# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Compile the factory's four halls and put them into the memory: tables Argus's agents query exactly, and a note per
hall. Each hall's sources are measured against the scene's recorded positions, so the memory knows how far to trust
every count.

    python examples/factory/ingest_factory.py [--dry]
"""
from __future__ import annotations

import argparse
import json
import pickle

from argus.config import DATA
from argus.memory import Edip
from argus.sites.factory import feed as FX

TAGS = ["site=factory"]
COLS = {
    "occupancy": ["time", "hall", "zone", "people", "humanoids", "vehicles_moving", "vehicles_idle"],
    "vehicles": ["time", "hall", "vehicle", "kind", "zone", "state", "speed_mps", "x_m", "y_m", "source"],
    "close_calls": ["start", "end", "hall", "zone", "vehicle", "vehicle_kind", "min_distance_m", "seconds", "source"],
    "minutes": ["time", "hall", "people_seen", "vehicles_moving", "vehicles_idle", "close_calls", "metres_walked",
                "people_source", "vehicle_source"],
    "sources": ["hall", "people", "vehicles", "coverage", "people_tracked_vs_present"],
}


def accuracy(hall: str, trs: list[FX.Track]) -> str:
    """People the hall's sources track at an instant, against the people the scene says are there."""
    gt = json.loads((FX.scene_dir(hall) / "ground_truth.json").read_text())
    pairs = []
    for t in (30, 90, 150, 210, 270):
        present = sum(1 for o in gt[str(int(t * 30))] if o["object type"] == "Person")
        tracked = sum(1 for tr in trs if tr.kind == "person" and tr.at(t) is not None)
        pairs.append((tracked, present))
    tr_ = sum(p[0] for p in pairs) / len(pairs)
    pr = sum(p[1] for p in pairs) / len(pairs)
    return f"{tr_:.0f} tracked of {pr:.0f} present on average ({tr_ / pr:.0%})"


def note(hall: str, tb: dict, src: dict) -> str:
    m = tb["minutes"]
    calls = tb["close_calls"]
    by_zone: dict[str, int] = {}
    for c in calls:
        by_zone[c["zone"]] = by_zone.get(c["zone"], 0) + 1
    top = sorted(by_zone.items(), key=lambda kv: -kv[1])[:3]
    kinds: dict[str, int] = {}
    for c in calls:
        kinds[c["vehicle_kind"]] = kinds.get(c["vehicle_kind"], 0) + 1
    veh = {}
    for r in tb["vehicles"]:
        v = veh.setdefault(r["vehicle"], {"kind": r["kind"], "moving": 0, "n": 0})
        v["n"] += 1
        v["moving"] += r["state"] == "moving"
    lines = [f"# Hall {hall}: shift notes, {FX.CLOCK[:10]} 08:00–08:05", "",
             f"Sources: people from {src['people']}; vehicles from {src['vehicles']}. Coverage: {src['coverage']}. "
             f"People tracked against people present: {src['people_tracked_vs_present']}.",
             f"People seen each minute: {', '.join(str(x['people_seen']) for x in m)}. Metres walked each minute: "
             f"{', '.join(str(x['metres_walked']) for x in m)}.",
             f"Close calls (a person within 1.5 m of a moving vehicle or robot): {len(calls)} in five minutes"
             + (f", most in zones {', '.join(f'{z} ({n})' for z, n in top)}" if top else "")
             + (f"; by vehicle kind: {', '.join(f'{k} {n}' for k, n in sorted(kinds.items()))}" if kinds else "") + ".",
             "Vehicles: " + ("; ".join(f"{vid.split('-', 1)[1]} ({v['kind']}) moving {v['moving'] * 100 // max(1, v['n'])}% of the time"
                                       for vid, v in sorted(veh.items())) or "none tracked") + "."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    edip = Edip()
    rows: dict[str, list[dict]] = {k: [] for k in COLS}
    notes = {}
    srcs = {s["hall"]: s for s in FX.sources()}
    compiled = {}
    for hall in FX.HALLS:
        trs = FX.tracks(hall)
        tb = FX.tables(hall, trs)
        srcs[hall]["people_tracked_vs_present"] = accuracy(hall, trs)
        for k in ("occupancy", "vehicles", "close_calls", "minutes"):
            rows[k] += tb[k]
        notes[hall] = note(hall, tb, srcs[hall])
        compiled[hall] = {"tracks": trs, "tables": tb}
        print(hall, {k: len(tb[k]) for k in ("occupancy", "vehicles", "close_calls", "minutes")}, "|", srcs[hall]["people_tracked_vs_present"], flush=True)
    rows["sources"] = list(srcs.values())
    (DATA / "factory-compiled.pkl").write_bytes(pickle.dumps(compiled))
    (DATA / "factory-sources.json").write_text(json.dumps(rows["sources"], indent=1))
    for k, rs in rows.items():
        rs.sort(key=lambda r: r.get("time") or r.get("start") or r.get("hall"))
    if a.dry:
        for h, n in notes.items():
            print(n)
        return
    for k, header in COLS.items():
        edip.ingest_table(f"factory/{k}.csv", header, [[r.get(c, "") for c in header] for r in rows[k]], TAGS)
        print(f"factory/{k}.csv: {len(rows[k])} rows", flush=True)
    for hall, text in notes.items():
        edip.ingest(f"factory/notes/hall-{hall.lower()}.md", text, "report", TAGS + ["code=SHIFTNOTE", f"hall={hall}",
                                                                                 f"t={FX.CLOCK[:10]}T08:05"])
    print("notes:", len(notes))


if __name__ == "__main__":
    main()
