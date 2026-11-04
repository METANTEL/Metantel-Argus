# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Equipment health: the air production unit (APU) of a metro train's compressor (MetroPT-3, Porto, Feb–Aug 2020).

The raw feed is 15 signals every 10 seconds, 1.5M rows. This module compiles it, with no model, into:

- `apu_5min.csv`: one row per 5 minutes: pressures, oil temperature, motor current, how much of the time the
  compressor was loading (duty), how many load cycles started, how long the low-pressure switch was on.
- `apu_daily.csv`: one row per day with the same measures and the 7-day baseline they are judged against.
- `anomalies`: hours whose duty cycle or cycle rate stood far above the trailing week, or whose pressure fell, merged
  into episodes. These are what the watcher warns on.
- The operator's own failure reports, as work orders, dated when each repair was done.

Signal meanings (from the dataset's description): COMP is 1 when the compressor is not taking in air (off or
unloaded), so loading time is 1 − COMP; LPS is 1 when pressure falls under about 7 bar.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta

import duckdb

from ...config import DATA

CSV = DATA / "metropt" / "MetroPT3(AirCompressor).csv"

# The operator's failure reports (UCI MetroPT-3 page). The second row's "30 Apr" maintenance date is a typo for 30 May.
FAILURES = [
    {"id": "WO-2020-0418", "start": "2020-04-18 00:00", "end": "2020-04-18 23:59", "kind": "Air leak", "severity": "High stress",
     "repaired": "2020-04-18 23:59"},
    {"id": "WO-2020-0529", "start": "2020-05-29 23:30", "end": "2020-05-30 06:00", "kind": "Air leak", "severity": "High stress",
     "repaired": "2020-05-30 12:00"},
    {"id": "WO-2020-0605", "start": "2020-06-05 10:00", "end": "2020-06-07 14:30", "kind": "Air leak", "severity": "High stress",
     "repaired": "2020-06-08 16:00"},
    {"id": "WO-2020-0715", "start": "2020-07-15 14:30", "end": "2020-07-15 19:00", "kind": "Air leak", "severity": "High stress",
     "repaired": "2020-07-16 00:00"},
]


def con() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.sql(f"CREATE TABLE m AS SELECT * EXCLUDE (column00) FROM read_csv_auto('{CSV}')")
    return c


