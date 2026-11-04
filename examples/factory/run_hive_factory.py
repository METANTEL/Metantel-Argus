# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""One decision in the factory's hive, end to end. The safety manager's answer at 08:05 (stop A-vehicle-c15's route
through K9 and K10) collides with logistics' use of that route; the two negotiate in their own words over the
what-if's numbers; what they agree is written to the memory and every other copy of the route goes stale, so floor
operations re-reads it and says what changes for people's walkways. What they cannot settle goes to people as a card.

    python examples/factory/run_hive_factory.py runs/factory-qa/<id>/answers.json
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from argus.config import RUNS
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.factory import team as H

NOW = f"{H.FX.CLOCK[:10]} 08:05"
MODELS = {"director": "muse-wonder-1.0", "floor": "muse-spark-1.3", "safety": "muse-spark-1.3", "logistics": "muse-spark-1.3"}
VEHICLE, HALL, ZONES = "A-vehicle-c15", "A", ["K9", "K10"]
ROUTE = f"route:{VEHICLE}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("answers", type=Path, help="the factory questions' answers; the safety manager's q4 is the start")
    a = ap.parse_args()
    q4 = next(q for q in json.loads(a.answers.read_text()) if q["id"] == "q4")
    act = next(x for x in q4["answer"]["actions"] if "safety" in str(x.get("who", "")))
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "hive-factory" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    hive = H.make(link, edip, models, run, provider="meta", models_by_role=MODELS)
    sf, lg, fl = hive["safety"], hive["logistics"], hive["floor"]
    for m in hive.values():
        m.announce()
    wf = H.whatif_fn(H.compiled())({"hall": HALL, "vehicle": VEHICLE, "avoid_zones": ZONES}, NOW)
    av = wf["avoid"]
    rec: dict = {"run": run, "now": NOW, "from": str(a.answers), "zones": ZONES, "safety_answer": q4["answer"]["headline"], "safety_action": act,
                 "whatif": wf}
    # the route as logistics and floor operations hold it: their working copies
    route_v1 = f"{VEHICLE} runs its goods route through Hall A's K-aisles (K9, K10) this shift"
    lg.hold(ROUTE, "v1", route_v1)
    fl.hold(ROUTE, "v1", route_v1)
    link.intend(lg.agent, ROUTE, "use", f"{VEHICLE} carries goods through the K-aisles this shift")
    # safety says what it is about to change: the collision shows before anything is done
    why = (f"{av['inside_zones']} of its {av['close_calls']} close calls in 08:00-08:05 happened inside {', '.join(ZONES)}")
    hits = link.intend(sf.agent, ROUTE, "change", f"{act['action']}: {why}")
    rec["collided_with"] = [h["agent"] for h in hits]
    ask = H.route_ask(ROUTE, act["action"], wf, ZONES)
    rec["ask"] = ask
    link.send(sf.agent, lg.agent, ask, importance="high")
    link.inbox(lg.agent)
    reply = lg.ask_json(f"{ask}\nIt is {NOW}. Your copy of the route: {route_v1}. Answer within your authority (the charter): "
                        "accept the change, counter with a change you can make instead (re-route or re-time the vehicle), or "
                        "decline. Reply with JSON only: {\"answer\": \"accept|counter|decline\", \"change\": \"what will "
                        "happen to the route, in one line\", \"reply\": \"one or two sentences to the safety manager\"}",
                        max_tokens=2500)
    link.send(lg.agent, sf.agent, f"[{ROUTE}] {reply.get('answer', '?')}: {reply.get('reply', '')}")
    link.inbox(sf.agent)
    rec["logistics"] = reply
    agreed = reply.get("change") if reply.get("answer") == "accept" else None
    if reply.get("answer") == "accept" and not agreed:
        agreed = act["action"]
    if reply.get("answer") == "counter":
        back = sf.ask_json(f"[{ROUTE}] Logistics counters: {reply.get('reply', '')} (change: {reply.get('change', '')}). Your "
                           f"request was: {act['action']}. The what-if: {json.dumps(wf)}. Can you accept it within the site's "
                           "goals, or must people decide? Reply with JSON only: {\"accept\": true|false, \"why\": \"one sentence\"}",
                           max_tokens=2000)
        rec["safety_answer_to_counter"] = back
        link.send(sf.agent, lg.agent, f"[{ROUTE}] {'accepted' if back.get('accept') is True else 'not accepted'}: {back.get('why', '')}")
        agreed = reply.get("change") if back.get("accept") is True else None
    if agreed:
        got = sf.change(ROUTE, "v2", f"agreed with logistics: {agreed}")
        rec["agreed"] = agreed
        rec["made_stale"] = [s["agent"] for s in got.get("stale", [])]
        link.add_facts(sf.agent, [{"text": f"{VEHICLE}'s route, agreed by safety and logistics at {NOW}: {agreed}",
                                   "kind": "decision", "subjects": [sf.agent, lg.agent, ROUTE, f"run:{run}"], "since": NOW}])
        sf.done(ROUTE)
        # floor operations' copy went stale: it re-reads the decision before it acts, and says what changes for people
        rec["floor_stale"] = fl.stale([ROUTE])
        if rec["floor_stale"]:
            seen = link.facts(subject=ROUTE)
            rec["floor"] = fl.ask_json(f"Your copy of {ROUTE} went stale. The memory now says: "
                                       f"{json.dumps([f.get('text') for f in seen][-3:])}. It is {NOW}. What, if anything, "
                                       "changes for people's walkways and staffing in Hall A? Reply with JSON only: "
                                       "{\"change\": \"one line\", \"why\": \"one sentence\"}", max_tokens=2000)
            fl.hold(ROUTE, "v2", agreed)
    else:
        card = link.card(sf.agent, ROUTE, f"{VEHICLE}: safety and logistics disagree on its route",
                         f"Safety: {ask}\nLogistics: {reply.get('reply', '')}",
                         [{"id": "as-safety-asks", "label": "Keep it out of K9 and K10"},
                          {"id": "as-logistics-says", "label": "As logistics proposes"},
                          {"id": "keep-route", "label": "Keep the route and watch"}],
                         [sf.agent, lg.agent], {sf.agent: ask, lg.agent: str(reply.get("reply", ""))},
                         card_id=f"factory-{VEHICLE.lower()}-{run}", at=NOW)
        rec["card"] = card["id"]
    link.clear(lg.agent, ROUTE)
    link.clear(sf.agent, ROUTE)
    rec["coordination_calls"] = link.counts
    rec["spend"] = ledger.summary()
    (out / "decision.json").write_text(json.dumps(rec, indent=1, default=str))
    print(json.dumps({k: rec.get(k) for k in ("collided_with", "logistics", "safety_answer_to_counter", "agreed", "made_stale",
                                               "floor_stale", "floor", "card")}, indent=1, default=str))
    print(out)


if __name__ == "__main__":
    main()
