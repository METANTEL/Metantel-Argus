# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""People teach the hive: corrections a harbor master would make, recorded as standing site knowledge in the shared
memory, each dated when it became known. Every agent that looks at the memory's facts after that date sees them.

The visibility rule labels a slowdown "fog or haze" when visibility is low; two of 2024's longest were storms whose
rain brought visibility down, and the port was shut for the storm, not for fog.

    python examples/port/hive_teach.py
"""
from __future__ import annotations

from argus.hive.link import Link
from argus.hive.manager import KNOWLEDGE
from argus.memory import Edip

LESSONS = [
    {"text": "Correction from the harbor master: the 36-hour slowdown from 2024-06-19 02:00 UTC was Tropical Storm Alberto's "
             "rain and wind along the Texas coast, not fog; storms close the channel for a day or more.",
     "since": "2024-06-21 12:00"},
    {"text": "Correction from the harbor master: the 36-hour slowdown from 2024-07-08 01:00 UTC was Hurricane Beryl, which "
             "made landfall on the Texas coast on 8 July 2024; the port was shut for the storm, not for fog.",
     "since": "2024-07-10 12:00"},
]


def main() -> None:
    link = Link(Edip())
    link.presence("port/director", "director", "port/director",
                  "Keep the whole port meeting its goals, and bring people in only for what agents cannot settle")
    out = link.add_facts("port/director", [{**f, "kind": "event", "subjects": [KNOWLEDGE, "port/channel", "cause"],
                                            "source": "people/harbor-master"} for f in LESSONS])
    for f in out:
        print(f["id"], f["text"][:100])


if __name__ == "__main__":
    main()
