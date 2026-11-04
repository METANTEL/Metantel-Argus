# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The Argus console: the site as the harness sees it, on this machine.

    python -m argus.console [--port 8765]

- **Site**: every hall live on one clock, each through its own sources.
- **Floor**: one hall on its plan: people, vehicles and robots, their danger zones, parked machines, close calls.
- **Cameras**: a camera's footage with what perception followed in it, the danger zone of each moving machine drawn on
  the floor, and the people inside it.
- **Ask**: a question to the site's managers, answered from the memory, every call to the memory shown as it happens.
- **Hive**: the agents' coordination as it happened: intents, collisions, messages, stale copies, decisions; and the
  decisions waiting for people, decided here.
- **Supervisors**: what the supervisors found in the models' output, what they looked at, and what they changed.

The demo's videos are rendered from the same records the console reads.
"""
