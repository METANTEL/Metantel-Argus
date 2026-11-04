# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The factory as a hive: floor operations, safety, logistics and a plant director over four halls whose sources
differ (cameras, tags, a mix), sharing one charter and one memory, with a what-if the harness computes on the tracks.
"""
from __future__ import annotations

import json
from typing import Any

from ...agent import Agent
from ...config import DATA, load_cache
from ...hive.link import Link
from ...hive.manager import Manager, facts_for
from ...hive.mind import Charter, Goal
from . import feed as FX

SITE = ("a factory site of four halls (A to D) where people work beside forklifts, autonomous transporters, mobile "
        "robots and humanoid robots")

CHARTER = Charter(
    site=SITE,
    purpose="Keep everyone safe, keep goods and machines moving, and use people, space and equipment well, shift after "
            "shift.",
    goals=[Goal("Nobody comes within 1.5 m of a moving vehicle or robot", "close calls per hour, by hall and zone"),
           Goal("No zone is so crowded that work slows", "people per zone at the peak"),
           Goal("Every vehicle and robot earns its place on the floor", "share of the shift each one is moving"),
           Goal("Every number says how far its sources can be trusted", "each hall's coverage, stated with the number")],
    sections={"factory/floor": "people, space and flow in every hall",
              "factory/safety": "close calls between people and vehicles or robots, and where they happen",
              "factory/logistics": "forklifts, transporters, mobile robots and humanoid robots",
              "factory/director": "the site's priorities, the next shift's plan, what goes to people"},
    authority={"floor operations manager": "re-routes walkways and staffing within a hall",
               "safety manager": "can stop a vehicle route at once; a permanent layout change goes to people",
               "logistics manager": "re-routes and reschedules vehicles and robots; buying or retiring one goes to people",
               "plant director": "sets priorities and the shift plan; brings people in for layout, staffing and spend",
               "people": "the plant manager decides layout changes, staffing levels and capital spend"})

KNOWN = ("TABLES you can query exactly: factory/occupancy.csv (people, humanoids and vehicles per hall and 5 m zone, every "
         "10 s), factory/vehicles.csv (every vehicle and robot every 5 s: zone, moving or idle, speed, position, source), "
         "factory/close_calls.csv (a person within 1.5 m of a moving vehicle or robot), factory/minutes.csv (each hall "
         "minute by minute), factory/sources.csv (what each hall's sources can see, and how many of the people present they "
         "track). Notes per hall: factory/notes/hall-a.md to hall-d.md. The shift so far runs 08:00 to 08:05 on "
         f"{FX.CLOCK[:10]}; zones are 5 m squares named by a letter and a number.")

WHATIF = {"type": "function", "function": {
    "name": "whatif", "description": "Replay one vehicle or robot against the people as they actually moved: its close calls "
    "if it ran its route earlier or later (shift_seconds), and how many of its close calls happened inside given zones "
    "(avoid_zones; keeping it out of them could avoid at most that many). People are assumed to move as recorded.",
    "parameters": {"type": "object", "properties": {
        "hall": {"type": "string"}, "vehicle": {"type": "string", "description": "a vehicle id from factory/vehicles.csv"},
        "avoid_zones": {"type": "array", "items": {"type": "string"}}},
        "required": ["hall", "vehicle"]}}}


def compiled() -> dict:
    return load_cache(DATA / "factory-compiled.pkl")


def whatif_fn(data: dict):
    def run(args: dict, now: str) -> Any:
        hall = str(args.get("hall") or "").strip().upper()[:1]
        if hall not in data:
            return {"error": f"hall is one of {', '.join(data)}"}
        trs = data[hall]["tracks"]
        vid = str(args.get("vehicle") or "").strip()
        ids = {tr.id.lower(): tr.id for tr in trs}   # an agent may drop the hall prefix, or the case: "vehicle-c15"
        vid = ids.get(vid.lower()) or ids.get(f"{hall}-{vid}".lower()) or vid
        if not any(tr.id == vid for tr in trs):
            cands = sorted(tr.id for tr in trs if tr.kind in FX.VEHICLES + ("vehicle", "humanoid"))
            return {"error": f"no vehicle {vid!r} in hall {hall}", "vehicles": cands[:20]}
        out: dict[str, Any] = {"vehicle": vid, "by_shift": FX.whatif_shift(trs, vid)}
        if args.get("avoid_zones"):
            out["avoid"] = FX.whatif_avoid(trs, vid, {str(z).upper() for z in args["avoid_zones"]})
        return out
    return run


def route_ask(route: str, action: str, wf: dict, zones: list[str] | None = None) -> str:
    """Safety's request to logistics, with the what-if's numbers as the evidence."""
    av, shifts = wf["avoid"], {r["shift_s"]: r["close_calls"] for r in wf["by_shift"]}
    return (f"[{route}] Safety asks: {action}. Evidence from the what-if, with people as they actually moved: "
            f"{av['inside_zones']} of {wf['vehicle']}'s {av['close_calls']} close calls in the last five minutes were inside "
            f"{', '.join(zones or av['zones'])}; running its route {', '.join(f'{s:+d} s → {n}' for s, n in shifts.items() if s)} "
            f"(as run: {shifts[0]}).")


def negotiate(link: Link, sf, lg, fl, vehicle: str, zones: list[str], action: str, wf: dict, now: str, run: str) -> dict:
    """Safety's change to a vehicle's route, through the hive: its intent collides with logistics' use of the route, the
    two negotiate over the what-if's numbers, and what they agree is written to memory, making every other copy of the
    route stale; floor operations re-reads and says what changes for people. What they cannot settle goes to people."""
    route = f"route:{vehicle}"
    rec: dict = {"vehicle": vehicle, "zones": zones, "action": action, "whatif": wf}
    route_v1 = f"{vehicle} runs its goods route through {', '.join(zones)} this shift"
    lg.hold(route, "v1", route_v1)
    fl.hold(route, "v1", route_v1)
    link.intend(lg.agent, route, "use", f"{vehicle} carries goods through {', '.join(zones)} this shift")
    av = wf.get("avoid") or {}
    why = f"{av.get('inside_zones')} of its {av.get('close_calls')} close calls happened inside {', '.join(zones)}"
    rec["collided_with"] = [h["agent"] for h in link.intend(sf.agent, route, "change", f"{action}: {why}")]
    ask = route_ask(route, action, wf, zones)
    rec["ask"] = ask
    link.send(sf.agent, lg.agent, ask, importance="high")
    link.inbox(lg.agent)
    reply = lg.ask_json(f"{ask}\nIt is {now}. Your copy of the route: {route_v1}. Answer within your authority (the charter): "
                        "accept the change, counter with a change you can make instead (re-route or re-time the vehicle), or "
                        "decline. Reply with JSON only: {\"answer\": \"accept|counter|decline\", \"change\": \"what will "
                        "happen to the route, in one line\", \"reply\": \"one or two sentences to the safety manager\"}",
                        max_tokens=2500)
    link.send(lg.agent, sf.agent, f"[{route}] {reply.get('answer', '?')}: {reply.get('reply', '')}")
    link.inbox(sf.agent)
    rec["logistics"] = reply
    agreed = (reply.get("change") or action) if reply.get("answer") == "accept" else None
    if reply.get("answer") == "counter":
        back = sf.ask_json(f"[{route}] Logistics counters: {reply.get('reply', '')} (change: {reply.get('change', '')}). Your "
                           f"request was: {action}. The what-if: {json.dumps(wf)}. Can you accept it within the site's goals, "
                           "or must people decide? Reply with JSON only: {\"accept\": true|false, \"why\": \"one sentence\"}",
                           max_tokens=2000)
        rec["safety_answer_to_counter"] = back
        link.send(sf.agent, lg.agent, f"[{route}] {'accepted' if back.get('accept') is True else 'not accepted'}: {back.get('why', '')}")
        agreed = reply.get("change") if back.get("accept") is True else None
    if agreed:
        got = sf.change(route, "v2", f"agreed with logistics: {agreed}")
        rec["agreed"] = agreed
        rec["made_stale"] = [s["agent"] for s in got.get("stale", [])]
        link.add_facts(sf.agent, [{"text": f"{vehicle}'s route, agreed by safety and logistics at {now}: {agreed}",
                                   "kind": "decision", "subjects": [sf.agent, lg.agent, route, f"run:{run}"], "since": now}])
        sf.done(route)
        rec["floor_stale"] = fl.stale([route])
        if rec["floor_stale"]:
            seen = link.facts(subject=route)
            rec["floor"] = fl.ask_json(f"Your copy of {route} went stale. The memory now says: "
                                       f"{json.dumps([f.get('text') for f in seen][-3:])}. It is {now}. What, if anything, "
                                       "changes for people's walkways and staffing in the hall? Reply with JSON only: "
                                       "{\"change\": \"one line\", \"why\": \"one sentence\"}", max_tokens=2000)
            fl.hold(route, "v2", agreed)
    else:
        card = link.card(sf.agent, route, f"{vehicle}: safety and logistics disagree on its route",
                         f"Safety: {ask}\nLogistics: {reply.get('reply', '')}",
                         [{"id": "as-safety-asks", "label": f"Keep it out of {' and '.join(zones)}"},
                          {"id": "as-logistics-says", "label": "As logistics proposes"},
                          {"id": "keep-route", "label": "Keep the route and watch"}],
                         [sf.agent, lg.agent], {sf.agent: ask, lg.agent: str(reply.get("reply", ""))},
                         card_id=f"factory-{vehicle.lower()}-{run}", at=now)
        rec["card"] = card["id"]
    link.clear(lg.agent, route)
    link.clear(sf.agent, route)
    return rec


def make(link: Link, edip, models, run: str, provider: str = "meta", models_by_role: dict[str, str] | None = None) -> dict[str, Manager]:
    data = compiled()
    spec = {"director": ("factory/director", "plant director", "factory/director",
                         "Run a safe, productive site across all four halls, and bring people in only where they must decide"),
            "floor": ("factory/floor", "floor operations manager", "factory/floor",
                      "Keep people's work flowing: no crowded zones, short walks, the right people in the right hall"),
            "safety": ("factory/safety", "safety manager", "factory/safety",
                       "Remove close calls between people and vehicles or robots, starting with the ones that repeat"),
            "logistics": ("factory/logistics", "logistics manager", "factory/logistics",
                          "Every vehicle and robot moving goods when it is needed, and none crossing people's paths")}
    out = {}
    for k, (agent, role, section, goal) in spec.items():
        m = Manager(link, CHARTER, agent, role, section, goal, models=models, provider=provider,
                    model=(models_by_role or {}).get(k))
        m.brain = Agent(SITE, edip, models, None, provider=provider, model=(models_by_role or {}).get(k), max_calls=9,
                        facts=facts_for(link, run), extra={"whatif": (WHATIF, whatif_fn(data))})
        out[k] = m
    return out
