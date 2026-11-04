# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
from __future__ import annotations

import argparse

from ..config import DATA
from .server import serve


def main() -> None:
    ap = argparse.ArgumentParser(description="The Argus console, on this machine. It shows the factory reference site.")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if not (DATA / "factory-compiled.pkl").exists():
        raise SystemExit("The console shows the factory site, and its memory is not built yet: run the steps in "
                         "examples/factory/README.md (examples/factory/ingest_factory.py writes data/factory-compiled.pkl).")
    serve(a.port)


if __name__ == "__main__":
    main()
