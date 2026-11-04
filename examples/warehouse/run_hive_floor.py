# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The plant floor as a hive, against the same cameras watched in isolation.

Five minutes of four cameras, split in two: the first 150 s are a shift the hive learns from, the last 150 s are scored.
Every arm uses the same SAM 3.1 detections (cached from the floor run); what differs is what the watchers know.

- isolated: the perceptors flag every person within 1.5 m of a vehicle that is not at a place where a vehicle stood
  for most of the first half (the isolated pipeline's own parked-vehicle rule, learned from the first half only);
- memory: the perceptors also skip the places the hive's lessons name (written in the first half), with no review;
- hive: memory, and every flagged close call reviewed by the floor-safety manager (Muse Spark Open on Baseten, two
  frames, plus what the memory says about the place) as it happens, with new lessons shared at once.

    python examples/warehouse/run_hive_floor.py [--split 150] [--limit-reviews N]
"""
from __future__ import annotations

import argparse
import json
import time

from argus.config import RUNS
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.perception import floor as F
from argus.sites.warehouse import team as H


def episodes_over(by_t: dict, times: list[float], places: dict | None, still: list) -> list[dict]:
    eps = H.Episodes()
    for t in times:
        spots = [s for s in by_t.get(t, []) if places is None or H.keep(s, places)]
        merged, cams = H.merge_with_cams(spots)
        eps.step(t, merged, still, cams)
    eps.flush()
    return [e.view() for e in eps.closed]


def plain(v):
    """JSON-safe: a key that is not a string (a tuple, from a place or a pair) is written as text."""
    if isinstance(v, dict):
        return {k if isinstance(k, (str, int, float, bool)) or k is None else str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", type=float, default=150.0)
    ap.add_argument("--limit-reviews", type=int, default=0, help="stop reviewing after N close calls (a smoke test)")
    ap.add_argument("--provider", default="baseten")
    ap.add_argument("--model", default=None)
    ap.add_argument("--no-setup", action="store_true", help="the reviewer works without the people's setup notes")
    ap.add_argument("--policy", default="corroborate", choices=["corroborate", "review-all"],
                    help="corroborate: a close call seen by two cameras or for a second stands, and only weaker ones are "
                         "reviewed; review-all: the manager reviews every one")
    ap.add_argument("--cams", default="4", choices=["4", "all"])
    a = ap.parse_args()
    run_id = time.strftime("%Y%m%d%H%M") + ("-" + (a.model or a.provider).split("/")[-1][:20] if a.model or a.provider != "baseten" else "")
    out = RUNS / "hive-floor" / run_id
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    cal = F.cameras()

    cams = H.CAMS if a.cams == "4" else sorted(cal)
    perceptors = {c: H.Perceptor(link, H.CHARTER, H.cam_id(c), "perceptor", H.SECTION,
                                 f"Report every person within 2 m of a moving vehicle or robot that {c.replace('_', ' ')} sees, "
                                 "and nothing the floor's memory says is not one", models=models)
                  for c in cams}
    safety = H.Safety(link, H.CHARTER, "plant/floor/safety", "floor-safety manager", H.SECTION,
                      "Confirm real close calls within a minute, reject false ones, and teach every watcher what misleads it",
                      models=models, provider=a.provider, model=a.model)
    for m in [*perceptors.values(), safety]:
        m.announce()
    for p in perceptors.values():
        p.refresh(run_id)
    knowledge: list[dict] = []
    if not a.no_setup:
        # People teach the floor at setup: standing site knowledge every agent reads (subject site-knowledge, this run).
        link.presence("plant/floor/site-lead", "person (site lead)", H.SECTION, "Tell the hive what this floor looks like")
        link.add_facts("plant/floor/site-lead", [{"text": t, "kind": "procedure", "subjects": [H.KNOWLEDGE, H.SECTION, f"run:{run_id}"],
                                                  "since": H.stamp(0), "source": "people/site-lead"} for t in H.SETUP])
        knowledge = [f for f in link.facts(subject=f"run:{run_id}", limit=50) if H.KNOWLEDGE in f["subjects"]]
    LESSONS = H.lessons_res(run_id)

    by_t = H.raw(cams)
    times = sorted(by_t)
    eps = H.Episodes()
    reviews, invalidations, version = [], [], 0
    t_last_poll = -99.0

    def review(e: H.Episode, t: float) -> None:
        nonlocal version
        p = perceptors[e.person.camera]
        if a.policy == "corroborate" and (len(e.seen_by) >= 2 or e.end_s - e.start_s >= 1.0):
            # Corroborated by a second camera or by time: it stands, and the manager is told rather than asked.
            link.send(p.agent, safety.agent, f"Close call at {H.stamp(e.at_s)}: person at x={e.person.x:.1f} y={e.person.y:.1f}, "
                      f"vehicle at x={e.vehicle.x:.1f} y={e.vehicle.y:.1f}, {e.distance:.1f} m apart; seen by "
                      f"{', '.join(sorted(e.seen_by))} for {e.end_s - e.start_s + 0.5:.1f} s.", importance="high")
            reviews.append({**e.view(), "phase": "A" if e.start_s < a.split else "B", "reviewed_at_s": t,
                            "verdict": {"verdict": "confirm", "reason": "corroborated", "corroborated": True},
                            "lessons": [], "seconds": 0, "usd": 0})
            return
        link.send(p.agent, safety.agent, f"Possible close call at {H.stamp(e.at_s)}: person at x={e.person.x:.1f} y={e.person.y:.1f}, "
                  f"vehicle at x={e.vehicle.x:.1f} y={e.vehicle.y:.1f}, {e.distance:.1f} m apart; seen by {', '.join(sorted(e.seen_by))}.",
                  importance="high")
        link.inbox(safety.agent)
        facts = link.facts(subject=f"run:{run_id}", limit=300)
        t0, usd0 = time.time(), ledger.usd
        try:
            v = safety.verify(e, p.places, out / "frames", cal, [f for f in facts if H.KNOWLEDGE not in f["subjects"]], knowledge)
        except Exception as ex:  # noqa: BLE001 - a failed review is reported, never silently dropped
            v = {"verdict": "confirm", "reason": f"review failed: {str(ex)[:120]}", "failed": True}
        lessons = safety.learn(e, v, run_id, H.stamp(t))
        if lessons:
            version += 1
            got = safety.change(LESSONS, str(version), f"new floor lesson: {lessons[0]['text'][:120]}")
            invalidations.append({"t": t, "made_stale": [s["agent"] for s in got.get("stale", [])]})
            safety.done(LESSONS)
        reviews.append({**e.view(), "phase": "A" if e.start_s < a.split else "B", "reviewed_at_s": t, "verdict": v,
                        "lessons": [l["text"] for l in lessons], "seconds": round(time.time() - t0, 1),
                        "usd": round(ledger.usd - usd0, 5)})
        print(f"{t:6.1f}s {v.get('verdict', '?'):8s} {e.person.camera} d={e.distance:.1f} {str(v.get('reason'))[:90]}"
              + (f"  LESSON: {lessons[0]['text'][:80]}" if lessons else ""), flush=True)

    for t in times:
        if t - t_last_poll >= 10 or invalidations and invalidations[-1]["t"] == t:
            t_last_poll = t
            if any(s["kind"] == "lease" and s["subject"] == LESSONS for s in link.signals()):
                for p in perceptors.values():
                    if p.stale([LESSONS]):
                        p.refresh(run_id)
        spots = [s for s in by_t[t] if H.keep(s, perceptors[s.camera].places)]
        merged, cams = H.merge_with_cams(spots)
        for e in eps.step(t, merged, [], cams):
            if not a.limit_reviews or len(reviews) < a.limit_reviews:
                review(e, t)
    for e in eps.flush():
        if not a.limit_reviews or len(reviews) < a.limit_reviews:
            review(e, times[-1])

    # ── scoring ──
    gold = H.truth(cams)
    in_b = lambda xs: [x for x in xs if x["start_s"] >= a.split]  # noqa: E731
    gold_b = in_b(gold)
    times_a = [t for t in times if t < a.split]
    merged_a = {t: H.merge_with_cams(by_t[t])[0] for t in times_a}
    parked_a = F.parked(merged_a)
    iso_b = in_b(episodes_over(by_t, times, None, parked_a))
    iso_all = episodes_over(by_t, times, None, parked_a)
    facts = [f for f in link.facts(subject=f"run:{run_id}", limit=300) if H.KNOWLEDGE not in f["subjects"]]
    places_a = H.lessons_from([f for f in facts if f["since"] < H.stamp(a.split)])
    mem_b = in_b(episodes_over(by_t, times, places_a, []))
    mem_parked_b = in_b(episodes_over(by_t, times, places_a, parked_a))
    hive_b = [r for r in reviews if r["phase"] == "B" and r["verdict"].get("verdict") != "reject"]
    hive_a = [r for r in reviews if r["phase"] == "A" and r["verdict"].get("verdict") != "reject"]
    flagged_a = [r for r in reviews if r["phase"] == "A"]
    old = F.only_moving({t: F.merge(by_t[t]).get(t, []) for t in times}, F.parked({t: F.merge(by_t[t]).get(t, []) for t in times}))
    old_b = in_b(F.near_misses(old, still=F.parked({t: F.merge(by_t[t]).get(t, []) for t in times})))
    summary = {
        "run": run_id, "split_s": a.split, "truth": {"all": len(gold), "second_half": len(gold_b)},
        "second_half": {
            "isolated (parked rule from the first half)": H.score(iso_b, gold_b),
            "isolated, earlier pipeline (motion filter; parked rule from the whole clip)": H.score(old_b, gold_b),
            "memory (lessons from the first half, no review)": H.score(mem_b, gold_b),
            "memory + parked rule": H.score(mem_parked_b, gold_b),
            "hive (memory + review as it happens)": H.score(hive_b, gold_b)},
        "first_half": {"flagged": H.score(flagged_a, [g for g in gold if g["start_s"] < a.split]),
                       "after review": H.score(hive_a, [g for g in gold if g["start_s"] < a.split])},
        "policy": a.policy, "cameras": cams,
        "isolated_whole_clip": H.score(iso_all, gold),
        "reviews": len(reviews), "model_reviews": sum(not r["verdict"].get("corroborated") for r in reviews),
        "rejected": sum(r["verdict"].get("verdict") == "reject" for r in reviews),
        "review_failures": sum(bool(r["verdict"].get("failed")) for r in reviews),
        "lessons": [f["text"] for f in facts], "invalidations": invalidations,
        "coordination_calls": link.counts, "spend": ledger.summary(),
        "review_seconds_median": sorted(r["seconds"] for r in reviews)[len(reviews) // 2] if reviews else None}
    (out / "reviews.json").write_text(json.dumps(reviews, indent=1, default=str))
    (out / "summary.json").write_text(json.dumps(plain(summary), indent=1, default=str))
    print(json.dumps({k: v for k, v in summary.items() if k != "lessons"}, indent=1, default=str))
    for m in [*perceptors.values(), safety]:
        m.link.leave(m.agent)


if __name__ == "__main__":
    main()
