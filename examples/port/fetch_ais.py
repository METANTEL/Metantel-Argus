# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Download NOAA's daily AIS files and keep only the Houston Ship Channel and Galveston Bay.

Each national file is about 230 MB; the Houston box is about 7% of it. A day is downloaded, filtered to
`data/ais/houston/ais-YYYY-MM-DD.parquet` (with plain lon/lat columns), and the national file is deleted, so the disk
never holds more than a few national files at once. Finished days are skipped, so the script can be rerun.

    python examples/port/fetch_ais.py [days.txt] --workers 3      # no file: every day of 2024 (about 80 GB to download, 2 GB kept)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import httpx

from argus.config import DATA

URL = "https://ocmgeodatastor1.blob.core.windows.net/marinecadastre/ais2024/ais-{day}.parquet"
BOX = dict(lat_min=28.95, lat_max=29.85, lon_min=-95.35, lon_max=-94.40)
RAW = DATA / "ais" / "raw"
OUT = DATA / "ais" / "houston"


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def download(day: str) -> Path:
    RAW.mkdir(parents=True, exist_ok=True)  # noqa: F823 - RAW may be set by --raw
    path = RAW / f"ais-{day}.parquet"
    url = URL.format(day=day)
    for attempt in range(6):
        try:
            with httpx.stream("GET", url, timeout=httpx.Timeout(60, read=300)) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                with path.open("wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            if total and path.stat().st_size != total:
                raise IOError(f"short read {path.stat().st_size}/{total}")
            return path
        except Exception as e:  # noqa: BLE001 - retry any network failure
            log(f"{day}: download attempt {attempt + 1} failed: {e}")
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"{day}: download failed")


def filter_day(raw: Path, out: Path) -> int:
    con = duckdb.connect()
    con.sql("INSTALL spatial; LOAD spatial;")
    tmp = out.with_suffix(".tmp")
    con.sql(f"""
        COPY (
          SELECT mmsi, base_date_time AS ts, ST_Y(geometry::GEOMETRY) AS lat, ST_X(geometry::GEOMETRY) AS lon,
                 sog, cog, heading, vessel_name, imo, call_sign, vessel_type, status, length, width, draft, cargo
          FROM '{raw}'
          WHERE ST_Y(geometry::GEOMETRY) BETWEEN {BOX['lat_min']} AND {BOX['lat_max']}
            AND ST_X(geometry::GEOMETRY) BETWEEN {BOX['lon_min']} AND {BOX['lon_max']}
          ORDER BY mmsi, ts
        ) TO '{tmp}' (FORMAT parquet, COMPRESSION zstd)""")
    n = con.sql(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchall()[0][0]
    tmp.rename(out)
    return n


def _complete(path: Path) -> bool:
    """A national file left by an earlier run, kept only if its parquet footer reads."""
    if not path.exists():
        return False
    try:
        duckdb.connect().sql(f"SELECT count(*) FROM read_parquet('{path}')").fetchall()
        return True
    except duckdb.Error:
        return False


def one(day: str) -> None:
    out = OUT / f"ais-{day}.parquet"
    if out.exists():
        return
    t0 = time.time()
    raw = RAW / f"ais-{day}.parquet"
    if not _complete(raw):
        raw = download(day)
    n = filter_day(raw, out)
    raw.unlink()
    log(f"{day}: {n:,} Houston rows in {time.time() - t0:.0f} s")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="?", help="a file with one YYYY-MM-DD per line, in priority order (default: every day of 2024)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--raw", default=None, help="where national files wait to be filtered (one folder per downloader)")
    a = ap.parse_args()
    global RAW
    if a.raw:
        RAW = Path(a.raw)
    OUT.mkdir(parents=True, exist_ok=True)
    days = ([d.strip() for d in Path(a.days).read_text().split() if d.strip()] if a.days
            else [(date(2024, 1, 1) + timedelta(n)).isoformat() for n in range(366)])
    log(f"{len(days)} days queued, {sum((OUT / f'ais-{d}.parquet').exists() for d in days)} already done")
    with ThreadPoolExecutor(a.workers) as ex:
        for f in [ex.submit(one, d) for d in days]:
            try:
                f.result()
            except Exception as e:  # noqa: BLE001 - one bad day must not stop the rest
                log(f"FAILED: {e}")
    log("all queued days processed")


if __name__ == "__main__":
    sys.exit(main())
