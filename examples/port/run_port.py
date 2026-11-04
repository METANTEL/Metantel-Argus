# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Replay the port's days into the memory and let Argus warn and forecast as slowdowns begin.

Two hours into every traffic slowdown the watcher fires. Argus sees only what was known then: the hourly traffic so
far, earlier slowdowns that have played out, and the daily reports up to the day before. It warns the harbor operations
manager and forecasts how long the slowdown will last and how long the queue will take to clear.

Forecasts are scored against what actually happened, next to two baselines that use no similarity: the median of all
earlier slowdowns, and a fixed guess (the first slowdown's outcome carried forward is not used; with no history the
baseline is empty).

    python examples/port/run_port.py [--until 2024-04-01] [--no-agent]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timedelta

from argus.agent import Agent, Episodes
from argus.config import RUNS
import os

from argus.memory import DryEdip, Edip
from argus.models import Models, ledger
from argus.replay import Replay
from argus.sites.port import pack as S

TRAFFIC = ["time", "moving_bay_channel", "moving_upper_channel", "moving_total", "inbound_transits", "outbound_transits",
           "waiting_outside", "at_anchor", "tugs_working", "vis_galveston_mi", "vis_baytown_mi"]
EVENTS = ["time", "mmsi", "vessel", "type", "event", "zone", "lat", "lon", "sog", "note"]
VESSELS = ["mmsi", "name", "imo", "type", "length_m", "draft_m"]
SLOW = ["start", "end", "hours", "cause", "hours_so_far", "min_traffic_ratio_so_far", "min_visibility_mi_so_far",
        "queue_start", "baseline_moving_per_hour", "min_traffic_ratio", "queue_peak", "queue_growth", "peak_at",
        "recovery_hours", "min_visibility_mi", "transits_lost", "known_at"]
