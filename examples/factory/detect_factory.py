# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""SAM 3.1 on the factory's camera halls (B: people, humanoid robots and vehicles on 12 cameras; C: people on 6),
each camera as soon as its video has downloaded, three at a time. Results are cached per scene.

    python examples/factory/detect_factory.py
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from argus.models import Models, ledger
from argus.sites.factory import feed as FX


def main() -> None:
    models = Models()
    jobs = [(h, c) for h in ("B", "C") for c in FX.cameras(h)]

    def one(job: tuple[str, str]) -> str:
        hall, cam = job
        video = FX.scene_dir(hall) / "videos" / f"{cam}.mp4"
        for _ in range(240):                    # wait up to 20 minutes for the download
            if video.exists() and video.stat().st_size > 0:
                break
            time.sleep(5)
        t0 = time.time()
        det = FX.detect(models, hall, cam)
        counts = {k: len(v) for k, v in det.items() if not k.startswith("_")}
        return f"{hall} {cam}: {counts} ({time.time() - t0:.0f} s)"

    with ThreadPoolExecutor(3) as ex:
        for line in ex.map(one, jobs):
            print(line, flush=True)
    print(ledger.summary(), flush=True)


if __name__ == "__main__":
    main()
