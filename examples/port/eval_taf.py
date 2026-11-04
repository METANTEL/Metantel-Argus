# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The forecast a port dispatcher already has: the National Weather Service's airport forecast (TAF) for Galveston
(KGLS), from the Iowa Environmental Mesonet archive. Two hours into each low-visibility slowdown, the latest TAF issued
by then says when prevailing visibility rises above 2 miles; the slowdown's predicted length is that time minus its
start. Scored against what happened, next to the analog forecast, the median of earlier slowdowns and, when a hive run
is given, the channel manager's own first forecast.

    python examples/port/eval_taf.py [--hive runs/hive-port/<id>] [--miles 2]
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from argus.config import RUNS
from argus.sites.port import taf

FMT = "%Y-%m-%d %H:%M"


def tafs() -> list[dict]:
    return taf.load()


def predicted_end(p: dict, now: str, miles: float) -> tuple[str, str]:
    end, group, _ = taf.lift(p, now, miles)
    return end, group


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hive", type=Path, default=None)
    ap.add_argument("--miles", type=float, default=2.0)
    a = ap.parse_args()
    ts = tafs()
    issued = [p["issued"] for p in ts]
    analog = {x["start"]: x for x in json.loads((RUNS / "analog-year.json").read_text())["rows"]}
    hive = {}
    if a.hive:
        for f in a.hive.glob("2024-*.json"):
            r = json.loads(f.read_text())
            p = r["steps"][0]["channel"]["plan"] if r["steps"] else {}
            hive[r["start"]] = p.get("duration_hours")
    rows = []
    for start, x in sorted(analog.items()):
        if "fog" not in x["cause"] and "haze" not in x["cause"]:
            continue
        now = (datetime.strptime(start, FMT) + timedelta(hours=2)).strftime(FMT)
        i = max(j for j, t in enumerate(issued) if t <= now)
        end, why = predicted_end(ts[i], now, a.miles)
        taf_hours = (datetime.strptime(end, FMT) - datetime.strptime(start, FMT)).total_seconds() / 3600
        rows.append({"start": start, "cause": x["cause"], "truth": x["hours"]["truth"], "taf": round(taf_hours, 1),
                     "taf_issued": ts[i]["issued"], "taf_group": why, "analog": x["hours"]["analog"],
                     "median_all": x["hours"]["median_all"], "hive_channel": hive.get(start)})

    def mae(k: str, sel=None) -> tuple:
        v = [abs(float(r[k]) - r["truth"]) for r in (sel or rows) if r.get(k) is not None]
        return (round(statistics.fmean(v), 2), len(v)) if v else (None, 0)
    storms = {"2024-06-19 02:00", "2024-07-08 01:00"}      # Tropical Storm Alberto, Hurricane Beryl: rain, not fog
    fog = [r for r in rows if r["start"] not in storms]
    out = {"miles": a.miles, "events": len(rows),
           "mae_hours_all": {k: mae(k) for k in ("taf", "analog", "median_all", "hive_channel")},
           "mae_hours_without_storms": {k: mae(k, fog) for k in ("taf", "analog", "median_all", "hive_channel")},
           "rows": rows}
    (RUNS / f"taf-{int(a.miles)}mi.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))
    for r in rows:
        print(r["start"], f"truth {r['truth']:>4}", f"taf {r['taf']:>5}", f"analog {r['analog']}", f"median {r['median_all']}",
              f"hive {r['hive_channel']}", "|", r["taf_group"][:60])


if __name__ == "__main__":
    main()
