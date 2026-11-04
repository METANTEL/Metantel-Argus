# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Maintenance and operations on every compressor warning of 2020 (MetroPT-3), coordinating through the hive.

For each of the watcher's 13 firings: maintenance plans from the memory; an inspection it wants collides with
operations' standing use of the train; they negotiate (request, accept or counter or decline, and maintenance's answer
to a counter); what they cannot settle goes to the depot manager as a card. Scored against the operator's four leak
reports: was an inspection agreed before the leak began, and how many agreed inspections came before nothing.

    python examples/plant/run_hive_plant.py
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from argus.config import RUNS
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.plant import feed as E
from argus.sites.plant import pack as P
from argus.sites.plant import team as H

FMT = "%Y-%m-%d %H:%M"


def main() -> None:
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "hive-plant" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    hive = H.make(link, edip, models, run=run)
    mt, op = hive["maintenance"], hive["operations"]
    for m in (mt, op):
        m.announce()
    firings = P.firings()                         # the warnings of the latest replay (run_equipment.py)
    failures = sorted(E.FAILURES, key=lambda f: f["start"])
    results = []
    for k, f in enumerate(firings):
        now, ev = f["fired_at"], f"apu-{f['fired_at'][:10]}-{f['fired_at'][11:13]}"
        for m in (mt, op):
            m.announce()
        op.link.intend(op.agent, H.UNIT, "use", "APU-1's train is on today's timetable (peaks 07:00-10:00 and 17:00-20:00)")
        text = (f"At {now} the compressor watcher fired on APU-1: an abnormal episode began at {f['episode_start']} and its "
                f"first hour looked severe. Decide what maintenance does about it: inspect now, inspect at the next off-peak "
                f"window, or watch.")
        o = mt.think("plan", text, now, "supervisor", "", H.PLAN_JSON)
        plan = (o["answer"] or {}).get("plan") or {}
        rec = {"fired_at": now, "plan": plan, "level": (o["answer"] or {}).get("level"), "usd": o["usd"], "tools": o["tools"]}
        if plan.get("action") in ("inspect_now", "inspect_off_peak"):
            hits = mt.link.intend(mt.agent, H.UNIT, "change", f"take APU-1's train out for a leak inspection from "
                                  f"{plan.get('window_start')} for {plan.get('window_hours')} h: {plan.get('why', '')}")
            rec["collided_with"] = [c["agent"] for c in hits]
            ask = (f"[{ev}] Maintenance asks to take APU-1's train out from {plan.get('window_start')} for "
                   f"{plan.get('window_hours')} h. Why: {plan.get('why', '')} Risk: {plan.get('risk', '')}")
            link.send(mt.agent, op.agent, ask, importance="high")
            link.inbox(op.agent)
            dow = datetime.strptime(now[:10], "%Y-%m-%d").strftime("%A")
            reply = op.ask_json(f"{ask}\nIt is {now} ({dow}). Answer within your authority (the charter): accept the window, "
                                "counter with a window you can release the train for, or decline. Reply with JSON only: "
                                '{"answer": "accept|counter|decline", "window_start": "YYYY-MM-DD HH:MM", "reply": "one or two '
                                'sentences to maintenance"}', max_tokens=2500)
            link.send(op.agent, mt.agent, f"[{ev}] {reply.get('answer', '?')}: {reply.get('reply', '')}")
            link.inbox(mt.agent)
            rec["operations"] = reply
            agreed = reply.get("window_start") if reply.get("answer") == "accept" else None
            if reply.get("answer") == "accept":
                agreed = plan.get("window_start") or reply.get("window_start")
            elif reply.get("answer") == "counter":
                back = mt.ask_json(f"[{ev}] Operations counters: {reply.get('reply', '')} (window from {reply.get('window_start')}). "
                                   f"Your plan: {json.dumps(plan)}. Can you accept it within the plant's goals, or does the "
                                   'depot manager need to decide? Reply with JSON only: {"accept": true|false, "why": "one sentence"}',
                                   max_tokens=2000)
                rec["maintenance_answer"] = back
                agreed = reply.get("window_start") if back.get("accept") is True else None
            if agreed:
                got = mt.link.claim(mt.agent, [H.UNIT], write=True, version=agreed)
                rec["agreed_window"] = agreed
                rec["made_stale"] = [s["agent"] for s in got.get("stale", [])] if "granted" in got else []
                link.add_facts(mt.agent, [{"text": f"Inspection of APU-1's train agreed with operations from {agreed} "
                                           f"({plan.get('window_hours')} h): {plan.get('why', '')}", "kind": "decision",
                                           "subjects": ["plant/maintenance", "plant/operations", f"run:{run}"], "since": now}])
                link.release(mt.agent, [H.UNIT])
            else:
                card = link.card(mt.agent, H.UNIT, f"APU-1 warning at {now}: maintenance and operations disagree on an inspection",
                                 f"Maintenance: {ask}\nOperations: {reply.get('reply', '')}",
                                 [{"id": "inspect-as-maintenance-asks", "label": "Inspect when maintenance asks"},
                                  {"id": "keep-in-service", "label": "Keep the train in service and watch"},
                                  {"id": "inspect-at-operations-window", "label": "Inspect in operations' window"}],
                                 [mt.agent, op.agent], {mt.agent: ask, op.agent: str(reply.get("reply", ""))},
                                 card_id=f"plant-{ev.lower()}", at=now)
                rec["card"] = card["id"]
            link.clear(mt.agent, H.UNIT)
        nxt = next((x for x in failures if x["start"] > now), None)
        lead = (datetime.strptime(nxt["start"], FMT) - datetime.strptime(now, FMT)).total_seconds() / 3600 if nxt else None
        rec["next_failure"] = {"id": nxt["id"], "start": nxt["start"], "hours_after": round(lead, 1)} if nxt else None
        rec["before_failure"] = bool(lead is not None and lead <= 72)
        rec["inspection_before_failure"] = bool(rec["before_failure"] and rec.get("agreed_window")
                                                and rec["agreed_window"] < nxt["start"])
        results.append(rec)
        print(now, plan.get("action"), "| ops:", (rec.get("operations") or {}).get("answer"), "| agreed:", rec.get("agreed_window"),
              "| card:", rec.get("card", ""), "| failure in 72 h:", rec["before_failure"], flush=True)
    summary = {"run": run, "firings": len(results),
               "actions": {a: sum(1 for r in results if r["plan"].get("action") == a) for a in ("inspect_now", "inspect_off_peak", "watch")},
               "collisions": sum(1 for r in results if r.get("collided_with")),
               "agreed": sum(1 for r in results if r.get("agreed_window")), "to_people": sum(1 for r in results if r.get("card")),
               "firings_before_a_failure": sum(r["before_failure"] for r in results),
               "agreed_inspection_before_the_failure": sum(r["inspection_before_failure"] for r in results),
               "agreed_inspections_with_no_failure_within_72h": sum(1 for r in results if r.get("agreed_window") and not r["before_failure"]),
               "coordination_calls": link.counts, "spend": ledger.summary()}
    (out / "firings.json").write_text(json.dumps(results, indent=1, default=str))
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
