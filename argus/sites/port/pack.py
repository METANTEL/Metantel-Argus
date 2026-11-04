# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Site pack: the Houston Ship Channel and Galveston Bay, replayed from NOAA AIS and airport visibility (2024).

What goes into the memory (no raw positions):
- `port/traffic_hourly.csv`: hourly deep-draft traffic, transits, the queue outside, tugs, visibility.
- `port/vessel_events.csv`: what each deep-draft ship did (arrived, anchored, entered the bay, went silent, …).
- `port/vessels.csv`: the ships seen, with type, length and draft.
- `port/slowdowns.csv`: every traffic slowdown, appended once it has played out (its recovery is known). This is what the
  analog forecast reads.
- `port/daily/<date>.md`: a daily port report with figures only.
- `port/slowdowns/<start>.md`: a write-up of each slowdown, drafted by Muse Spark Open from the computed figures.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta

from . import feed as P

SITE = "the Port of Houston approaches: the Houston Ship Channel, Galveston Bay and the Bolivar Roads entrance"
EPISODE_FEATURES = ["hours_so_far", "min_traffic_ratio_so_far", "min_visibility_mi_so_far", "queue_start"]
EPISODE_OUTCOMES = ["hours", "recovery_hours", "queue_growth", "transits_lost"]
TAGS = ["site=port"]


def fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def build(days: list[str] | None = None) -> dict:
    c = P.con(days)
    st = P.status(c)
    sl = P.slowdowns(st)
    ev = P.events(c)
    vs = P.vessels(c)
    return {"status": st, "slowdowns": sl, "events": ev, "vessels": vs}


def slowdown_rows(st: list[dict], sl: list[P.Slowdown]) -> list[dict]:
    """One row per slowdown, with what was known two hours in (the features) and how it played out (the outcomes)."""
    t = {r["time"]: r for r in st}
    out = []
    for s in sl:
        s0 = datetime.strptime(s.start, "%Y-%m-%d %H:%M")
        first2 = [t.get(fmt(s0 + timedelta(hours=h))) for h in range(2)]
        first2 = [r for r in first2 if r]
        vis = [float(v) for r in first2 for v in (r["vis_galveston_mi"], r["vis_baytown_mi"]) if v != ""]
        end = datetime.strptime(s.end, "%Y-%m-%d %H:%M") if s.end else s0 + timedelta(hours=s.hours)
        known = end + timedelta(hours=s.recovery_hours if s.recovery_hours is not None else 24)
        out.append({"start": s.start, "end": s.end or "", "hours": s.hours, "cause": s.cause,
                    "hours_so_far": 2, "min_traffic_ratio_so_far": round(min(r["moving_total"] for r in first2) / s.baseline_moving, 2) if first2 else "",
                    "min_visibility_mi_so_far": min(vis) if vis else "", "queue_start": s.queue_start,
                    "baseline_moving_per_hour": s.baseline_moving, "min_traffic_ratio": s.min_traffic_ratio,
                    "queue_peak": s.queue_peak, "queue_growth": s.queue_peak - s.queue_start, "peak_at": s.peak_at,
                    "recovery_hours": s.recovery_hours if s.recovery_hours is not None else "",
                    "min_visibility_mi": s.min_visibility_mi if s.min_visibility_mi is not None else "",
                    "transits_lost": s.transits_lost, "known_at": fmt(known)})
    return out


