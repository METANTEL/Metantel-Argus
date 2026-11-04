# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Management over the hive: at the end of each month, the director reviews the port against the charter's goals with
Muse Wonder, and sets the next month's priorities as facts in the shared memory, each addressed to one section.

The goals are management's words ("a fog backlog clears within 24 hours of reopening"); the director measures them from
the memory (the slowdowns table, hourly traffic) and from what the hive itself planned that month (a hive run's facts),
says where the port fell short, and writes what each section should do differently. Section managers read priorities
like any other fact.

    python examples/port/run_hive_review.py --hive-run 202611031500 [--months 2024-01,2024-03,2024-07,2024-12]
"""
from __future__ import annotations

import argparse
import json
import time
from calendar import monthrange

from argus.config import RUNS
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.port import team as H

REVIEW_JSON = ('"review": {"goals": [{"goal": "the goal as the charter words it", "met": "yes|partly|no|unknown", '
               '"evidence": "the figures that show it, with their source"}], "priorities": [{"section": "port/channel|'
               'port/anchorage|port/arrivals|port/weather", "priority": "one thing that section should do differently next '
               'month", "why": "the evidence"}]}, at most three priorities')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hive-run", required=True, help="the hive run whose plans the director reads")
    ap.add_argument("--months", default="2024-01,2024-02,2024-03,2024-07,2024-12")
    ap.add_argument("--model", default="muse-wonder-1.0")
    a = ap.parse_args()
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "hive-review" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    hive = H.make(link, edip, models, provider="meta", run=a.hive_run)
    di = hive["director"]
    di.brain.model, di.brain.max_calls = a.model, 8
    di.announce()
    results = []
    for m in a.months.split(","):
        y, mo = int(m[:4]), int(m[5:7])
        now = f"{m}-{monthrange(y, mo)[1]:02d} 23:59"
        nxt = f"{y + (mo == 12):04d}-{mo % 12 + 1:02d}-01 00:00"
        text = (f"It is the end of {m}. Review the port's month against each of the charter's goals: say whether the port met "
                f"it, measured from the tables (port/slowdowns.csv has every slowdown with its hours, cause and recovery_hours; "
                f"port/traffic_hourly.csv the hourly traffic and queue) and from the hive's own plans this month "
                f"(memory_facts, subjects port/channel and port/anchorage). Then set the next month's priorities, at most three, "
                f"each for one section.")
        res = di.brain.run("brief", text, now, "executive", preamble=di.system(), extra_json=REVIEW_JSON)
        review = (res.answer or {}).get("review") if isinstance((res.answer or {}).get("review"), dict) else {}
        pr = [p for p in review.get("priorities") or [] if isinstance(p, dict) and p.get("priority")]
        if pr:
            link.add_facts(di.agent, [{"text": f"Priority for {p.get('section', 'the port')} from {nxt[:7]}, set by the director's "
                                               f"review of {m}: {p['priority']} Why: {p.get('why', '')}"[:400], "kind": "decision",
                                       "subjects": ["port/priorities", str(p.get("section") or "port"), f"run:{run}"], "since": nxt}
                                      for p in pr[:3]])
        results.append({"month": m, "at": now, "headline": (res.answer or {}).get("headline"), "review": review,
                        "tools": [t["tool"] for t in res.trace], "usd": res.usd, "seconds": res.seconds})
        print(m, "|", (res.answer or {}).get("headline"), "|", [(g.get("goal", "")[:40], g.get("met")) for g in review.get("goals") or []],
              "| priorities:", [p.get("section") for p in pr], flush=True)
    (out / "reviews.json").write_text(json.dumps(results, indent=1, default=str))
    print(json.dumps({"run": run, "months": len(results), "spend": ledger.summary()}, indent=1))


if __name__ == "__main__":
    main()
