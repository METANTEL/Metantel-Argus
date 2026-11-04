# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Put a whole year of the port into the memory at once, for runs whose agents are kept at "now" by their tools
(`Agent(bounded=True)`): every document carries `t=<when it became known>`, and the episode table's `known_at` says
when each slowdown's outcome was learned. The tables replace those of earlier replays; documents keep their names, so
the year replaces the earlier days' copies.

    python examples/port/ingest_port_year.py [--skip-tables] [--skip-docs]
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor

from argus.config import DATA, load_cache
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.port import pack as S

from run_port import EVENTS, SLOW, TRAFFIC, VESSELS, WRITEUP


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-tables", action="store_true")
    ap.add_argument("--skip-docs", action="store_true")
    a = ap.parse_args()
    data = load_cache(DATA / "ais" / "compiled-2024.pkl")
    edip, models = Edip(), Models()
    rows = S.slowdown_rows(data["status"], data["slowdowns"])
    t0 = time.time()
    if not a.skip_tables:
        for name, header, recs in (("port/traffic_hourly.csv", TRAFFIC, data["status"]),
                                   ("port/vessels.csv", VESSELS, data["vessels"]),
                                   ("port/slowdowns.csv", SLOW, rows),
                                   ("port/vessel_events.csv", EVENTS, data["events"])):
            edip.ingest_table(name, header, [[r.get(h, "") for h in header] for r in recs], S.TAGS)
            print(f"{name}: {len(recs):,} rows ({time.time() - t0:.0f} s)", flush=True)
    if a.skip_docs:
        return

    def report(item: tuple[str, str, str]) -> None:
        d, name, text = item
        edip.ingest(name, text, "report", S.TAGS + ["code=DAILY", f"t={d}T23:59"])

    def writeup(r: dict) -> None:
        facts = S.slowdown_facts(r)
        try:
            prose = models.text(WRITEUP.format(facts=facts), provider="baseten", effort=None, max_tokens=700)
        except Exception as e:  # noqa: BLE001 - the figures alone still make a usable note
            prose = f"(write-up unavailable: {str(e)[:80]})"
        text = f"# Slowdown {r['start']} UTC — {r['cause']}\n\n{prose}\n\n## Figures\n\n{facts}\n"
        tags = S.TAGS + ["code=SLOWDOWN", f"t={r['known_at'].replace(' ', 'T')}"] + (["code=FOG"] if "fog" in r["cause"] else [])
        edip.ingest(f"port/slowdowns/{r['start'][:10]}-{r['start'][11:13]}{r['start'][14:16]}.md", text, "incident", tags)

    reports = S.daily_reports(data["status"], data["events"], data["slowdowns"])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(report, reports))
        print(f"daily reports: {len(reports)} ({time.time() - t0:.0f} s)", flush=True)
        list(ex.map(writeup, rows))
    print(f"slowdown write-ups: {len(rows)} ({time.time() - t0:.0f} s); spend {ledger.summary()}", flush=True)


if __name__ == "__main__":
    main()
