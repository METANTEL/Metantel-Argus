# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""A hall's camera supervisor at work on the shift's own footage. It holds SAM 3.1's output on every camera and the
memory built from it to the four invariants (argus/hive/supervise.py), looks for itself where a check fires, chooses a
remedy, applies it, and tells the hive what it learned. Its log (issues, the frames it looked at, its findings, the
remedies and what they changed) is what the console shows.

    python examples/factory/supervise_factory.py [--hall A] [--judge 4]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time

from argus.config import RUNS
from argus.hive import supervise as S
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.perception import tiles as P
from argus.sites.factory import feed as FX
from argus.sites.factory import supervise as CS
from argus.sites.factory import team as H

NOW = f"{FX.CLOCK[:10]} 08:05"
#: What the people who run the hall told the hive at setup.
KNOWLEDGE = {
    "A": ["People walk Hall A's floor beside forklifts and two machines that drive themselves: an autonomous transporter "
          "(a low, flat cart) and a small white mobile robot.",
          "The footage is a simulation: some people are drawn semi-transparent; each one is a person on the floor.",
          "SAM 3.1, the perception model, returns at most 16 objects a frame for one phrase."],
}


def per_frame(boxes: list[dict]) -> float:
    per: dict[int, int] = {}
    for b in boxes:
        per[b["frame"]] = per.get(b["frame"], 0) + 1
    return statistics.median(per.values()) if per else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hall", default="A")
    ap.add_argument("--judge", type=int, default=4, help="cameras the supervisor looks at itself; the rest get its lesson")
    ap.add_argument("--look", default="", help="the cameras it looks at itself, instead of the most saturated")
    a = ap.parse_args()
    hall = a.hall
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "supervise" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    sup = CS.CameraSupervisor(link, H.CHARTER, f"factory/perception-{hall.lower()}", "camera supervisor", "factory/perception",
                             f"Everyone and every machine in Hall {hall}'s view followed, and nothing in memory the cameras did "
                             "not really see", models=models, provider="baseten", watches=f"SAM 3.1 on Hall {hall}'s cameras",
                             out_dir=out, hall=hall)
    sup.announce()
    knowledge = KNOWLEDGE.get(hall, [])
    for k in knowledge:
        sup.tell(k, "state", [f"hall:{hall}", "site-knowledge"], NOW)

    def split(issue: S.Issue) -> dict:
        cam = issue.subject
        before = FX.detect(None, hall, cam, dense=False).get("person", [])
        try:
            d = P.dense(models, hall, cam, "person")
        except Exception as e:                       # the model is unreachable: the remedy waits, the issue stays open
            return {"pending": str(e)[:160], "people_per_frame_before": per_frame(before)}
        return {"tiles": len(d["tiles"]), "people_per_frame_before": per_frame(before),
                "people_per_frame_after": per_frame(d["boxes"])}

    def rederive(issue: S.Issue) -> dict:
        mx, my = issue.evidence["median_xy"]
        trs = FX.vehicle_tracks(hall)
        near = min(trs, key=lambda tr: math.dist((FX._median(tr.x), FX._median(tr.y)), (mx, my)))
        return {"tracks": len(trs), "parked": [tr.id for tr in trs if tr.parked],
                "moving": [tr.id for tr in trs if not tr.parked], "this_vehicle_now": near.id, "this_vehicle_parked": near.parked}

    sup.remedies = {"split": split, "rederive": rederive, "accept": lambda i: {}, "correct": rederive}

    # people: is everyone in each camera's view followed?
    issues = []
    for cam in FX.cameras(hall):
        det = FX.detect(None, hall, cam, dense=False).get("person", [])
        issue = sup.people_check(cam, det)
        if issue:
            issues.append((issue.evidence["units_at_limit"] / issue.evidence["units"], issue, det))
    issues.sort(key=lambda x: -x[0])
    if a.look:
        first = a.look.split(",")
        issues.sort(key=lambda x: (x[1].subject not in first, -x[0]))
    lesson_remedy = None
    for n, (_, issue, det) in enumerate(issues):
        if n < a.judge:
            v = sup.count(issue, det, 60.0, "before", knowledge)
            remedy = str(v.get("remedy") or "accept")
            if remedy == "split":
                lesson_remedy = "split"
        else:
            remedy = lesson_remedy or "accept"
            issue.verdict = {"finding": "the same limit the supervisor looked at on the other cameras", "remedy": remedy,
                             "by": "the hall's lesson"}
        res = sup.apply(issue, remedy)
        if n < a.judge and remedy == "split" and not res.get("pending"):   # it looks again at the same frame, new boxes
            after = S.Issue("disagrees", issue.subject, {"after_remedy": "split"})
            dense = P.dense(models, hall, issue.subject, "person")["boxes"]
            res["count_after"] = sup.count(after, dense, 60.0, "after", knowledge)
            res["count_after_images"] = after.images
        print(issue.subject, issue.check, "->", remedy, json.dumps(res)[:200], flush=True)
    if lesson_remedy:
        sup.tell(f"Hall {hall}'s cameras each see far more people than SAM 3.1 returns (it stops at 16 a frame): their watchers "
                 "look in tiles at full resolution, and closer wherever a tile comes back full.", "lesson",
                 [f"hall:{hall}", "perception"], NOW)

    # vehicles: is what memory calls a moving vehicle moving?
    old = H.compiled()[hall]
    tb = old["tables"]
    for tr in [t for t in old["tracks"] if t.kind == "vehicle"]:
        rows = [r for r in tb["vehicles"] if r["vehicle"] == tr.id]
        share = sum(r["state"] == "moving" for r in rows) / max(1, len(rows))
        calls = sum(1 for r in tb["close_calls"] if r["vehicle"] == tr.id)
        issue = sup.vehicle_check(tr, share, calls)
        if not issue:
            continue
        v = sup.look_at_vehicle(issue, tr, knowledge)
        remedy = str(v.get("remedy") or "accept")
        res = sup.apply(issue, remedy)
        print(issue.subject, issue.check, "->", remedy, (v.get("finding") or "")[:160], json.dumps(res)[:200], flush=True)
        if remedy in ("rederive", "correct") and res.get("this_vehicle_parked"):
            sup.tell(f"Correction from the camera supervisor: {v.get('finding', '')} Memory had {tr.id} moving {share:.0%} of "
                     f"the shift with {calls} close calls; re-derived from every camera at once it is {res['this_vehicle_now']}, "
                     f"parked. Hall {hall}'s machines now: {len(res['moving'])} moving, {len(res['parked'])} parked.",
                     "event", [f"hall:{hall}", tr.id, "correction", "memory:factory/hall-" + hall.lower()], NOW)
            if v.get("lesson"):
                sup.tell(str(v["lesson"]), "lesson", [f"hall:{hall}", "perception"], NOW)

    # what the site knows exists: is every machine that drives itself followed?
    trs = FX.vehicle_tracks(hall)
    movers = [tr for tr in trs if not tr.parked and sum(FX.moving(tr, i) >= 0.2 for i in range(len(tr.t))) >= 60]
    expected = 2 if hall == "A" else 0
    if expected:
        gap = S.missing({f"mover {i + 1}" for i in range(expected)}, {f"mover {i + 1}" for i in range(min(expected, len(movers)))},
                        f"hall:{hall}", movers=[tr.id for tr in movers], knowledge="two machines drive themselves")
        print("missing check:", "issue" if gap else "every machine the site named is followed", [tr.id for tr in movers])
        if gap:
            sup.log.append(gap)
    sup.save()
    print(json.dumps(ledger.summary(), indent=1))
    print(out)


if __name__ == "__main__":
    main()
