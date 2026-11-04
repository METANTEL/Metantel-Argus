# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Re-file the compressor's daily notes and work orders with `t=<when known>` stamps, so agents bounded to a moment can
search them (`Agent(bounded=True)`). Same names, so each replaces its earlier copy.

    python examples/plant/stamp_plant_docs.py
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from argus.memory import Edip
from argus.sites.plant import feed as E
from argus.sites.plant import pack as S

TAGS = ["site=plant", "asset=APU-1"]


def main() -> None:
    edip = Edip()
    d = S.build()
    jobs = [(f"plant/apu/daily/{x['date']}.md", S.daily_note(x), "note", TAGS + ["code=DAILY", f"t={x['date']}T23:59"])
            for x in d["daily"]]
    jobs += [(f"plant/work-orders/{f['id']}.md", S.work_order(f), "ticket",
              TAGS + ["code=WORKORDER", "code=AIRLEAK", f"t={f['repaired'].replace(' ', 'T')}"]) for f in E.FAILURES]
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(lambda j: edip.ingest(*j), jobs))
    print(f"{len(jobs)} documents stamped")


if __name__ == "__main__":
    main()
