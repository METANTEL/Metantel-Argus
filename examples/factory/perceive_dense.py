# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Everyone every camera of a hall sees: SAM 3.1 in tiles at the camera's own resolution, a full tile looked at again
in four (argus/perception/tiles.py). Cached per region, so a rerun only pays for what is missing.

    python examples/factory/perceive_dense.py A [--concept person] [--cameras Camera_10,Camera_12]
"""
from __future__ import annotations

import argparse
import json
import time

from argus.models import Models, ledger
from argus.perception import tiles as P
from argus.sites.factory import feed as FX


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("hall")
    ap.add_argument("--concept", default="person")
    ap.add_argument("--cameras", default="")
    ap.add_argument("--depth", type=int, default=2)
    a = ap.parse_args()
    models = Models()
    cams = a.cameras.split(",") if a.cameras else FX.cameras(a.hall)
    t0 = time.time()
    from concurrent.futures import ThreadPoolExecutor

    def one(cam: str) -> tuple[str, int, int]:
        d = P.dense(models, a.hall, cam, a.concept, max_depth=a.depth)
        print(f"{cam}: {len(d['boxes'])} boxes from {len(d['tiles'])} tiles ({time.time() - t0:.0f} s)", flush=True)
        return cam, len(d["boxes"]), len(d["tiles"])
    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, cams))
    print(json.dumps(ledger.summary(), indent=1))


if __name__ == "__main__":
    main()
