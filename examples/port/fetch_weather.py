# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Hourly airport visibility around Galveston Bay from the Iowa Environmental Mesonet's ASOS archive.

GLS is Galveston (Scholes Field), at the bay's entrance; HPY is Baytown, beside the upper ship channel. NOAA has no
visibility sensor in the channel itself, so these two stations are the fog record.

    python examples/port/fetch_weather.py 2024-01-01 2025-01-01
"""
from __future__ import annotations

import csv
import io
import sys
from datetime import date

import httpx

from argus.config import DATA

URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
STATIONS = ("GLS", "HPY")


def fetch(start: date, end: date) -> list[dict]:
    params = [("station", s) for s in STATIONS] + [
        ("data", "vsby"), ("data", "tmpf"), ("data", "dwpf"), ("data", "sknt"),
        ("year1", start.year), ("month1", start.month), ("day1", start.day),
        ("year2", end.year), ("month2", end.month), ("day2", end.day),
        ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"),
        ("direct", "no"), ("report_type", "3"),
    ]
    r = httpx.get(URL, params=params, timeout=300)
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text)))


def main() -> None:
    start, end = (date.fromisoformat(a) for a in sys.argv[1:3])
    rows = fetch(start, end)
    out = DATA / "weather"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"asos_{start}_{end}.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["station", "time_utc", "visibility_mi", "temp_f", "dewpoint_f", "wind_kt"])
        for r in rows:
            w.writerow([r["station"], r["valid"], r["vsby"], r["tmpf"], r["dwpf"], r["sknt"]])
    print(f"{len(rows)} observations -> {path}")


if __name__ == "__main__":
    main()
