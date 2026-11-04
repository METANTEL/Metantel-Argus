# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Collect the latest runs into CSV files and one summary, for the results write-up.

    python examples/results/write_results.py <out_dir>
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from pathlib import Path

from argus.config import RUNS


def latest(kind: str, name: str) -> dict | list | None:
    dirs = sorted((RUNS / kind).glob("*/"), reverse=True)
    for d in dirs:
        if (d / name).exists() and (d / "summary.json").exists():
            return json.loads((d / name).read_text())
    return None


def write(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    summary: dict = {}

    eq = latest("equipment", "warnings.json")
    eqs = latest("equipment", "summary.json")
    if eq:
        rows = []
        for w in eq:
            a = w.get("answer") or {}
            rate = ((w.get("analog") or {}).get("outcome_spread") or {}).get("failure_within_72h") or {}
            rows.append({"fired_at": w["at"], "episode_start": w["episode_start"], "failure_within_72h": w["truth_failure_within_72h"],
                         "failure": w["truth_failure_id"], "similar_episodes": rate.get("n"), "share_of_similar_that_failed": rate.get("mean"),
                         "level": a.get("level", ""), "headline": a.get("headline", ""), "usd": w.get("usd"), "seconds": w.get("seconds")})
        write(out / "equipment_warnings.csv", rows)
        act = [r for r in rows if r["level"] == "act_now"]
        summary["equipment"] = {**{k: eqs[k] for k in ("warnings", "lead_hours_by_failure", "failures_warned", "false_warnings",
                                                         "false_warnings_per_month")},
                                "act_now": len(act), "act_now_before_failure": sum(r["failure_within_72h"] for r in act),
                                "spend": eqs["spend"], "edip_calls": eqs["edip_calls"]}

    ps = latest("port", "summary.json")
    pw = latest("port", "slowdown_warnings.json")
    if ps and pw:
        per = ps["per_slowdown"]
        write(out / "port_forecasts.csv", per)
        paired = [r for r in per if all(r.get(k) is not None for k in ("err_analog_hours", "err_baseline_hours"))]
        pr = [r for r in per if all(r.get(k) is not None for k in ("err_analog_recovery", "err_baseline_recovery"))]
        pa = [r for r in per if all(r.get(k) is not None for k in ("err_agent_hours", "err_baseline_hours"))]

        def m(rows: list[dict], k: str) -> float | None:
            return round(statistics.fmean(r[k] for r in rows), 2) if rows else None
        summary["port"] = {"slowdowns": ps["slowdowns"], "warned": ps["warned"], "replay": ps["replay"],
                           "hours_paired_n": len(paired), "hours_mae_analog": m(paired, "err_analog_hours"),
                           "hours_mae_median_of_prior": m(paired, "err_baseline_hours"),
                           "agent_hours_paired_n": len(pa), "hours_mae_agent": m(pa, "err_agent_hours"),
                           "hours_mae_median_of_prior_on_agent_set": m(pa, "err_baseline_hours"),
                           "recovery_paired_n": len(pr), "recovery_mae_analog": m(pr, "err_analog_recovery"),
                           "recovery_mae_median_of_prior": m(pr, "err_baseline_recovery"),
                           "spend": ps["spend"], "edip_calls": ps["edip_calls"]}
        rows = []
        for w in pw:
            a = w.get("answer") or {}
            rows.append({"fired_at": w["at"], "start": w["start"], "truth_hours": w["truth"]["hours"], "truth_recovery": w["truth"]["recovery_hours"],
                         "cause": w["truth"]["cause"], "level": a.get("level", ""), "headline": a.get("headline", ""),
                         "operator": ((w.get("other_audiences") or {}).get("operator") or {}).get("answer", {}).get("headline", ""),
                         "executive": ((w.get("other_audiences") or {}).get("executive") or {}).get("answer", {}).get("headline", "")})
        write(out / "port_warnings.csv", rows)

    fl = sorted((RUNS / "floor").glob("*/summary.json"), reverse=True)
    if fl:
        f = json.loads(fl[0].read_text())
        summary["floor"] = {"detector_vs_truth": f["detector_vs_truth"], "truth_counts": f["truth_counts"], "zones": f["zones"]}
        write(out / "floor_detector.csv", [{**f["detector_vs_truth"], **f["truth_counts"]}])

    for site in ("equipment", "port"):
        qs = sorted((RUNS / "qa").glob(f"{site}-*.json"), reverse=True)
        if qs:
            q = json.loads(qs[0].read_text())
            write(out / f"qa_{site}.csv", [{"id": r["id"], "question": r["question"], "gold": json.dumps(r["gold"]),
                                            **{arm: r.get(arm) for arm in ("argus", "window", "full", "none")}} for r in q["rows"]])
            summary[f"qa_{site}"] = {"n": q["n"], "correct": q["correct"], "window_days": q.get("window_days"),
                                     "window_chars": q.get("window_chars"), "full_chars": q.get("full_chars")}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
