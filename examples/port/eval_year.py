# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Ask a year of the port at the year's end, three ways (`argus.eval.year`), and score the answers.

    python examples/port/eval_year.py [--arms argus,reports,context] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import time

from argus.agent import Agent, Episodes
from argus.config import DATA, RUNS, load_cache
from argus.eval import year
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.port import pack as S

CONTEXT_EVENTS = 23000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="argus,reports,context")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="question ids to ask, e.g. y6,y7 (default: all)")
    ap.add_argument("--provider", default="baseten")
    ap.add_argument("--model", default=None)
    a = ap.parse_args()
    d = load_cache(DATA / "ais" / "compiled-2024.pkl")
    qs = year.questions(d["status"], d["events"])
    if a.only:
        qs = [q for q in qs if q.id in a.only.split(",")]
    if a.limit:
        qs = qs[:a.limit]
    now = "2024-12-31 23:59"
    reports = "\n".join(t for _, _, t in S.daily_reports(d["status"], d["events"], d["slowdowns"]))
    cols = ("time", "mmsi", "vessel", "type", "event", "zone", "sog", "note")
    context = "time,mmsi,vessel,type,event,zone,sog,note\n" + "\n".join(
        ",".join(str(e.get(k, "")) for k in cols) for e in d["events"][-CONTEXT_EVENTS:])
    edip, models = Edip(), Models()
    year.PROVIDER.update(provider=a.provider, model=a.model)
    agent = Agent(S.SITE, edip, models, Episodes(edip, {"slowdown": "port/slowdowns.csv"}, {"slowdown": S.EPISODE_FEATURES},
                                                 {"slowdown": S.EPISODE_OUTCOMES}), provider=a.provider, model=a.model, max_calls=8)
    out = year.run(qs, agent, models, now, reports, context, tuple(a.arms.split(",")))
    out.update(now=now, reports_chars=len(reports), context_chars=len(context), context_events=CONTEXT_EVENTS,
               context_from=d["events"][-CONTEXT_EVENTS]["time"], all_events=len(d["events"]), spend=ledger.summary())
    path = RUNS / "qa" / f"year-{time.strftime('%Y%m%d-%H%M')}-{(a.model or a.provider).split('/')[-1]}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("n", "correct", "reports_chars", "context_chars", "context_from", "spend")}, indent=1))


if __name__ == "__main__":
    main()
