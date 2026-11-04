# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""SAM 3.1 on every camera of the scene (people and vehicles, 2 frames a second), cached per camera, three at a time.

    python examples/warehouse/detect_floor.py [Camera_02 Camera_04 ...]
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor

from argus.models import Models, ledger
from argus.perception import floor as F


def main() -> None:
    cams = sys.argv[1:] or sorted(F.cameras())
    models = Models()

    def one(c: str) -> str:
        t0 = time.time()
        det = F.detect(models, c)
        return f"{c}: {det.get('_frames')} frames, {len(det.get('person', []))} person boxes, {len(det.get('vehicle', []))} vehicle boxes ({time.time() - t0:.0f} s)"
    with ThreadPoolExecutor(3) as ex:
        for line in ex.map(one, cams):
            print(line, flush=True)
    print(ledger.summary())


if __name__ == "__main__":
    main()
