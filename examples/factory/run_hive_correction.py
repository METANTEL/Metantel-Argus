# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The hive correcting itself, on the shift's own record. At 08:05 the safety manager answered from a memory that
counted 102 close calls against a vehicle the cameras had followed badly, and safety and logistics agreed to keep it
out of K9 and K10. The camera supervisor found it was a forklift parked by the wall (examples/factory/supervise_factory.py) and
the memory was rebuilt. Here the correction reaches everyone who relied on the old picture:

1. the supervisor takes the hall's memory it changed: the copy safety answered from goes stale;
2. safety re-reads the supervisor's finding and decides whether its decision stands; withdrawing it takes the route,
   and the copies logistics and floor operations hold go stale in turn: each re-reads and says what changes;
3. safety asks its question again of the corrected memory, and the hive acts on what is really there (argus.sites.factory.team
   .negotiate): the new change collides with logistics' use of the route, they negotiate, floor operations re-plans.

    python examples/factory/run_hive_correction.py runs/supervise/<id> runs/hive-factory/<old id>
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from argus.config import RUNS
from argus.hive.link import Link
from argus.hive.mind import Member
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.factory import feed as FX
from argus.sites.factory import team as H

NOW = f"{FX.CLOCK[:10]} 08:05"
QUESTION = "What single change would remove the most close calls? Show me the evidence."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("supervision", type=Path, help="the camera supervisor's run")
    ap.add_argument("old", type=Path, help="the hive run whose decision rested on the old memory")
    ap.add_argument("--provider", default="baseten")
    ap.add_argument("--answers", type=Path, default=None,
                    help="safety's answer already given on the corrected memory (the factory questions' q4), instead of asking again")
    a = ap.parse_args()
    log = json.loads((a.supervision / "supervision.json").read_text())
    issues = log["issues"] if isinstance(log, dict) else log         # the first runs saved the bare list
    finding = next(i for i in issues if i["check"] == "implausible" and i["remedy"] in ("correct", "rederive"))
    old = json.loads((a.old / "decision.json").read_text())
    old_vehicle = old.get("vehicle") or "A-vehicle-c15"
    old_route = f"route:{old_vehicle}"
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "hive-factory" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    hive = H.make(link, edip, models, run, provider=a.provider)
    sf, lg, fl = hive["safety"], hive["logistics"], hive["floor"]
    sup = Member(link, H.CHARTER, "factory/perception-a", "camera supervisor", "factory/perception",
                 "Everyone and every machine in Hall A's view followed, and nothing in memory the cameras did not really see",
                 models=models, provider=a.provider)
    for m in (*hive.values(), sup):
        m.announce()
    rec: dict = {"run": run, "now": NOW, "supervision": str(a.supervision), "old": str(a.old), "finding": finding,
                 "old_decision": old.get("agreed"), "old_vehicle": old_vehicle}
    memory = "memory:factory/hall-a"
    # what each agent relied on: safety answered from the hall's memory; logistics and floor hold the agreed route
    sf.hold(memory, "v1", "Hall A's tables as at 08:05, before the camera supervisor's correction")
    lg.hold(old_route, "v2", old.get("agreed"))
    fl.hold(old_route, "v2", old.get("agreed"))

    # 1. the supervisor publishes its correction: the memory it changed is claimed, every copy of it goes stale
    got = sup.change(memory, "v2", f"corrected: {finding['subject']} is a parked forklift; Hall A rebuilt from every camera")
    sup.done(memory)
    rec["memory_stale_for"] = [s["agent"] for s in got.get("stale", [])]
    print("memory stale for:", rec["memory_stale_for"], flush=True)

    # 2. safety re-reads and decides whether its decision stands
    stale = sf.stale([memory])
    rec["safety_saw_stale"] = stale
    facts = link.facts(subject="factory/perception", limit=20)
    corrections = [f["text"] for f in facts if f["kind"] in ("event", "lesson")][:4]
    verdict = sf.ask_json(f"Your copy of Hall A's memory went stale: the camera supervisor changed it. What it found:\n- "
                          + "\n- ".join(corrections) + f"\n\nAt 08:05 you decided, with logistics: {old.get('agreed')} "
                          f"(on {old_vehicle}, from {old.get('whatif', {}).get('avoid', {}).get('close_calls', '?')} close calls "
                          "in memory). Does that decision stand on the corrected memory? Reply with JSON only: "
                          '{"stands": true|false, "why": "one sentence", "to_logistics_and_floor": "one or two sentences"}',
                          max_tokens=2000)
    rec["safety_review"] = verdict
    print("safety:", json.dumps(verdict)[:300], flush=True)
    if verdict.get("stands") is not True:
        old_fact = next((f for f in link.facts(subject=old_route.lower()) if f["kind"] == "decision"), None)
        if old_fact and not old_fact.get("replacedBy"):
            try:
                link.correct(sf.agent, old_fact["id"], f"Withdrawn: {verdict.get('why', '')}", "the camera supervisor's correction", NOW)
            except Exception as e:  # noqa: BLE001 - the withdrawal is still sent to everyone who holds the route
                rec["correct_error"] = str(e)[:200]
        took = sf.change(old_route, "v3", f"withdrawn: {verdict.get('why', '')}")
        sf.done(old_route)
        rec["route_stale_for"] = [s["agent"] for s in took.get("stale", [])]
        link.send(sf.agent, lg.agent, f"[{old_route}] withdrawn: {verdict.get('to_logistics_and_floor', '')}", importance="high")
        link.send(sf.agent, fl.agent, f"[{old_route}] withdrawn: {verdict.get('to_logistics_and_floor', '')}", importance="high")
        for m, key in ((lg, "logistics_after"), (fl, "floor_after")):
            if m.stale([old_route]):
                link.inbox(m.agent)
                rec[key] = m.ask_json(f"Your copy of {old_route} went stale: safety withdrew the 08:05 decision. Safety says: "
                                      f"{verdict.get('to_logistics_and_floor', '')} What changes for your section now? Reply with "
                                      'JSON only: {"change": "one line", "why": "one sentence"}', max_tokens=1500)
                print(key, json.dumps(rec[key])[:200], flush=True)
        sf.hold(memory, "v2", "Hall A's tables after the camera supervisor's correction")

    # 3. safety asks its question again of the corrected memory, and the hive acts on it
    if a.answers:
        q4 = next(q for q in json.loads(a.answers.read_text()) if q["id"] == "q4")
        o = type("Answer", (), {"answer": q4["answer"], "trace": q4["trace"], "usd": q4.get("usd", 0.0)})()
        rec["answer_from"] = str(a.answers)
    else:
        o = sf.brain.run("plan", QUESTION, NOW, "manager", context=H.KNOWN, preamble=sf.system())
    rec["answer"] = {"answer": o.answer, "trace": o.trace, "usd": o.usd}
    act = next((x for x in (o.answer or {}).get("actions") or [] if "safety" in str(x.get("who", "")).lower()), None)
    ran = [s for s in o.trace if s.get("tool") == "whatif" and '"by_shift"' in str(s.get("result"))]
    # the what-if behind safety's own action: the one about the vehicle the action names, else the one that avoids most
    wi = next((s for s in ran if act and str(s["args"].get("vehicle", "")) in act["action"]), None) or \
        max(ran, key=lambda s: int((json.loads(s["result"]) if str(s["result"]).startswith("{") and str(s["result"]).endswith("}")
                                    else {}).get("avoid", {}).get("inside_zones", 0)), default=None)
    if act and not wi:          # the answer named the change without replaying it: the harness replays it as evidence
        import re
        named = re.search(r"\b([A-D]-(?:vehicle|robot|transporter|forklift|humanoid)-[a-z]?\d+)\b", act["action"])
        zones_named = re.findall(r"\b([A-Z]\d{1,2})\b", act["action"])
        if named:
            wi = {"tool": "whatif", "args": {"hall": named.group(1)[0], "vehicle": named.group(1), "avoid_zones": zones_named},
                  "by": "harness"}
    print("new answer:", (o.answer or {}).get("headline"), "| what-if:", (wi or {}).get("args"), flush=True)
    if act and wi:
        args = wi["args"]
        vehicle = str(args.get("vehicle"))
        zones = [str(z).upper() for z in args.get("avoid_zones") or []]
        hall = str(args.get("hall") or vehicle[:1]).upper()[:1]
        wf = H.whatif_fn(H.compiled())({"hall": hall, "vehicle": vehicle, "avoid_zones": zones}, NOW)
        if "error" not in wf and not zones:          # no zones named: the ones where its close calls repeat most
            calls = Counter(e["zone"] for e in H.compiled()[hall]["tables"]["close_calls"] if e["vehicle"] == wf["vehicle"])
            zones = [z for z, _ in calls.most_common(2)]
            wf = H.whatif_fn(H.compiled())({"hall": hall, "vehicle": wf["vehicle"], "avoid_zones": zones}, NOW)
        if "error" not in wf:
            rec["new"] = H.negotiate(link, sf, lg, fl, wf["vehicle"], zones, act["action"], wf, NOW, run)
            print("new decision:", json.dumps({k: rec["new"].get(k) for k in ("collided_with", "logistics", "agreed", "made_stale",
                                                                                "floor")})[:600], flush=True)
    rec["coordination_calls"] = link.counts
    rec["spend"] = ledger.summary()
    (out / "decision.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps(rec["spend"], indent=1))
    print(out)


if __name__ == "__main__":
    main()
