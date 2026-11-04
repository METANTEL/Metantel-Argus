# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Compile a whole year of Houston AIS once: positions into a database file, then the hourly traffic, vessel events,
vessels and slowdowns that go to the memory, cached so the replay and the hive runs do not compile again.

    python examples/port/compile_port.py            # data/ais/houston.duckdb and data/ais/compiled-2024.pkl
"""
from __future__ import annotations

import pickle
import time

from argus.config import DATA
from argus.sites.port import feed as P

DB = DATA / "ais" / "houston.duckdb"
OUT = DATA / "ais" / "compiled-2024.pkl"


def main() -> None:
    t0 = time.time()
    c = P.con(path=DB)
    print(f"positions: {c.sql('SELECT count(*) FROM p').fetchall()[0][0]:,} in {time.time() - t0:.0f} s", flush=True)
    st = P.status(c)
    print(f"hourly rows: {len(st):,} ({time.time() - t0:.0f} s)", flush=True)
    sl = P.slowdowns(st)
    print(f"slowdowns: {len(sl)}", flush=True)
    ev = P.events(c)
    print(f"events: {len(ev):,} ({time.time() - t0:.0f} s)", flush=True)
    vs = P.vessels(c)
    print(f"vessels: {len(vs):,}", flush=True)
    OUT.write_bytes(pickle.dumps({"status": st, "slowdowns": sl, "events": ev, "vessels": vs}))
    print(f"done in {time.time() - t0:.0f} s -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
