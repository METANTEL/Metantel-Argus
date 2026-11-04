# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The port as a hive, on every fog slowdown of 2024, against an anchorage manager working alone.

The memory holds the whole year (`examples/port/ingest_port_year.py`); every agent's tools keep it at its moment. At 2 h into
each slowdown, and again at 5 h and 8 h while it lasts:
- the channel manager plans the traffic and, when its expected reopening moves by an hour or more, publishes a new
  version of its plan, which makes the anchorage manager's copy stale;
- the arrivals watcher publishes the arrival rate and the channel's inbound capacity;
- the hive's anchorage manager re-plans on the current copies, asks the channel for what it needs, and a refusal goes
  to people as a decision card;
- the anchorage manager working alone plans at 2 h and reviews every 6 h, estimating the reopening itself.
The director briefs the executive from both hive plans at 2 h.

Scored against what happened: the error of each recovery forecast, and how far each anchorage plan's reopening time
is from the channel's current one (the hours a section works from a plan the channel no longer holds).

    python examples/port/run_hive_port.py [--events fog|all] [--limit N] [--workers 3]
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from argus.config import DATA, RUNS, load_cache
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.port import pack as S
from argus.sites.port import team as H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default="fog", choices=["fog", "nonfog", "all"])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--event", default="", help="only the slowdown that starts at this time (YYYY-MM-DD HH:MM)")
    ap.add_argument("--resume", default="", help="a run id: continue it, skipping the events it already finished")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--provider", default="baseten")
    ap.add_argument("--weather", action="store_true", help="a weather watcher shares the airport forecast with the channel")
    a = ap.parse_args()
    run = a.resume or time.strftime("%Y%m%d%H%M")
    out = RUNS / "hive-port" / run
    out.mkdir(parents=True, exist_ok=True)
    data = load_cache(DATA / "ais" / "compiled-2024.pkl")
    rows = S.slowdown_rows(data["status"], data["slowdowns"])
    status = {r["time"]: r for r in data["status"]}
    arrivals = H.Arrivals(data["status"], data["events"])
    weather = H.Weather(data["status"]) if a.weather else None
    low_vis = lambda r: "fog" in r["cause"] or "haze" in r["cause"]  # noqa: E731
    events = [r for r in rows if a.events == "all" or (a.events == "fog") == low_vis(r)]
    events = [r for r in events if any(x["known_at"] <= H.at(r["start"], 2) for x in rows)]   # some history to learn from
    if a.event:
        events = [r for r in rows if r["start"] == a.event]
    if a.limit:
        events = events[:a.limit]
    done = {json.loads(f.read_text())["start"]: json.loads(f.read_text()) for f in out.glob("2024-*.json")} if a.resume else {}
    events = [r for r in events if r["start"] not in done]
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    router = H.Router(link)
    hive = H.make(link, edip, models, a.provider, run=run)
    members = [hive[k] for k in ("channel", "anchorage", "arrivals", "director") + (("weather",) if a.weather else ())]
    for m in members:
        m.announce()
    stop = threading.Event()

    def keepalive() -> None:
        while not stop.wait(60):
            for m in members:
                try:
                    m.announce()
                except Exception:  # noqa: BLE001 - presence is best effort; the next beat retries
                    pass
    threading.Thread(target=keepalive, daemon=True).start()
    print(f"{len(events)} events, run {run}", flush=True)

    def one(r: dict) -> dict:
        ev = H.event_id(r["start"])
        T, Q, A = f"plan:port/traffic/{ev}", f"plan:port/anchorage/{ev}", f"state:port/arrivals/{ev}"
        ch, an, ar, di, al, wx = (hive[k] for k in ("channel", "anchorage", "arrivals", "director", "anchorage_alone", "weather"))
        W = f"state:port/weather/{ev}"
        if weather:
            ch.hold(W, "0", None)
        tag = [f"event:{ev}", f"run:{run}"]
        checkpoints = [H.at(r["start"], h) for h in (2, 5, 8) if h == 2 or (r["end"] and H.at(r["start"], h) < r["end"])]
        rec = {"event": ev, "start": r["start"], "end": r["end"], "cause": r["cause"],
               "truth": {k: r[k] for k in ("hours", "recovery_hours", "queue_start", "queue_peak", "min_visibility_mi")}, "steps": []}
        an.hold(T, "0", None)
        an.hold(A, "0", None)
        channel_plan, ch_v, anchor_plan, an_v, alone_plan, alone_at = None, 0, None, 0, None, None
        for k, now in enumerate(checkpoints):
            text = H.situation(r, now, status)
            step: dict = {"at": now}
            ch_ctx = ""
            if weather:
                wv = weather.at(now)
                wx.change(W, str(k + 1), "weather update for the channel")
                link.add_facts(wx.agent, [{"text": H.Weather.sentence(wv), "kind": "state", "subjects": ["port/weather", *tag], "since": now}])
                wx.done(W)
                step["weather"] = wv
                if ch.stale([W]):
                    ch_ctx = f"WEATHER (from port/weather): {H.Weather.sentence(wv)}"
                    ch.hold(W, str(k + 1), wv)
            oc = ch.think("plan", text + " Plan the channel's traffic: the restriction that applies now, and when normal "
                          "deep-draft traffic will resume.", now, "manager", ch_ctx, H.CHANNEL_JSON)
            p = H.plan_of(oc)
            step["channel"] = {"plan": p, "usd": oc["usd"], "seconds": oc["seconds"], "tools": oc["tools"]}
            moved = H.hours_between(channel_plan.get("expected_end", ""), p.get("expected_end", "")) if channel_plan else None
            if not H.hours_between(r["start"], p.get("expected_end", "")):
                step["channel"]["missing"] = True          # no usable plan: the last published one stands
            elif channel_plan is None or moved is None or abs(moved) >= 1:
                ch_v += 1
                got = ch.change(T, str(ch_v), f"channel plan v{ch_v}: {p.get('state')} until {p.get('expected_end')}")
                link.add_facts(ch.agent, [{"text": H.summarise(p, "Channel", ch_v, now), "kind": "decision",
                                           "subjects": ["port/channel", *tag], "since": now}])
                ch.done(T)
                step["channel"]["published"] = ch_v
                step["channel"]["made_stale"] = [s["agent"] for s in got.get("stale", [])]
                channel_plan = p
            av = arrivals.at(now)
            ar.change(A, str(k + 1), "arrivals update for the anchorage")
            link.add_facts(ar.agent, [{"text": H.Arrivals.sentence(av), "kind": "state", "subjects": ["port/arrivals", *tag], "since": now}])
            ar.done(A)
            step["arrivals"] = av
            stale = an.stale([T, A])
            step["anchorage_stale"] = stale
            if T in stale or anchor_plan is None:
                msgs = router.take(an.agent, ev)
                ctx = (f"THE CHANNEL'S CURRENT PLAN (v{ch_v}, from port/channel): {json.dumps(channel_plan)}\n"
                       f"ARRIVALS (from port/arrivals): {H.Arrivals.sentence(av)}"
                       + ("\nMESSAGES:\n" + "\n".join(f"- {m['from']}: {m['text']}" for m in msgs) if msgs else ""))
                oa = an.think("plan", text + " Plan the offshore queue: how big it will get, the inbound order once traffic "
                              "resumes, and how long it will take to clear. Build on the channel's current plan for when "
                              "traffic resumes.", now, "manager", ctx, H.ANCHOR_JSON)
                anchor_plan, an_v = H.plan_of(oa), an_v + 1
                an.hold(T, str(ch_v), channel_plan)
                an.hold(A, str(k + 1), av)
                an.change(Q, str(an_v), f"anchorage plan v{an_v}")
                link.add_facts(an.agent, [{"text": H.summarise(anchor_plan, "Anchorage", an_v, now), "kind": "decision",
                                           "subjects": ["port/anchorage", *tag], "since": now}])
                an.done(Q)
                step["anchorage"] = {"plan": anchor_plan, "usd": oa["usd"], "seconds": oa["seconds"], "tools": oa["tools"]}
                ask = str(anchor_plan.get("ask_channel") or "").strip()
                if ask:
                    link.send(an.agent, ch.agent, f"[{ev}] {ask}", importance="high")
                    router.take(ch.agent, ev)
                    reply = ch.ask_json(f"[{ev}] The anchorage manager asks you: {ask}\nYour current plan: {json.dumps(channel_plan)}\n"
                                        f"The situation: {text}\nAnswer within your authority (the charter). Reply with JSON only: "
                                        '{"answer": "accept|decline", "reply": "one or two sentences to the anchorage manager"}',
                                        max_tokens=2500)
                    link.send(ch.agent, an.agent, f"[{ev}] {reply.get('answer', '?')}: {reply.get('reply', '')}")
                    step["ask"] = {"ask": ask, "answer": reply}
                    if reply.get("answer") == "decline":
                        # A refusal is not yet a conflict: the anchorage decides whether it can live with it or needs people.
                        router.take(an.agent, ev)
                        follow = an.ask_json(f"[{ev}] You asked the channel manager: {ask}\nThey declined: {reply.get('reply', '')}\n"
                                             f"Your plan: {json.dumps(anchor_plan)}\nCan the port still meet its goals with their "
                                             "answer, or does this need the harbor master? Bring people in only if it truly "
                                             'needs them. Reply with JSON only: {"escalate": true|false, "why": "one sentence"}',
                                             max_tokens=2000)
                        step["ask"]["follow"] = follow
                    if reply.get("answer") == "decline" and step["ask"]["follow"].get("escalate") is True:
                        card = link.card(an.agent, T, f"Slowdown {r['start']} UTC: the anchorage asks the channel for something it declined",
                                         f"The anchorage manager asked: {ask}\nThe channel manager declined: {reply.get('reply', '')}",
                                         [{"id": "keep-channel-plan", "label": "Keep the channel's plan"},
                                          {"id": "grant-the-ask", "label": "Grant the anchorage's request"},
                                          {"id": "other", "label": "Something else (say what in the note)"}],
                                         [an.agent, ch.agent], {an.agent: ask, ch.agent: str(reply.get("reply", ""))},
                                         card_id=f"port-{ev.lower()}-{k}", at=now)
                        step["card"] = card["id"]
            if alone_plan is None or (H.hours_between(alone_at, now) or 0) >= 6:
                ol = al.think("plan", text + " Plan the offshore queue: how big it will get, the inbound order once traffic "
                              "resumes, and how long it will take to clear. Estimate yourself when traffic will resume.",
                              now, "manager", "", H.ANCHOR_JSON)
                alone_plan, alone_at = H.plan_of(ol), now
                step["alone"] = {"plan": alone_plan, "usd": ol["usd"], "seconds": ol["seconds"], "tools": ol["tools"]}
            gap = lambda pl: H.hours_between((channel_plan or {}).get("expected_end", ""), (pl or {}).get("assumed_reopen", ""))  # noqa: E731
            step["coherence"] = {"hive_gap_h": gap(anchor_plan), "alone_gap_h": gap(alone_plan)}
            if k == 0:
                brief = di.ask_json(f"Slowdown at the port. {text}\nThe channel's plan: {json.dumps(channel_plan)}\nThe "
                                    f"anchorage's plan: {json.dumps(anchor_plan)}\nArrivals: {H.Arrivals.sentence(av)}\n"
                                    "Brief the executive. Reply with JSON only: {\"headline\": \"one line\", \"brief\": \"two or "
                                    "three sentences: impact, trend, and the one decision that needs them, if any\", "
                                    "\"needs_people\": \"the decision for people, or empty\"}", max_tokens=2500)
                step["director"] = brief
            rec["steps"].append(step)
            print(f"{ev} +{H.hours_between(r['start'], now):.0f}h channel->{p.get('expected_end')} hive->{(anchor_plan or {}).get('assumed_reopen')} "
                  f"alone->{(alone_plan or {}).get('assumed_reopen')} stale={stale} ask={'ask' in step} card={step.get('card', '')}", flush=True)
        (out / f"{ev}.json").write_text(json.dumps(rec, indent=1, default=str))
        return rec

    results = list(done.values())
    with ThreadPoolExecutor(a.workers) as ex:
        for f in [ex.submit(one, r) for r in events]:
            try:
                results.append(f.result())
            except Exception as e:  # noqa: BLE001 - one event's failure is reported, the rest go on
                print(f"FAILED: {type(e).__name__}: {str(e)[:300]}", flush=True)
    stop.set()

    def err(pred, truth) -> float | None:
        p, t = H.num(pred), H.num(truth)
        return None if p is None or t is None else abs(p - t)

    def mae(vals: list) -> float | None:
        v = [x for x in vals if x is not None]
        return round(statistics.fmean(v), 2) if v else None

    first = [(x, x["steps"][0]) for x in results if x["steps"]]
    summary = {
        "run": run, "events": len(results),
        "recovery_mae_h_first_plan": {
            "hive": mae([err((s.get("anchorage") or {}).get("plan", {}).get("recovery_hours"), x["truth"]["recovery_hours"]) for x, s in first]),
            "alone": mae([err((s.get("alone") or {}).get("plan", {}).get("recovery_hours"), x["truth"]["recovery_hours"]) for x, s in first]),
            "n": sum(1 for x, s in first if H.num(x["truth"]["recovery_hours"]) is not None)},
        "duration_mae_h_channel_first_plan": mae([err(s["channel"]["plan"].get("duration_hours"), x["truth"]["hours"]) for x, s in first]),
        "reopen_gap_h_mean": {"hive": mae([abs(st["coherence"]["hive_gap_h"]) if st["coherence"]["hive_gap_h"] is not None else None
                                           for x in results for st in x["steps"]]),
                              "alone": mae([abs(st["coherence"]["alone_gap_h"]) if st["coherence"]["alone_gap_h"] is not None else None
                                            for x in results for st in x["steps"]])},
        "checkpoints_with_gap_over_2h": {
            "hive": sum(1 for x in results for st in x["steps"] if (st["coherence"]["hive_gap_h"] is not None and abs(st["coherence"]["hive_gap_h"]) > 2)),
            "alone": sum(1 for x in results for st in x["steps"] if (st["coherence"]["alone_gap_h"] is not None and abs(st["coherence"]["alone_gap_h"]) > 2)),
            "checkpoints": sum(len(x["steps"]) for x in results)},
        "channel_revisions_published": sum(1 for x in results for st in x["steps"] if st["channel"].get("published", 0) > 1),
        "asks": sum(1 for x in results for st in x["steps"] if "ask" in st),
        "declined_to_people": sum(1 for x in results for st in x["steps"] if "card" in st),
        "coordination_calls": link.counts, "spend": ledger.summary(),
        "member_usd": {k: round(m.usd, 4) for k, m in hive.items()}}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
