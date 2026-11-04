# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Replay the compressor's six months into the memory and let Argus warn as it goes.

At the first hour of every severe episode the watcher fires. Argus then sees only what was known at that hour: the
episode so far, the tables up to then, earlier episodes whose outcome is already known, and the work orders of repairs
already done. It warns the shift supervisor with a risk estimate drawn from similar past episodes.

    python examples/plant/run_equipment.py [--until 2020-09-01] [--no-agent]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timedelta

from argus.agent import Agent, Episodes
from argus.config import RUNS
from argus.memory import Edip
from argus.models import Models, ledger
from argus.replay import Replay
from argus.sites.plant import feed as E
from argus.sites.plant import pack as S

FIVE = ["time", "unit", "tp2_bar", "tp3_bar", "tp3_min_bar", "reservoir_min_bar", "oil_temp_c", "oil_temp_max_c",
        "motor_current_a", "duty_pct", "load_cycles", "low_pressure_s"]
DAILY = ["date", "unit", "hours_recorded", "duty_pct", "duty_pct_7d_median", "load_cycles", "cycles_per_hour",
         "cycles_per_hour_7d_median", "tp3_min_bar", "reservoir_min_bar", "oil_temp_max_c", "motor_current_a", "low_pressure_min"]
EPIS = ["start", "end", "hours", "severity", "peak_duty_pct", "baseline_duty_pct", "peak_cycles_per_hour",
        "baseline_cycles_per_hour", "low_pressure_min", "min_tp3_bar", "signals", "failure_within_72h", "failure_id",
        "hours_to_failure", "known_at"]
TAGS = ["site=plant", "asset=APU-1"]


def first_hour(fm: list[dict], start: str) -> dict:
    s = datetime.strptime(start, "%Y-%m-%d %H:%M")
    rows = [r for r in fm if s <= datetime.strptime(r["time"], "%Y-%m-%d %H:%M") < s + timedelta(hours=1)]
    return {"peak_duty_pct": round(max(r["duty_pct"] for r in rows), 1), "low_pressure_min": round(sum(r["low_pressure_s"] for r in rows) / 60, 1),
            "min_tp3_bar": round(min(r["tp3_min_bar"] for r in rows), 2), "hours": 1.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default=None)
    ap.add_argument("--no-agent", action="store_true")
    a = ap.parse_args()
    run = RUNS / "equipment" / time.strftime("%Y%m%d-%H%M")
    run.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    data = S.build()
    for d in data["daily"]:
        d["known"] = d["date"] + " 23:59"
    rp = Replay(edip, run / "replay.jsonl")
    rp.stream("plant/apu_5min.csv", FIVE, data["five_min"], "time", TAGS)
    rp.stream("plant/apu_daily.csv", DAILY, data["daily"], "known", TAGS)
    rp.stream("plant/apu_episodes.csv", EPIS, data["episodes"], "known_at", TAGS)
    for d in data["daily"]:
        rp.doc(d["known"], f"plant/apu/daily/{d['date']}.md", S.daily_note(d), "note", TAGS + ["code=DAILY"])
    for f in E.FAILURES:
        rp.doc(f["repaired"], f"plant/work-orders/{f['id']}.md", S.work_order(f), "ticket", TAGS + ["code=WORKORDER", "code=AIRLEAK"])

    agent = Agent(S.SITE, edip, models, Episodes(edip, {"compressor": "plant/apu_episodes.csv"},
                                                     {"compressor": S.EPISODE_FEATURES}, {"compressor": S.EPISODE_OUTCOMES}))
    warnings: list[dict] = []
    for ep in data["episodes"]:
        if ep["severity"] != "severe" or ep["during_failure"]:
            continue
        at = (datetime.strptime(ep["start"], "%Y-%m-%d %H:%M") + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
        so_far = first_hour(data["five_min"], ep["start"])

        def fire(now: str, ep=ep, so_far=so_far) -> dict:
            analog = agent.episodes.similar("compressor", now, so_far)
            rec = {"at": now, "episode_start": ep["start"], "so_far": so_far, "truth_failure_within_72h": ep["failure_within_72h"],
                   "truth_failure_id": ep["failure_id"], "analog": {k: analog.get(k) for k in ("outcome_spread", "finished_before_now")}}
            if not a.no_agent:
                text = (f"At {now} the compressor watcher fired on APU-1. In the first hour of this episode (from {ep['start']}): "
                        f"compressor loading up to {so_far['peak_duty_pct']}% of the hour, low-pressure switch on "
                        f"{so_far['low_pressure_min']} min, lowest TP3 pressure {so_far['min_tp3_bar']} bar.")
                r = agent.run("warn", text, now, audience="supervisor")
                rec.update({"answer": r.answer, "usd": r.usd, "seconds": r.seconds, "tools": [t["tool"] for t in r.trace]})
            warnings.append(rec)
            return {"headline": (rec.get("answer") or {}).get("headline"), "risk": rec["analog"]}
        rp.checkpoint(at, f"warn {ep['start']}", fire)

    stats = rp.run(until=a.until)
    (run / "warnings.json").write_text(json.dumps(warnings, indent=1, default=str))
    # Scoring: lead time before each reported failure, and warnings not followed by one.
    fails = [(datetime.strptime(f["start"], "%Y-%m-%d %H:%M"), f["id"]) for f in E.FAILURES]
    lead = {}
    for fs, fid in fails:
        ws = [w for w in warnings if timedelta(0) <= fs - datetime.strptime(w["at"], "%Y-%m-%d %H:%M") <= timedelta(hours=72)]
        lead[fid] = round(max((fs - datetime.strptime(w["at"], "%Y-%m-%d %H:%M")).total_seconds() / 3600 for w in ws), 1) if ws else None
    false = [w["at"] for w in warnings if not w["truth_failure_within_72h"]]
    months = 7.0
    summary = {"replay": stats, "warnings": len(warnings), "lead_hours_by_failure": lead,
               "failures_warned": sum(v is not None for v in lead.values()), "false_warnings": len(false),
               "false_warnings_per_month": round(len(false) / months, 2), "spend": ledger.summary(), "edip_calls": edip.calls}
    (run / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