WRITEUP = ("You write short situation notes for port operations staff. From the facts below, and nothing else, write "
           "three or four plain sentences: what happened, how big it was against normal, and how the queue behaved. Keep "
           "every number exactly as given. Do not add causes, names or advice that the facts do not state.\n\nFacts: {facts}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default=None)
    ap.add_argument("--no-agent", action="store_true")
    a = ap.parse_args()
    run = RUNS / "port" / time.strftime("%Y%m%d-%H%M")
    run.mkdir(parents=True, exist_ok=True)
    edip, models = (DryEdip() if os.environ.get("ARGUS_DRY") else Edip()), Models()
    data = S.build()
    rows = S.slowdown_rows(data["status"], data["slowdowns"])
    rp = Replay(edip, run / "replay.jsonl")
    rp.stream("port/traffic_hourly.csv", TRAFFIC, data["status"], "time", S.TAGS)
    rp.stream("port/vessel_events.csv", EVENTS, data["events"], "time", S.TAGS)
    first = data["status"][0]["time"]
    for v in data["vessels"]:
        v["_at"] = first
    rp.stream("port/vessels.csv", VESSELS, data["vessels"], "_at", S.TAGS)
    rp.stream("port/slowdowns.csv", SLOW, rows, "known_at", S.TAGS)
    for d, name, text in S.daily_reports(data["status"], data["events"], data["slowdowns"]):
        rp.doc(f"{d} 23:59", name, text, "report", S.TAGS + ["code=DAILY"])
    for r in rows:
        facts = S.slowdown_facts(r)
        try:
            if os.environ.get("ARGUS_DRY"):
                raise RuntimeError("dry run")
            prose = models.text(WRITEUP.format(facts=facts), provider="baseten", effort=None, max_tokens=600)
        except Exception as e:  # noqa: BLE001 - the figures alone still make a usable note
            prose = f"(write-up unavailable: {str(e)[:80]})"
        text = f"# Slowdown {r['start']} UTC — {r['cause']}\n\n{prose}\n\n## Figures\n\n{facts}\n"
        tags = S.TAGS + ["code=SLOWDOWN"] + (["code=FOG"] if "fog" in r["cause"] else [])
        rp.doc(r["known_at"], f"port/slowdowns/{r['start'][:10]}-{r['start'][11:13]}{r['start'][14:16]}.md", text, "incident", tags)

    agent = Agent(S.SITE, edip, models, Episodes(edip, {"slowdown": "port/slowdowns.csv"},
                                                     {"slowdown": S.EPISODE_FEATURES}, {"slowdown": S.EPISODE_OUTCOMES}))
    results: list[dict] = []
    for r in rows:
        at = (datetime.strptime(r["start"], "%Y-%m-%d %H:%M") + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        known = {k: r[k] for k in S.EPISODE_FEATURES}

        def fire(now: str, r=r, known=known) -> dict:
            analog = agent.episodes.similar("slowdown", now, known)
            prior = [x for x in rows if x["known_at"] <= now]
            base = {o: statistics.median([float(x[o]) for x in prior if x[o] != ""]) if any(x[o] != "" for x in prior) else None
                    for o in ("hours", "recovery_hours")}
            rec = {"at": now, "start": r["start"], "known": known, "truth": {o: r[o] for o in ("hours", "recovery_hours", "queue_growth", "cause")},
                   "analog": analog.get("outcome_spread"), "analog_n": len(analog.get("episodes") or []),
                   "baseline_median_all_prior": base, "prior_n": len(prior)}
            if not a.no_agent:
                text = (f"At {now} UTC the traffic watcher fired: for the last 2 hours deep-draft traffic in the channels has been "
                        f"at {int(float(known['min_traffic_ratio_so_far']) * 100) if known['min_traffic_ratio_so_far'] != '' else '?'}% of normal. "
                        f"Lowest visibility so far: {known['min_visibility_mi_so_far'] or 'not reported'} mi. Ships waiting offshore when it began: "
                        f"{known['queue_start']}. Forecast how long this slowdown will last (total hours) and how long the queue will take "
                        f"to clear after traffic resumes, and say what operations should do now.")
                res = agent.run("warn", text, now, audience="manager")
                rec.update({"answer": res.answer, "usd": res.usd, "seconds": res.seconds, "tools": [t["tool"] for t in res.trace]})
                # In dense fog, the same moment written for the people on the water and for the executive as well.
                vis = known["min_visibility_mi_so_far"]
                if vis != "" and float(vis) <= 0.5:
                    for aud in ("operator", "executive"):
                        r2 = agent.run("warn", text, now, audience=aud)
                        rec.setdefault("other_audiences", {})[aud] = {"answer": r2.answer, "usd": r2.usd, "seconds": r2.seconds}
            results.append(rec)
            return {"headline": (rec.get("answer") or {}).get("headline"), "analog": rec["analog"]}
        rp.checkpoint(at, f"slowdown {r['start']}", fire)

    stats = rp.run(until=a.until)
    (run / "slowdown_warnings.json").write_text(json.dumps(results, indent=1, default=str))

    def err(pred: float | None, truth: str) -> float | None:
        return None if pred is None or truth == "" else abs(float(pred) - float(truth))

    def agent_forecast(x: dict, words: tuple[str, ...]) -> float | None:
        for f in (x.get("answer") or {}).get("forecasts") or []:
            what = str(f.get("what") or "").lower()
            if any(w in what for w in words) and isinstance(f.get("value"), (int, float)):
                return float(f["value"])
        return None

    rowsc = []
    for x in results:
        an = x.get("analog") or {}
        rowsc.append({"start": x["start"], "prior_n": x["prior_n"], "truth_hours": x["truth"]["hours"],
                      "analog_hours": (an.get("hours") or {}).get("median"), "baseline_hours": x["baseline_median_all_prior"]["hours"],
                      "truth_recovery": x["truth"]["recovery_hours"],
                      "analog_recovery": (an.get("recovery_hours") or {}).get("median"),
                      "baseline_recovery": x["baseline_median_all_prior"]["recovery_hours"],
                      "agent_hours": agent_forecast(x, ("last", "duration", "total", "slowdown")),
                      "agent_recovery": agent_forecast(x, ("queue", "clear", "recover"))})
    for r in rowsc:
        r["err_analog_hours"], r["err_baseline_hours"] = err(r["analog_hours"], r["truth_hours"]), err(r["baseline_hours"], r["truth_hours"])
        r["err_analog_recovery"], r["err_baseline_recovery"] = err(r["analog_recovery"], r["truth_recovery"]), err(r["baseline_recovery"], r["truth_recovery"])
        r["err_agent_hours"], r["err_agent_recovery"] = err(r["agent_hours"], r["truth_hours"]), err(r["agent_recovery"], r["truth_recovery"])

    def mae(k: str) -> float | None:
        v = [r[k] for r in rowsc if r[k] is not None]
        return round(statistics.fmean(v), 2) if v else None

    summary = {"replay": stats, "slowdowns": len(rows), "warned": len(results),
               "mae_hours": {"analog": mae("err_analog_hours"), "agent": mae("err_agent_hours"), "median_of_prior": mae("err_baseline_hours")},
               "mae_recovery_hours": {"analog": mae("err_analog_recovery"), "agent": mae("err_agent_recovery"),
                                      "median_of_prior": mae("err_baseline_recovery")},
               "per_slowdown": rowsc, "spend": ledger.summary(), "edip_calls": edip.calls}
    (run / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
