# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Ask each site's questions three ways (Argus with the memory, a window of recent reports, nothing) and score them.

    python examples/eval_qa.py equipment|port [--window-days 30]
"""
from __future__ import annotations

import argparse
import json
import time

from argus.agent import Agent, Episodes
from argus.config import RUNS
from argus.eval import qa
from argus.memory import Edip
from argus.models import Models, ledger


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=["equipment", "port"])
    ap.add_argument("--window-days", type=int, default=30)
    a = ap.parse_args()
    edip, models = Edip(), Models()
    if a.site == "equipment":
        from argus.sites.plant import feed as E
        from argus.sites.plant import pack as S
        d = S.build()
        qs = qa.equipment_questions(d["daily"], d["five_min"], d["episodes"], E.FAILURES)
        now = "2020-09-01 06:00"
        window = "\n".join(S.daily_note(x) for x in d["daily"][-a.window_days:])
        full = "\n".join(S.daily_note(x) for x in d["daily"]) + "\n" + "\n".join(S.work_order(f) for f in E.FAILURES)
        agent = Agent(S.SITE, edip, models, Episodes(edip, {"compressor": "plant/apu_episodes.csv"},
                                                         {"compressor": S.EPISODE_FEATURES}, {"compressor": S.EPISODE_OUTCOMES}))
    else:
        from argus.sites.port import pack as S
        d = S.build()
        rows = S.slowdown_rows(d["status"], d["slowdowns"])
        qs = qa.port_questions(d["status"], d["events"], rows)
        now = d["status"][-1]["time"]
        reports = S.daily_reports(d["status"], d["events"], d["slowdowns"])
        window = "\n".join(t for _, _, t in reports[-a.window_days:])
        full = "\n".join(t for _, _, t in reports) + "\n" + "\n".join(S.slowdown_facts(r) for r in rows)
        agent = Agent(S.SITE, edip, models, Episodes(edip, {"slowdown": "port/slowdowns.csv"},
                                                         {"slowdown": S.EPISODE_FEATURES}, {"slowdown": S.EPISODE_OUTCOMES}))
    out = qa.run(qs, agent, models, now, window, full)
    out["now"], out["window_days"], out["window_chars"], out["full_chars"], out["spend"] = now, a.window_days, len(window), len(full), ledger.summary()
    run = RUNS / "qa" / f"{a.site}-{time.strftime('%Y%m%d-%H%M')}.json"
    run.parent.mkdir(parents=True, exist_ok=True)
    run.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps({k: out[k] for k in ("n", "correct", "now", "window_days", "window_chars", "full_chars", "spend")}, indent=1))
    for r in out["rows"]:
        print(r["id"], {k: r[k] for k in ("argus", "window", "full", "none")}, r["gold"])


if __name__ == "__main__":
    main()