def daily_reports(st: list[dict], ev: list[dict], sl: list[P.Slowdown]) -> list[tuple[str, str, str]]:
    """(date, name, markdown) per day: the day's figures, its slowdowns, and the ships that waited longest."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in st:
        by_day[r["time"][:10]].append(r)
    ev_day: dict[str, list[dict]] = defaultdict(list)
    for e in ev:
        ev_day[e["time"][:10]].append(e)
    out = []
    for d in sorted(by_day):
        rs = by_day[d]
        vis = [float(v) for r in rs for v in (r["vis_galveston_mi"], r["vis_baytown_mi"]) if v != ""]
        low_hours = sorted({r["time"][11:13] for r in rs for v in (r["vis_galveston_mi"], r["vis_baytown_mi"]) if v != "" and float(v) <= 1})
        inb, outb = sum(r["inbound_transits"] for r in rs), sum(r["outbound_transits"] for r in rs)
        q = [r["waiting_outside"] for r in rs]
        mv = [r["moving_total"] for r in rs]
        day_sl = [s for s in sl if s.start[:10] == d]
        evs = ev_day.get(d, [])
        silent = [e for e in evs if e["event"] == "went_silent" and e["sog"] >= 2
                  and e["zone"] not in ("Gulf approach", "Offshore anchorage")]
        kinds = Counter(e["event"] for e in evs)
        lines = [f"# Port of Houston approaches — daily report {d} (UTC)", "",
                 f"Hours recorded: {len(rs)}. Deep-draft transits through Bolivar Roads: {inb} inbound, {outb} outbound.",
                 f"Deep-draft ships moving in the channels: {round(statistics.fmean(mv), 1)} an hour on average (lowest {min(mv)}, highest {max(mv)}).",
                 f"Ships waiting at the offshore anchorage: between {min(q)} and {max(q)} (at {rs[q.index(max(q))]['time'][11:]} the most).",
                 f"Ships at anchor anywhere in the area at the day's end: {rs[-1]['at_anchor']}. Tugs working at midday: "
                 f"{next((r['tugs_working'] for r in rs if r['time'][11:13] == '12'), rs[len(rs) // 2]['tugs_working'])}.",
                 ("Lowest visibility: " + f"{min(vis)} mi" + (f"; at or under 1 mile in the hours {', '.join(low_hours)} UTC." if low_hours else ".")) if vis else "No visibility reports.",
                 f"Vessel events: {kinds.get('anchored', 0)} anchorings, {kinds.get('entered_bay', 0)} entries into the bay, "
                 f"{kinds.get('left_bay', 0)} departures, {kinds.get('went_silent', 0)} AIS silences of an hour or more."]
        if day_sl:
            lines += ["", "## Traffic slowdowns"]
            for s in day_sl:
                lines.append(f"- From {s.start[11:]} for {s.hours} h: traffic fell to {int(s.min_traffic_ratio * 100)}% of its usual "
                             f"{s.baseline_moving:g} ships an hour; cause {s.cause}; the queue went from {s.queue_start} to {s.queue_peak}.")
        if silent:
            lines += ["", "## AIS silences inside the area"] + [
                f"- {e['vessel'] or 'MMSI ' + str(e['mmsi'])} ({e['type']}, MMSI {e['mmsi']}) in {e['zone']} at {e['time'][11:]}: {e['note']}."
                for e in silent[:8]]
        out.append((d, f"port/daily/{d}.md", "\n".join(lines) + "\n"))
    return out


def slowdown_facts(row: dict) -> str:
    return (f"Traffic slowdown at the Port of Houston approaches from {row['start']} UTC"
            + (f" to {row['end']} UTC" if row['end'] else "") + f" ({row['hours']} h). Deep-draft ships moving in the channels fell "
            f"to {int(float(row['min_traffic_ratio']) * 100)}% of the usual {row['baseline_moving_per_hour']} an hour. Cause: {row['cause']}"
            + (f"; lowest visibility {row['min_visibility_mi']} mi" if row['min_visibility_mi'] != "" else "") + ". "
            f"Ships waiting offshore: {row['queue_start']} at the start, {row['queue_peak']} at the peak ({row['peak_at']} UTC)"
            + (f"; back to {row['queue_start']} {row['recovery_hours']} h after traffic resumed" if row['recovery_hours'] != "" else
               "; the queue had not returned to its starting size within a day") + f". Transits lost against a normal day: about {row['transits_lost']}.")