def five_min(c: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = c.sql("""
        WITH s AS (SELECT *, lag(COMP) OVER (ORDER BY timestamp) AS pcomp FROM m)
        SELECT time_bucket(INTERVAL 5 MINUTE, timestamp) AS t,
               avg(TP2), avg(TP3), min(TP3), min(Reservoirs), avg(Oil_temperature), max(Oil_temperature), avg(Motor_current),
               100 * avg(1 - COMP), count(*) FILTER (WHERE pcomp = 1 AND COMP = 0), 10 * sum(LPS), count(*)
        FROM s GROUP BY t ORDER BY t""").fetchall()
    return [{"time": t.strftime("%Y-%m-%d %H:%M"), "unit": "APU-1", "tp2_bar": round(a, 3), "tp3_bar": round(b, 3),
             "tp3_min_bar": round(cmin, 3), "reservoir_min_bar": round(rmin, 3), "oil_temp_c": round(o, 2),
             "oil_temp_max_c": round(omax, 2), "motor_current_a": round(mc, 3), "duty_pct": round(d, 2), "load_cycles": cyc,
             "low_pressure_s": int(lps), "samples": n}
            for t, a, b, cmin, rmin, o, omax, mc, d, cyc, lps, n in rows]


def daily(fm: list[dict]) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for r in fm:
        by.setdefault(r["time"][:10], []).append(r)
    days = sorted(by)
    out = []
    for i, d in enumerate(days):
        rs = by[d]
        hours = sum(r["samples"] for r in rs) * 10 / 3600
        duty = statistics.fmean(r["duty_pct"] for r in rs)
        cycles = sum(r["load_cycles"] for r in rs)
        row = {"date": d, "unit": "APU-1", "hours_recorded": round(hours, 1), "duty_pct": round(duty, 2),
               "load_cycles": cycles, "cycles_per_hour": round(cycles / hours, 2) if hours else 0,
               "tp3_min_bar": min(r["tp3_min_bar"] for r in rs), "reservoir_min_bar": min(r["reservoir_min_bar"] for r in rs),
               "oil_temp_max_c": max(r["oil_temp_max_c"] for r in rs),
               "motor_current_a": round(statistics.fmean(r["motor_current_a"] for r in rs), 3),
               "low_pressure_min": round(sum(r["low_pressure_s"] for r in rs) / 60, 1)}
        prior = [o for o in out[max(0, i - 7):i] if o["hours_recorded"] >= 6]
        row["duty_pct_7d_median"] = round(statistics.median([o["duty_pct"] for o in prior]), 2) if prior else ""
        row["cycles_per_hour_7d_median"] = round(statistics.median([o["cycles_per_hour"] for o in prior]), 2) if prior else ""
        out.append(row)
    return out


@dataclass
class Anomaly:
    start: str
    end: str
    hours: float
    peak_duty_pct: float
    baseline_duty_pct: float
    peak_cycles_per_hour: float
    baseline_cycles_per_hour: float
    min_tp3_bar: float
    low_pressure_min: float
    reasons: list[str]


def anomalies(fm: list[dict], days_back: int = 7, factor: float = 1.8, min_hours: float = 1.0) -> list[Anomaly]:
    """Hours that stand far above the trailing week, merged into episodes. Judged only on what came before each hour."""
    hours: dict[str, list[dict]] = {}
    for r in fm:
        hours.setdefault(r["time"][:13], []).append(r)
    keys = sorted(hours)
    hstats = []
    for k in keys:
        rs = hours[k]
        hstats.append({"hour": k, "duty": statistics.fmean(r["duty_pct"] for r in rs),
                       "cycles": sum(r["load_cycles"] for r in rs) * 60 / (5 * len(rs)),
                       "tp3_min": min(r["tp3_min_bar"] for r in rs), "lps": sum(r["low_pressure_s"] for r in rs) / 60,
                       "n": len(rs)})
    flagged = []
    window: list[dict] = []
    for h in hstats:
        t = datetime.strptime(h["hour"], "%Y-%m-%d %H")
        window = [w for w in window if t - datetime.strptime(w["hour"], "%Y-%m-%d %H") <= timedelta(days=days_back)]
        if len(window) >= 24 * 2 and h["n"] >= 6:
            bd = statistics.median(w["duty"] for w in window)
            bc = statistics.median(w["cycles"] for w in window)
            why = []
            if h["duty"] > max(bd * factor, bd + 8):
                why.append(f"compressor loading {h['duty']:.0f}% of the hour against {bd:.0f}% normally")
            if h["cycles"] > max(bc * factor, bc + 3):
                why.append(f"{h['cycles']:.1f} load cycles an hour against {bc:.1f} normally")
            if h["lps"] > 0:
                why.append(f"low-pressure switch on {h['lps']:.1f} min")
            if h["tp3_min"] < 7.5:
                why.append(f"pressure fell to {h['tp3_min']:.2f} bar")
            if why:
                flagged.append((t, h, bd, bc, why))
        if h["n"] >= 6:
            window.append(h)
    out: list[Anomaly] = []
    for t, h, bd, bc, why in flagged:
        if out and t - datetime.strptime(out[-1].end, "%Y-%m-%d %H:%M") <= timedelta(hours=2):
            a = out[-1]
            a.end = (t + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            a.hours = round((datetime.strptime(a.end, "%Y-%m-%d %H:%M") - datetime.strptime(a.start, "%Y-%m-%d %H:%M")).total_seconds() / 3600, 1)
            a.peak_duty_pct = round(max(a.peak_duty_pct, h["duty"]), 1)
            a.peak_cycles_per_hour = round(max(a.peak_cycles_per_hour, h["cycles"]), 1)
            a.min_tp3_bar = round(min(a.min_tp3_bar, h["tp3_min"]), 2)
            a.low_pressure_min = round(a.low_pressure_min + h["lps"], 1)
            a.reasons = sorted(set(a.reasons) | {w.split(" ")[0] + " " + w.split(" ")[1] for w in why})
        else:
            out.append(Anomaly(start=t.strftime("%Y-%m-%d %H:%M"), end=(t + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
                               hours=1.0, peak_duty_pct=round(h["duty"], 1), baseline_duty_pct=round(bd, 1),
                               peak_cycles_per_hour=round(h["cycles"], 1), baseline_cycles_per_hour=round(bc, 1),
                               min_tp3_bar=round(h["tp3_min"], 2), low_pressure_min=round(h["lps"], 1),
                               reasons=[w.split(" ")[0] + " " + w.split(" ")[1] for w in why]))
    return [a for a in out if a.hours >= min_hours]
