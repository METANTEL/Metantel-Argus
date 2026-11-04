# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Site pack: the plant's compressor (APU-1), replayed from MetroPT-3.

What goes into the memory (no raw 10-second signals):
- `plant/apu_5min.csv` and `plant/apu_daily.csv`: the compiled health measures.
- `plant/apu_episodes.csv`: every abnormal episode, appended once its outcome is known (72 hours after it began, or when
  a failure began within those 72 hours). This is the memory the analog forecast reads.
- `plant/apu/daily/<date>.md`: a daily health note, with figures only.
- `plant/work-orders/<id>.md`: the operator's failure reports, at the time each repair was done.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from ...config import RUNS
from . import feed as E

SITE = "the plant's compressed-air system (unit APU-1, a metro train air production unit)"
PREFIX = "plant"
EPISODE_FEATURES = ["peak_duty_pct", "low_pressure_min", "min_tp3_bar", "hours"]
EPISODE_OUTCOMES = ["failure_within_72h", "hours_to_failure"]


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def severe(a: E.Anomaly) -> bool:
    return a.low_pressure_min >= 10 or (a.peak_duty_pct >= 85 and a.min_tp3_bar < 6)


def episodes(an: list[E.Anomaly]) -> list[dict]:
    fails = [(datetime.strptime(f["start"], "%Y-%m-%d %H:%M"), datetime.strptime(f["repaired"], "%Y-%m-%d %H:%M"), f["id"])
             for f in E.FAILURES]
    out = []
    for a in an:
        s, e = datetime.strptime(a.start, "%Y-%m-%d %H:%M"), datetime.strptime(a.end, "%Y-%m-%d %H:%M")
        during = next((fid for fs, fr, fid in fails if fs <= s <= fr), None)
        nxt = next(((fs, fid) for fs, fr, fid in fails if fs > s), None)
        within = nxt is not None and (nxt[0] - s) <= timedelta(hours=72)
        known = min(s + timedelta(hours=72), nxt[0]) if within else s + timedelta(hours=72)
        known = max(known, e)
        out.append({"start": a.start, "end": a.end, "hours": a.hours, "severity": "severe" if severe(a) else "minor",
                    "peak_duty_pct": a.peak_duty_pct, "baseline_duty_pct": a.baseline_duty_pct,
                    "peak_cycles_per_hour": a.peak_cycles_per_hour, "baseline_cycles_per_hour": a.baseline_cycles_per_hour,
                    "low_pressure_min": a.low_pressure_min, "min_tp3_bar": a.min_tp3_bar,
                    "signals": "; ".join(a.reasons), "during_failure": during or "",
                    "failure_within_72h": 1 if within else 0, "failure_id": nxt[1] if within else "",
                    "hours_to_failure": round((nxt[0] - s).total_seconds() / 3600, 1) if within else "",
                    "known_at": fmt(known)})
    return out


def daily_note(d: dict) -> str:
    lines = [f"# APU-1 daily health — {d['date']}", "",
             f"Recorded {d['hours_recorded']} h. Compressor loading {d['duty_pct']}% of the time"
             + (f" (7-day median {d['duty_pct_7d_median']}%)" if d['duty_pct_7d_median'] != "" else "") + ".",
             f"Load cycles: {d['load_cycles']} ({d['cycles_per_hour']} an hour"
             + (f"; 7-day median {d['cycles_per_hour_7d_median']}" if d['cycles_per_hour_7d_median'] != "" else "") + ").",
             f"Lowest pressure after the separator (TP3): {d['tp3_min_bar']} bar; lowest reservoir pressure: {d['reservoir_min_bar']} bar.",
             f"Low-pressure switch on for {d['low_pressure_min']} min. Highest oil temperature {d['oil_temp_max_c']} °C. "
             f"Mean motor current {d['motor_current_a']} A."]
    return "\n".join(lines) + "\n"


def work_order(f: dict) -> str:
    return (f"# Work order {f['id']} — {f['kind']} on APU-1\n\n"
            f"Failure reported: {f['kind'].lower()}, severity {f['severity'].lower()}.\n"
            f"Fault period: {f['start']} to {f['end']}.\n"
            f"Repair completed: {f['repaired']}.\n"
            f"Unit returned to service after the repair.\n")


def build(fm: list[dict] | None = None) -> dict:
    fm = fm or E.five_min(E.con())
    daily = E.daily(fm)
    an = E.anomalies(fm)
    eps = episodes(an)
    return {"five_min": fm, "daily": daily, "anomalies": an, "episodes": eps}


def episode_text(ep: dict) -> str:
    return (f"Compressor episode on APU-1 from {ep['start']} to {ep['end']} ({ep['hours']} h): compressor loading up to "
            f"{ep['peak_duty_pct']}% of the hour against {ep['baseline_duty_pct']}% normally; up to "
            f"{ep['peak_cycles_per_hour']} load cycles an hour against {ep['baseline_cycles_per_hour']}; low-pressure switch "
            f"on {ep['low_pressure_min']} min; lowest TP3 pressure {ep['min_tp3_bar']} bar. Signals: {ep['signals']}.")


def firings(runs: Path = RUNS) -> list[dict]:
    """The watcher's warnings in the latest replay (`examples/plant/run_equipment.py`), one row each, as strings: the rows
    that `examples/results/write_results.py` writes to equipment_warnings.csv (fired_at, episode_start, headline, ...)."""
    for d in sorted((runs / "equipment").glob("*/"), reverse=True):
        if (d / "warnings.json").exists() and (d / "summary.json").exists():
            out = []
            for w in json.loads((d / "warnings.json").read_text()):
                a = w.get("answer") or {}
                row = {"fired_at": w["at"], "episode_start": w["episode_start"], "failure_within_72h": w["truth_failure_within_72h"],
                       "failure": w["truth_failure_id"], "level": a.get("level", ""), "headline": a.get("headline", "")}
                out.append({k: "" if v is None else str(v) for k, v in row.items()})
            return out
    return []
