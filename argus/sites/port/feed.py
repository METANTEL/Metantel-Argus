# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The Houston Ship Channel and Galveston Bay: AIS positions and airport visibility, turned into what a port operator
reasons with.

Raw AIS is 0.5M+ position reports a day for this box. None of that goes to the memory. This module compiles it, with
no model, into:

- `traffic_hourly.csv`: one row per hour. Deep-draft ships moving in the bay channel and the upper ship channel,
  transits through Bolivar Roads, the queue waiting outside, ships at anchor, tugs at work, visibility at Galveston
  (GLS) and Baytown (HPY).
- `vessel_events.csv`: one row per thing a deep-draft ship did (arrived in the area, anchored, entered the bay, berthed,
  went silent, …), keyed by MMSI, so tables can answer latest / trace / durations / gaps.
- `vessels.csv`: one row per ship seen.
- `visibility.csv`: hourly visibility per station.
- `slowdowns`: periods when deep-draft traffic in the channels fell far under its recent normal, with the queue
  they built, how long it took to recover, and the visibility at the time.

Zones are rough boxes drawn from the chart, good enough to tell "in the bay" from "waiting outside"; they are not
navigational boundaries.
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

from ...config import DATA

AIS = DATA / "ais" / "houston"
WEATHER = DATA / "weather"

# (name, lat_min, lat_max, lon_min, lon_max). First match wins.
ZONES = [
    ("Galveston harbor", 29.29, 29.335, -94.86, -94.765),
    ("Bolivar Roads", 29.30, 29.40, -94.80, -94.66),
    ("Texas City", 29.33, 29.42, -94.96, -94.86),
    ("Offshore anchorage", 28.95, 29.30, -94.80, -94.40),
    ("Lower bay channel", 29.40, 29.64, -95.06, -94.66),
    ("Upper ship channel", 29.64, 29.85, -95.35, -94.94),
]
DEEP = "vessel_type BETWEEN 70 AND 89"          # cargo and tanker
TUG = "vessel_type IN (31, 32, 52)"
ENTRANCE_LAT = 29.34                            # north of this is the bay


def zone_sql() -> str:
    parts = [f"WHEN lat BETWEEN {a} AND {b} AND lon BETWEEN {c} AND {d} THEN '{n}'" for n, a, b, c, d in ZONES]
    return "CASE " + " ".join(parts) + " ELSE 'Gulf approach' END"


def con(days: list[str] | None = None, path: Path | None = None) -> duckdb.DuckDBPyConnection:
    """Positions with their zone. In memory by default; with `path`, in a database file that is built once and reused
    (a year of positions, about 200M rows, does not fit in memory)."""
    c = duckdb.connect(str(path) if path else ":memory:")
    if path and c.sql("SELECT count(*) FROM information_schema.tables WHERE table_name = 'p'").fetchall()[0][0]:
        return c
    files = sorted(AIS.glob("ais-*.parquet"))
    if days is not None:
        files = [f for f in files if f.stem[4:] in days]
    if not files:
        raise FileNotFoundError(f"no Houston AIS days in {AIS}")
    flist = ", ".join(f"'{f}'" for f in files)
    c.sql(f"""CREATE TABLE p AS
        SELECT mmsi, ts, lat, lon, sog, cog, heading, vessel_name, imo, vessel_type, status, length, draft,
               {zone_sql()} AS zone, lat > {ENTRANCE_LAT} AS inside
        FROM read_parquet([{flist}])""")
    return c


def type_group(t: int | None) -> str:
    if t is None:
        return "unknown"
    if 80 <= t <= 89:
        return "tanker"
    if 70 <= t <= 79:
        return "cargo"
    if t in (31, 32, 52):
        return "tug"
    if 60 <= t <= 69:
        return "passenger"
    return "other"


def visibility() -> dict[tuple[str, str], float]:
    """{(station, 'YYYY-MM-DD HH'): visibility in miles}, the lowest report in each hour."""
    out: dict[tuple[str, str], float] = {}
    for f in sorted(WEATHER.glob("asos_*.csv")):
        for r in csv.DictReader(f.open()):
            try:
                v = float(r["visibility_mi"])
            except ValueError:
                continue
            k = (r["station"], r["time_utc"][:13])
            out[k] = min(v, out.get(k, v))
    return out


