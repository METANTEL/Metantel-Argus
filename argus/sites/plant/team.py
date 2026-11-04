# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The plant as a hive: maintenance and operations, one train's air system, and the timetable between them.

Operations keeps a standing intent to *use* the unit (the train is on the timetable). When the compressor watcher
fires, the maintenance manager plans from the memory (the five-minute health table, the daily notes, similar past
episodes and how many of them ended in a leak). If it wants the train out for an inspection, it says so as an intent
to *change* the unit, which collides with operations' at once; the two negotiate by message within their authority,
and what they cannot settle goes to the depot manager as a decision card. An agreed inspection is a claim on the unit:
operations' copy of the timetable goes stale until it re-plans around it.
"""
from __future__ import annotations

from ...agent import Agent, Episodes
from ...hive.link import Link
from ...hive.manager import Manager
from ...hive.mind import Charter, Goal
from . import pack as S

UNIT = "unit:apu-1"
KNOWN_AT = {"plant/apu_episodes.csv": "known_at"}

CHARTER = Charter(
    site="a metro operator's depot; unit APU-1 is the air production unit (compressor) of a train in daily service",
    purpose="Run the timetable with trains whose air systems are healthy: catch failures before they happen in service, "
            "without taking trains out for nothing.",
    goals=[Goal("No air-system failure in service", "failures while the train is in service"),
           Goal("The timetable is met: no train withdrawn at a peak without a replacement", "peak withdrawals"),
           Goal("Inspections are planned, not forced by failures", "share of repairs that followed a planned inspection"),
           Goal("Agents settle what they can; people decide only real trade-offs", "decisions sent to people")],
    sections={"plant/maintenance": "the train's systems: warnings, inspections, repairs",
              "plant/operations": "the timetable: which trains run when, spares, peak hours 07:00-10:00 and 17:00-20:00"},
    authority={"maintenance manager": "may inspect a train outside peak hours on its own; taking a train out at a peak, or "
                                      "for more than 4 hours, needs operations' agreement",
               "operations manager": "assigns trains to the timetable; can release a train at any time when a spare is "
                                     "available (one spare on weekdays, two at weekends)",
               "people": "the depot manager decides when maintenance and operations disagree"})

PLAN_JSON = ('"plan": {"action": "inspect_now|inspect_off_peak|watch", "window_start": "YYYY-MM-DD HH:MM", "window_hours": '
             'number, "risk": "one line", "why": "one line"}, where action is what you will do about this warning, '
             'window_start and window_hours the inspection you want (empty for watch), and risk what the memory says about '
             'how often episodes like this ended in a leak')


def make(link: Link, edip, models, provider: str = "baseten", run: str = "") -> dict[str, Manager]:
    from ...hive.manager import facts_for
    episodes = Episodes(edip, {"compressor": "plant/apu_episodes.csv"}, {"compressor": S.EPISODE_FEATURES},
                        {"compressor": S.EPISODE_OUTCOMES})
    spec = {"maintenance": ("plant/maintenance", "maintenance manager", "plant/maintenance",
                            "Catch air-system failures before they happen in service, with as few needless inspections as possible"),
            "operations": ("plant/operations", "operations manager", "plant/operations",
                           "Run every timetabled service, peaks first, and release trains for maintenance when it can")}
    out = {}
    for k, (agent, role, section, goal) in spec.items():
        m = Manager(link, CHARTER, agent, role, section, goal, models=models, provider=provider)
        m.brain = Agent(S.SITE, edip, models, episodes, provider=provider, bounded=True, known_at=KNOWN_AT,
                        site_tag="site=plant", max_calls=7, facts=facts_for(link, run) if run else None)
        out[k] = m
    return out
