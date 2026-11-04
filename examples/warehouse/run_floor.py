# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The plant floor's morning shift: four warehouse cameras through SAM 3.1, into the memory as events, counts, a few
described keyframes and a shift summary. Scores the near-miss detector against the scene's 3D ground truth.

The clip is NVIDIA PhysicalAI-SmartSpaces Warehouse_015 (5 minutes). It is replayed as the plant's floor from
2020-09-01 08:00 UTC, after the compressor history ends; it is a different public dataset, so nothing links the two.

    python examples/warehouse/run_floor.py
"""
from __future__ import annotations

import json
import math
import statistics
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from argus.config import DATA, RUNS
from argus.memory import Edip
from argus.models import Models, ledger
from argus.perception import floor as F

CAMS = ["Camera_01", "Camera_10", "Camera_12", "Camera_03"]
T0 = datetime(2020, 9, 1, 8, 0, 0)
TAGS = ["site=plant", "area=floor"]
DESCRIBE = ("This is a frame from a warehouse safety camera. A person is close to a moving autonomous transport vehicle "
            "near the centre of the marked box. In two or three plain sentences, say what the person and the vehicle are "
            "doing, whether the person is in or beside the vehicle's path, and anything that raises or lowers the risk "
            "(visibility, the person's attention, obstacles). Say only what the image shows.")


def zone(x: float, y: float) -> str:
    ns = "north" if y >= 5 else "south" if y < -3 else "middle"
    ew = "west" if x < -3 else "east" if x >= 3 else "centre"
    return f"{ns}-{ew}"


def ts(sec: float) -> str:
    return (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    run = RUNS / "floor" / time.strftime("%Y%m%d-%H%M")
    run.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    cal = F.cameras()
    spots = []
    for c in CAMS:
        spots += F.spots(c, F.detect(models, c), cal[c])
    by_t = F.merge(spots)
    still = F.parked(by_t)
    found = F.near_misses(F.only_moving(by_t, still), still=still)
    gold, counts = F.truth(CAMS)
    sc = F.score(found, gold)

    # Counts every 10 seconds: people on the floor, vehicles on the move, people within 3 m of a moving vehicle.
    rows = []
    for t0 in range(0, 300, 10):
        win = [ss for t, ss in by_t.items() if t0 <= t < t0 + 10]
        ppl = [sum(s.kind == "person" for s in ss) for ss in win]
        mov = [[s for s in ss if s.kind == "vehicle" and not any(math.dist((s.x, s.y), q) < 1.5 for q in still)] for ss in win]
        close = [sum(any(math.dist((p.x, p.y), (v.x, v.y)) < 3 for v in mv) for p in ss if p.kind == "person") for ss, mv in zip(win, mov)]
        rows.append([ts(t0), "floor", round(statistics.fmean(ppl), 1) if ppl else 0, max((len(m) for m in mov), default=0),
                     max(close, default=0)])
    edip.ingest("plant/floor_counts.csv", "time,area,people_on_floor,vehicles_moving,people_within_3m_of_vehicle\n"
                + "\n".join(",".join(map(str, r)) for r in rows) + "\n", kind="table", tags=TAGS)
    ev = [[ts(e["start_s"]), "near_miss", e["camera"], e["min_distance_m"], e["seconds"], e["person_xy"][0], e["person_xy"][1],
           e["forklift_xy"][0], e["forklift_xy"][1], zone(*e["person_xy"])] for e in found]
    edip.ingest("plant/floor_events.csv", "time,event,camera,min_distance_m,seconds,person_x,person_y,vehicle_x,vehicle_y,zone\n"
                + "\n".join(",".join(map(str, r)) for r in ev) + "\n", kind="table", tags=TAGS)

    # The closest calls get a keyframe, described by Muse Spark; three keyframes go in as images too.
    closest = sorted(found, key=lambda e: e["min_distance_m"])[:6]
    notes = []
    for i, e in enumerate(closest):
        img = F.keyframe(e["camera"], e["at_s"], DATA / "smartspaces" / "keyframes" / f"nm_{int(e['at_s'] * 10):05d}_{e['camera']}.jpg")
        desc = models.text(DESCRIBE, images=[img], effort="minimal", max_tokens=3000)
        name = f"plant/floor/near-miss/{ts(e['start_s'])[11:].replace(':', '')}.md"
        text = (f"# Near-miss on the plant floor at {ts(e['at_s'])} UTC\n\n"
                f"A person came within {e['min_distance_m']} m of a moving autonomous transport vehicle in the {zone(*e['person_xy'])} "
                f"zone (floor position x={e['person_xy'][0]} m, y={e['person_xy'][1]} m), seen by {e['camera']}. The close approach "
                f"lasted {e['seconds']} s, from {ts(e['start_s'])[11:]} to {ts(e['end_s'])[11:]}.\n\n"
                f"## What the camera shows (described by a vision model)\n\n{desc}\n")
        edip.ingest(name, text, kind="incident", tags=TAGS + ["code=NEARMISS"])
        if i < 3:
            try:
                edip.upload_file(img, f"plant/floor/keyframes/{img.name}", "image/jpeg")
            except Exception as ex:  # noqa: BLE001 - the description already carries the content
                print("image upload failed:", ex)
        notes.append({"name": name, "description": desc})

    zones = Counter(zone(*e["person_xy"]) for e in found)
    summary_doc = (f"# Plant floor — morning shift summary, {T0:%Y-%m-%d} 08:00–08:05 UTC\n\n"
                   f"Cameras watched: {', '.join(CAMS)}. People on the floor: about {round(statistics.fmean(r[2] for r in rows))} at any time.\n"
                   f"Near-misses between a person and a moving autonomous vehicle (within {F.NEAR_M} m): {len(found)}.\n"
                   f"Where: " + ", ".join(f"{z} {n}" for z, n in zones.most_common()) + ".\n"
                   f"Closest approach: {closest[0]['min_distance_m']} m at {ts(closest[0]['at_s'])[11:]} ({zone(*closest[0]['person_xy'])}).\n"
                   f"Parked vehicles (forklifts standing all shift) at floor positions: "
                   + "; ".join(f"x={x:.1f}, y={y:.1f}" for x, y in still) + ".\n\n"
                   f"How far to trust these counts: checked against this scene's 3D ground truth, the camera detector "
                   f"found {int(round((sc['recall'] or 0) * 100))}% of the real close approaches, and "
                   f"{int(round((sc['precision'] or 0) * 100))}% of what it flagged were real ones. Treat the zone ranking as a "
                   f"lead to check on camera, not a count.\n")
    edip.ingest(f"plant/floor/shift/{T0:%Y-%m-%d}-morning.md", summary_doc, kind="report", tags=TAGS + ["code=SHIFT"])
    out = {"detector_vs_truth": sc, "truth_counts": counts, "found": len(found), "parked": still, "zones": zones,
           "notes": notes, "spend": ledger.summary()}
    (run / "summary.json").write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
