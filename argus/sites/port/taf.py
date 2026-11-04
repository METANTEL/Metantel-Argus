# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The National Weather Service's airport forecasts (TAF) for Galveston (KGLS), from the Iowa Environmental Mesonet
archive: what a port dispatcher reads to know when fog will lift.

    curl -o data/weather/taf_KGLS_2024.csv \
      "https://mesonet.agron.iastate.edu/cgi-bin/request/taf.py?station=KGLS&sts=2023-12-31T00:00Z&ets=2025-01-02T00:00Z&fmt=csv"
"""
from __future__ import annotations

import bisect
import csv
from datetime import datetime, timedelta

from ...config import DATA

FMT = "%Y-%m-%d %H:%M"


def load(path=None) -> list[dict]:
    by: dict[str, dict] = {}
    with (path or DATA / "weather" / "taf_KGLS_2024.csv").open() as f:
        for r in csv.DictReader(f):
            p = by.setdefault(r["product_id"], {"issued": r["valid"], "groups": []})
            try:
                vis = float(r["visibility"])
            except ValueError:
                vis = None
            p["groups"].append({"start": r["fx_valid"], "tempo": r["is_tempo"] == "True", "vis": vis, "raw": r["raw"]})
    return sorted(by.values(), key=lambda p: p["issued"])


def latest(products: list[dict], now: str) -> dict | None:
    i = bisect.bisect_right([p["issued"] for p in products], now) - 1
    return products[i] if i >= 0 else None


def lift(p: dict, now: str, miles: float = 2.0) -> tuple[str, str, str]:
    """(when prevailing visibility is forecast above `miles`, the group saying so, the group in force now)."""
    prev = sorted((g for g in p["groups"] if not g["tempo"] and g["vis"] is not None), key=lambda g: g["start"])
    cur = None
    for g in prev:
        if g["start"] <= now:
            cur = g
    if cur and cur["vis"] > miles:
        return now, cur["raw"], cur["raw"]
    for g in prev:
        if g["start"] > now and g["vis"] > miles:
            return g["start"], g["raw"], cur["raw"] if cur else ""
    last = prev[-1]["start"] if prev else now
    return (datetime.strptime(last, FMT) + timedelta(hours=6)).strftime(FMT), "(no lift in this forecast)", cur["raw"] if cur else ""
