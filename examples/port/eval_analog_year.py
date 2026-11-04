# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The analog forecast over the whole year, with no model: two hours into each slowdown, the median outcome of the
five most similar earlier slowdowns (only those whose outcome was known by then) against the median of all of them.
The same rule as `Episodes.similar`, computed locally from the compiled year.

    python examples/port/eval_analog_year.py
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta

from argus.config import DATA, RUNS, load_cache
from argus.sites.port import pack as S


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    d = load_cache(DATA / "ais" / "compiled-2024.pkl")
    rows = S.slowdown_rows(d["status"], d["slowdowns"])
    feats = S.EPISODE_FEATURES
    out = []
    for r in rows:
        now = (datetime.strptime(r["start"], "%Y-%m-%d %H:%M") + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        past = [x for x in rows if x["known_at"] <= now and x["end"] and x["end"] <= now]
        if len(past) < 5:
            continue
        fs = [f for f in feats if num(r[f]) is not None]
        span = {f: (max(num(x[f]) or 0 for x in past) - min(num(x[f]) or 0 for x in past)) or 1 for f in fs}
        near = sorted(past, key=lambda x: sum(abs((num(x[f]) or 0) - num(r[f])) / span[f] for f in fs) / max(len(fs), 1))[:5]
        rec = {"start": r["start"], "cause": r["cause"], "prior": len(past)}
        for o in ("hours", "recovery_hours"):
            truth = num(r[o])
            a = [num(x[o]) for x in near if num(x[o]) is not None]
            m = [num(x[o]) for x in past if num(x[o]) is not None]
            rec[o] = {"truth": truth, "analog": statistics.median(a) if a else None, "median_all": statistics.median(m) if m else None}
        out.append(rec)

    def mae(sel, o, k):
        v = [abs(x[o][k] - x[o]["truth"]) for x in sel if x[o]["truth"] is not None and x[o][k] is not None]
        return (round(statistics.fmean(v), 2), len(v)) if v else (None, 0)
    fog = [x for x in out if "fog" in x["cause"] or "haze" in x["cause"]]
    summary = {"slowdowns": len(rows), "scored": len(out),
               "duration_mae": {"all": {"analog": mae(out, "hours", "analog"), "median_all": mae(out, "hours", "median_all")},
                                "fog": {"analog": mae(fog, "hours", "analog"), "median_all": mae(fog, "hours", "median_all")}},
               "recovery_mae": {"all": {"analog": mae(out, "recovery_hours", "analog"), "median_all": mae(out, "recovery_hours", "median_all")},
                                "fog": {"analog": mae(fog, "recovery_hours", "analog"), "median_all": mae(fog, "recovery_hours", "median_all")}}}
    (RUNS / "analog-year.json").write_text(json.dumps({"summary": summary, "rows": out}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
