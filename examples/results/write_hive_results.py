# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Collect the hive's runs into CSV files and one summary, for the results folder.

    python examples/results/write_hive_results.py OUT_DIR --port-runs 202611031442,202611031500[,<nonfog>] \
        --floor-runs <id>,<id> --plant-run <id> --year <runs/qa/year-*.json> --review-runs <id>,<id>
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from argus.config import RUNS
from argus.perception import floor as F
from argus.sites.warehouse import team as HF


def write(path: Path, rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--port-runs", default="")
    ap.add_argument("--floor-runs", default="")
    ap.add_argument("--plant-run", default="")
    ap.add_argument("--year", default="")
    ap.add_argument("--review-runs", default="")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    summary: dict = {}

    rows = []
    for run in filter(None, a.port_runs.split(",")):
        d = RUNS / "hive-port" / run
        summary[f"port_{run}"] = json.loads((d / "summary.json").read_text())
        for f in sorted(d.glob("2024-*.json")):
            r = json.loads(f.read_text())
            for st in r["steps"]:
                ch, an, al = st["channel"]["plan"], (st.get("anchorage") or {}).get("plan") or {}, (st.get("alone") or {}).get("plan") or {}
                rows.append({"run": run, "event": r["start"], "cause": r["cause"], "at": st["at"], "truth_hours": r["truth"]["hours"],
                             "truth_recovery_hours": r["truth"]["recovery_hours"], "channel_state": ch.get("state"),
                             "channel_expected_end": ch.get("expected_end"), "channel_duration_hours": ch.get("duration_hours"),
                             "channel_published": st["channel"].get("published", ""), "anchorage_replanned": bool(st.get("anchorage")),
                             "hive_assumed_reopen": an.get("assumed_reopen"), "hive_recovery_hours": an.get("recovery_hours"),
                             "alone_assumed_reopen": al.get("assumed_reopen"), "alone_recovery_hours": al.get("recovery_hours"),
                             "hive_gap_h": st["coherence"]["hive_gap_h"], "alone_gap_h": st["coherence"]["alone_gap_h"],
                             "ask": (st.get("ask") or {}).get("ask", ""), "channel_answer": ((st.get("ask") or {}).get("answer") or {}).get("answer", ""),
                             "card": st.get("card", ""), "weather": json.dumps(st.get("weather")) if st.get("weather") else ""})
    summary["port_checkpoints"] = write(a.out / "port_hive_checkpoints.csv", rows)

    gold = {}
    rows = []
    for run in filter(None, a.floor_runs.split(",")):
        d = RUNS / "hive-floor" / run
        # A run whose own summary was lost is scored again from its reviews (rescore_floor.py).
        s = json.loads((d / ("summary.json" if (d / "summary.json").exists() else "rescore.json")).read_text())
        summary[f"floor_{run}"] = {k: v for k, v in s.items() if k != "lessons"}
        cams = s.get("cameras")
        cams = tuple(cams) if isinstance(cams, list) else tuple(HF.CAMS if cams in (None, 4) else sorted(F.cameras()))
        if cams not in gold:
            gold[cams] = HF.truth(list(cams))
        for r in json.loads((d / "reviews.json").read_text()):
            real = any(r["start_s"] - 2 <= g["end_s"] and g["start_s"] - 2 <= r["end_s"]
                       and math.dist(r["person_xy"], g["person_xy"]) <= 2.5 for g in gold[cams])
            v = r["verdict"]
            rows.append({"run": run, "phase": r["phase"], "start_s": r["start_s"], "end_s": r["end_s"], "camera": r["camera"],
                         "seen_by": " ".join(r["seen_by"]), "min_distance_m": r["min_distance_m"], "real_close_call": real,
                         "verdict": v.get("verdict"), "corroborated": bool(v.get("corroborated")), "blue_is": v.get("blue_is", ""),
                         "red_is_person": v.get("red_is_person", ""), "reason": v.get("reason", ""), "lessons": " | ".join(r["lessons"])})
    summary["floor_reviews"] = write(a.out / "floor_hive_reviews.csv", rows)

    if a.plant_run:
        d = RUNS / "hive-plant" / a.plant_run
        summary["plant"] = json.loads((d / "summary.json").read_text())
        rows = [{"fired_at": r["fired_at"], "action": r["plan"].get("action"), "window_start": r["plan"].get("window_start"),
                 "window_hours": r["plan"].get("window_hours"), "risk": r["plan"].get("risk"), "collided_with": " ".join(r.get("collided_with") or []),
                 "operations": (r.get("operations") or {}).get("answer", ""), "agreed_window": r.get("agreed_window", ""),
                 "card": r.get("card", ""), "leak_within_72h": r["before_failure"],
                 "next_failure": (r.get("next_failure") or {}).get("id", ""), "inspection_before_leak": r["inspection_before_failure"]}
                for r in json.loads((d / "firings.json").read_text())]
        write(a.out / "plant_hive_firings.csv", rows)

    if a.year:
        y = json.loads(Path(a.year).read_text())
        summary["year"] = {k: v for k, v in y.items() if k != "rows"}
        write(a.out / "year_questions.csv", [{"id": r["id"], "question": r["question"], "gold": r["gold"],
                                              **{f"{arm}_final": r.get(f"{arm}_final") for arm in ("argus", "reports", "context")},
                                              **{f"{arm}_correct": r.get(arm) for arm in ("argus", "reports", "context")}} for r in y["rows"]])

    for name in ("taf-2mi.json", "analog-year.json"):
        p = RUNS / name
        if p.exists():
            j = json.loads(p.read_text())
            summary[name] = j.get("summary") or {k: v for k, v in j.items() if k != "rows"}
            write(a.out / name.replace(".json", ".csv"), [{k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in r.items()} for r in j["rows"]])

    rows = []
    for run in filter(None, a.review_runs.split(",")):
        for r in json.loads((RUNS / "hive-review" / run / "reviews.json").read_text()):
            for g in r["review"].get("goals") or []:
                rows.append({"month": r["month"], "kind": "goal", "what": g.get("goal"), "met": g.get("met"), "evidence": g.get("evidence")})
            for p in r["review"].get("priorities") or []:
                rows.append({"month": r["month"], "kind": "priority", "what": p.get("priority"), "section": p.get("section"), "evidence": p.get("why")})
    summary["director_reviews"] = write(a.out / "director_reviews.csv", sorted(rows, key=lambda r: r["month"]))

    (a.out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(sorted(p.name for p in a.out.iterdir()))


if __name__ == "__main__":
    main()