def status(c: duckdb.DuckDBPyConnection) -> list[dict]:
    """One row per hour: deep-draft traffic by zone, transits through Bolivar Roads, the queue outside, tugs, visibility."""
    rows = c.sql(f"""
        WITH s AS (SELECT *, lag(inside) OVER (PARTITION BY mmsi ORDER BY ts) AS was_in FROM p),
        h AS (SELECT time_bucket(INTERVAL 1 HOUR, ts) AS t, * FROM s)
        SELECT t,
          count(DISTINCT mmsi) FILTER (WHERE {DEEP} AND zone = 'Lower bay channel' AND sog > 5) AS moving_bay_channel,
          count(DISTINCT mmsi) FILTER (WHERE {DEEP} AND zone = 'Upper ship channel' AND sog > 3) AS moving_upper_channel,
          count(*) FILTER (WHERE {DEEP} AND inside AND NOT was_in) AS inbound_transits,
          count(*) FILTER (WHERE {DEEP} AND was_in AND NOT inside) AS outbound_transits,
          count(DISTINCT mmsi) FILTER (WHERE {DEEP} AND zone = 'Offshore anchorage' AND sog < 0.5) AS waiting_outside,
          count(DISTINCT mmsi) FILTER (WHERE {DEEP} AND status = 1) AS at_anchor,
          count(DISTINCT mmsi) FILTER (WHERE {TUG} AND sog > 2) AS tugs_working
        FROM h GROUP BY t ORDER BY t""").fetchall()
    vis = visibility()
    out = []
    for t, bay, up, inb, outb, wait, anch, tugs in rows:
        hr = t.strftime("%Y-%m-%d %H")
        out.append({"time": t.strftime("%Y-%m-%d %H:%M"), "moving_bay_channel": bay, "moving_upper_channel": up,
                    "moving_total": bay + up, "inbound_transits": inb, "outbound_transits": outb,
                    "waiting_outside": wait, "at_anchor": anch, "tugs_working": tugs,
                    "vis_galveston_mi": vis.get(("GLS", hr), ""), "vis_baytown_mi": vis.get(("HPY", hr), "")})
    return out


