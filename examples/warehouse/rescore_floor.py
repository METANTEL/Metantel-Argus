# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Score a finished floor hive run again from what it saved (its reviews) and what it wrote to the memory (its lessons),
without asking any model again.

    python examples/warehouse/rescore_floor.py runs/hive-floor/<run> [--split 150]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from argus.hive.link import Link
from argus.memory import Edip
from argus.perception import floor as F
from argus.sites.warehouse import team as H

from run_hive_floor import episodes_over


def score(run_dir: Path, split: float = 150.0) -> dict:
    reviews = json.loads((run_dir / "reviews.json").read_text())
    run_id = run_dir.name
    cams = sorted({c for r in reviews for c in r["seen_by"]} | {r["camera"] for r in reviews})
    cams = H.CAMS if set(cams) <= set(H.CAMS) else sorted(F.cameras())
    by_t = H.raw(cams)
    times = sorted(by_t)
    gold = H.truth(cams)
    in_b = lambda xs: [x for x in xs if x["start_s"] >= split]  # noqa: E731
    gold_b = in_b(gold)
    merged_a = {t: H.merge_with_cams(by_t[t])[0] for t in times if t < split}
    parked_a = F.parked(merged_a)
    facts = [f for f in Link(Edip()).facts(subject=f"run:{run_id}", limit=300) if H.KNOWLEDGE not in f["subjects"]]
    places_a = H.lessons_from([f for f in facts if f["since"] < H.stamp(split)])
    keep = lambda r: r["verdict"].get("verdict") != "reject"  # noqa: E731
    return {
        "run": run_id, "cameras": len(cams), "truth": {"all": len(gold), "second_half": len(gold_b)},
        "second_half": {
            "watchers alone (parked rule from the first half)": H.score(in_b(episodes_over(by_t, times, None, parked_a)), gold_b),
            "watchers with the first half's lessons, no review": H.score(in_b(episodes_over(by_t, times, places_a, [])), gold_b),
            "hive (lessons, corroboration, review)": H.score([r for r in reviews if r["phase"] == "B" and keep(r)], gold_b),
            "everything the hive's watchers flagged": H.score([r for r in reviews if r["phase"] == "B"], gold_b)},
        "first_half": {"flagged": H.score([r for r in reviews if r["phase"] == "A"], [g for g in gold if g["start_s"] < split]),
                       "hive": H.score([r for r in reviews if r["phase"] == "A" and keep(r)], [g for g in gold if g["start_s"] < split])},
        "flags": len(reviews), "model_reviews": sum(not r["verdict"].get("corroborated") for r in reviews),
        "rejected": sum(r["verdict"].get("verdict") == "reject" for r in reviews), "lessons": len(facts)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--split", type=float, default=150.0)
    a = ap.parse_args()
    s = score(a.run, a.split)
    (a.run / "rescore.json").write_text(json.dumps(s, indent=1))
    print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
