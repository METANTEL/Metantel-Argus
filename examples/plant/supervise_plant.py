# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The plant's sensor supervisor at work on the compressor's log (MetroPT-3, 2020): the same checks and remedies as the
camera supervisor (argus/sites/factory/supervise.py), on a different system. It finds the stretches where the analog channels
stopped changing while the compressor's duty signal kept reporting, judges each one with the numbers around it, and tells
the hive which of the watcher's warnings stood on them.

    python examples/plant/supervise_plant.py
"""
from __future__ import annotations

import json
import time

from argus.config import RUNS
from argus.hive import supervise as S
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.plant import feed as E
from argus.sites.plant import pack as P
from argus.sites.plant import team as HP

KNOWLEDGE = ["The compressor (APU-1) of a metro train logs 15 signals every 10 seconds; the watcher reads five-minute "
             "summaries: duty (share of time the compressor loads, from its COMP signal), pressures (TP2, TP3, reservoirs), "
             "oil temperature and motor current.",
             "A compressor that loads draws motor current; pressure and oil temperature move while it cycles.",
             "The operator logged four air leaks in 2020 (18 April, 29 May, 5 June, 15 July)."]
CHANNELS = ["tp3_bar", "motor_current_a", "oil_temp_c"]


def main() -> None:
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "supervise" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    sup = S.SensorSupervisor(link, HP.CHARTER, "plant/sensors", "sensor supervisor", "plant/maintenance",
                             "Nothing the compressor's watcher acts on rests on readings that were not really measured",
                             models=models, provider="baseten", watches="the compressor's sensor log (MetroPT-3)", out_dir=out)
    sup.announce()
    rows = E.five_min(E.con())
    warnings = P.firings()                        # the warnings of the latest replay (run_equipment.py)
    for issue in sup.frozen_check(rows, CHANNELS, "duty_pct"):
        ev = issue.evidence
        hit = [w for w in warnings if ev["start"] <= w["episode_start"] <= ev["end"] or ev["start"] <= w["fired_at"] <= ev["end"]]
        ev["warnings_inside"] = [{"fired_at": w["fired_at"], "headline": w["headline"]} for w in hit]
        v = sup.judge(issue, "no images: the five-minute rows just before, at the start of, and just after the stretch are in "
                      "the evidence", KNOWLEDGE, ["correct", "rederive", "accept", "ask_people"])
        remedy = str(v.get("remedy") or "accept")

        def correct(i: S.Issue) -> dict:
            text = (f"Sensor supervisor: {i.verdict.get('finding', '')} From {ev['start']} to {ev['end']} the compressor's "
                    f"pressure, motor current and oil temperature are not measurements; "
                    + (f"{len(hit)} watcher warning(s) fired on this stretch ({', '.join(w['fired_at'] for w in hit)})."
                       if hit else "no watcher warning fired on it."))
            sup.tell(text, "event", ["unit:apu-1", "sensor-quality", f"from:{ev['start']}"], ev["start"])
            return {"told": text, "warnings_inside": [w["fired_at"] for w in hit]}
        sup.remedies = {"correct": correct, "rederive": correct, "accept": lambda i: {}, "ask_people": lambda i: {}}
        res = sup.apply(issue, remedy)
        print(ev["start"], "→", ev["end"], f"{ev['hours']} h", "| warnings inside:", [w["fired_at"] for w in hit], "|", remedy, "|",
              (v.get("finding") or "")[:160], flush=True)
        if v.get("lesson") and remedy in ("correct", "rederive"):
            lesson = str(v["lesson"])
    if sup.log and any(i.remedy in ("correct", "rederive") for i in sup.log):
        sup.tell(lesson, "lesson", ["unit:apu-1", "sensor-quality"], rows[-1]["time"])
    sup.save()
    print(json.dumps(ledger.summary(), indent=1))
    print(out)


if __name__ == "__main__":
    main()
