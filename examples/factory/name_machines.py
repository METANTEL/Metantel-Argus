# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The camera supervisor has the machines on a hall's cameras named and followed: Muse Spark tags each machine on a
keyframe (what it is, whether it is being driven), SAM 3.1 follows each tag with a box and a mask, and where a named
machine is lost or a new one appears, Muse Spark tags that moment again and SAM is prompted again from there
(argus/perception/naming.py, argus/sites/factory/supervise.py). Every re-tag is an issue in the supervisor's log.

    python examples/factory/name_machines.py [--hall A] [--cameras Camera_01,Camera_10]
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from argus.config import RUNS
from argus.hive import supervise as S
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.factory import feed as FX
from argus.sites.factory import supervise as CS
from argus.sites.factory import team as H

KNOWLEDGE = ["Hall A's machines, as the people who run it describe them: yellow forklifts with a black overhead guard and a "
             "mast; an autonomous transporter, a low, flat, yellow cart with a blue base and a flat grey deck, knee high, with "
             "no seat and no mast; a small mobile robot, a white box on two black wheels with a blue sensor on top. The "
             "transporter and the robot drive themselves; nobody sits on them.",
             "The footage is a simulation: some people are drawn semi-transparent."]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hall", default="A")
    ap.add_argument("--cameras", default="")
    a = ap.parse_args()
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "supervise" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    sup = CS.CameraSupervisor(link, H.CHARTER, f"factory/perception-{a.hall.lower()}", "camera supervisor", "factory/perception",
                             f"Everyone and every machine in Hall {a.hall}'s view followed, and nothing in memory the cameras "
                             "did not really see", models=models, provider="meta", model="muse-spark-1.3",
                             watches=f"SAM 3.1 on Hall {a.hall}'s cameras", out_dir=out, hall=a.hall)
    sup.announce()
    cams = a.cameras.split(",") if a.cameras else [c for c in FX.cameras(a.hall)
                                                   if FX.detect(None, a.hall, c, dense=False, tagged=False).get("vehicle")]

    def one(cam: str) -> tuple[str, dict]:
        try:
            return cam, CS.name_machines(sup, models, cam, KNOWLEDGE)
        except Exception as e:  # noqa: BLE001 - one camera's failure is logged; the others go on
            return cam, {"error": str(e)[:200]}
    with ThreadPoolExecutor(4) as ex:
        for cam, res in ex.map(one, cams):
            print(cam, json.dumps(res), flush=True)
    sup.save()
    print(json.dumps(ledger.summary(), indent=1))
    print(out)


if __name__ == "__main__":
    main()