def vessels(c: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = c.sql(f"""SELECT mmsi, any_value(vessel_name), any_value(imo), any_value(vessel_type), max(length), max(draft),
                            min(ts), max(ts)
                     FROM p WHERE {DEEP} OR {TUG} GROUP BY mmsi ORDER BY mmsi""").fetchall()
    return [{"mmsi": m, "name": (n or "").strip(), "imo": i or "", "type": type_group(t), "length_m": l or "", "draft_m": d or "",
             "first_seen": a.strftime("%Y-%m-%d %H:%M"), "last_seen": b.strftime("%Y-%m-%d %H:%M")}
            for m, n, i, t, l, d, a, b in rows]


def events(c: duckdb.DuckDBPyConnection, silence_min: int = 60) -> list[dict]:
    """What each deep-draft ship did, from its own track: transitions between zones and between moving and stopped."""
    rows = c.sql(f"""
        SELECT mmsi, ts, lat, lon, sog, status, zone, inside, any_value(vessel_name) OVER (PARTITION BY mmsi) AS name,
               any_value(vessel_type) OVER (PARTITION BY mmsi) AS vt
        FROM p WHERE {DEEP} ORDER BY mmsi, ts""").fetchall()
    out: list[dict] = []

    def ev(ts: datetime, mmsi: int, name: str, vt: int, kind: str, zone: str, lat: float, lon: float, sog: float, note: str = "") -> None:
        out.append({"time": ts.strftime("%Y-%m-%d %H:%M"), "mmsi": mmsi, "vessel": (name or "").strip(), "type": type_group(vt),
                    "event": kind, "zone": zone, "lat": round(lat, 4), "lon": round(lon, 4), "sog": round(sog or 0, 1), "note": note})

    prev = None
    stop_since: datetime | None = None
    for r in rows:
        mmsi, ts, lat, lon, sog, st, zone, inside, name, vt = r
        if prev is None or prev[0] != mmsi:
            ev(ts, mmsi, name, vt, "seen", zone, lat, lon, sog)
            prev, stop_since = r, (ts if (sog or 0) < 0.5 else None)
            continue
        _, pts, plat, plon, psog, pst, pzone, pinside, *_ = prev
        gap = (ts - pts).total_seconds() / 60
        if gap >= silence_min:
            ev(pts, mmsi, name, vt, "went_silent", pzone, plat, plon, psog, f"no reports for {gap:.0f} min")
            ev(ts, mmsi, name, vt, "reappeared", zone, lat, lon, sog, f"after {gap:.0f} min")
        if inside and not pinside:
            ev(ts, mmsi, name, vt, "entered_bay", zone, lat, lon, sog)
        elif pinside and not inside:
            ev(ts, mmsi, name, vt, "left_bay", zone, lat, lon, sog)
        elif zone != pzone:
            ev(ts, mmsi, name, vt, "entered_zone", zone, lat, lon, sog, f"from {pzone}")
        if st == 1 and pst != 1:
            ev(ts, mmsi, name, vt, "anchored", zone, lat, lon, sog)
        elif pst == 1 and st != 1:
            ev(ts, mmsi, name, vt, "weighed_anchor", zone, lat, lon, sog)
        moving, was_moving = (sog or 0) >= 0.5, (psog or 0) >= 0.5
        if not moving and was_moving:
            stop_since = ts
        elif moving and not was_moving and stop_since is not None:
            dur = (ts - stop_since).total_seconds() / 3600
            if dur >= 1:
                ev(ts, mmsi, name, vt, "got_underway", zone, lat, lon, sog, f"after {dur:.1f} h stopped")
            stop_since = None
        prev = r
    out.sort(key=lambda e: (e["time"], e["mmsi"]))
    return out


@dataclass
class Slowdown:
    start: str
    end: str | None                       # first hour traffic was back to normal; None if still slow at the data's end
    hours: float
    min_traffic_ratio: float              # the slowest hour's traffic against its baseline
    baseline_moving: float                # median deep-draft ships moving per hour over the previous 72 hours
    queue_start: int
    queue_peak: int
    peak_at: str
    recovery_hours: float | None          # from the end of the slowdown until the queue was back to its starting size
    min_visibility_mi: float | None
    cause: str
    transits_lost: float                  # baseline transits minus actual transits over the slowdown


def slowdowns(st: list[dict], ratio: float = 0.4, min_hours: int = 2, baseline_hours: int = 72) -> list[Slowdown]:
    """Hours when deep-draft traffic in the channels fell under `ratio` of its recent normal, merged into episodes.

    The baseline is the median of the previous `baseline_hours` hours that exist, so each hour is judged only on what
    came before it, the way a live watcher would judge it."""
    t = [datetime.strptime(r["time"], "%Y-%m-%d %H:%M") for r in st]
    base, slow = [], []
    for i, r in enumerate(st):
        prior = [st[k]["moving_total"] for k in range(max(0, i - baseline_hours * 2), i)
                 if t[i] - t[k] <= timedelta(hours=baseline_hours)]
        b = statistics.median(prior) if len(prior) >= 24 else None
        base.append(b)
        slow.append(b is not None and b >= 3 and r["moving_total"] <= ratio * b)
    out: list[Slowdown] = []
    i, n = 0, len(st)
    while i < n:
        if not slow[i]:
            i += 1
            continue
        j = i + 1
        while j < n and (slow[j] or (j + 1 < n and slow[j + 1])) and t[j] - t[j - 1] <= timedelta(hours=2):
            j += 1
        hours = (t[j - 1] - t[i]).total_seconds() / 3600 + 1
        if hours >= min_hours:
            b = base[i] or 1
            seg = st[i:j]
            before = [st[k]["waiting_outside"] for k in range(max(0, i - 3), i + 1) if t[i] - t[k] <= timedelta(hours=3)]
            q0 = int(statistics.median(before))
            pk = max(range(i, min(n, j + 24)), key=lambda k: st[k]["waiting_outside"])
            rec = None
            for k in range(j, min(n, j + 72)):
                if t[k] - t[k - 1] > timedelta(hours=2):      # a hole in the data: the recovery can't be measured
                    break
                if st[k]["waiting_outside"] <= q0:
                    rec = round((t[k] - t[j - 1]).total_seconds() / 3600, 1)
                    break
            vis = [float(v) for r in seg for v in (r["vis_galveston_mi"], r["vis_baytown_mi"]) if v != ""]
            low = min(vis) if vis else None
            cause = "dense fog" if low is not None and low <= 0.5 else "fog or haze" if low is not None and low <= 2 \
                else "not weather (visibility normal)" if low is not None else "unknown (no visibility report)"
            tb = statistics.median([st[k]["inbound_transits"] + st[k]["outbound_transits"] for k in range(max(0, i - 72), i)]) if i else 0
            lost = round(tb * hours - sum(r["inbound_transits"] + r["outbound_transits"] for r in seg), 1)
            out.append(Slowdown(start=st[i]["time"], end=st[j]["time"] if j < n else None, hours=round(hours, 1),
                                min_traffic_ratio=round(min(r["moving_total"] for r in seg) / b, 2), baseline_moving=b,
                                queue_start=q0, queue_peak=st[pk]["waiting_outside"], peak_at=st[pk]["time"],
                                recovery_hours=rec, min_visibility_mi=low, cause=cause, transits_lost=max(lost, 0)))
        i = j
    return out


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
