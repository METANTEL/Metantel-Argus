# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""A section manager: a hive member whose thinking is the reasoning agent (`argus.agent.Agent`).

The member side (charter, working copies, intents, messages) is `Member`; the thinking side is the `Agent`, which reads
the site's memory through tools and answers as JSON. A `Manager` joins them: it puts the member's system prompt (the
charter and its own goal) in front of the agent's, and reports what each decision cost. Every site's team (port, plant,
factory) is built from managers, watchers and a director that differ only in charter, goal and tools.
"""
from __future__ import annotations

from ..agent import Agent
from ..memory import Coordination, Memory
from .mind import Member

KNOWLEDGE = "site-knowledge"     # facts that hold across runs: what people corrected or taught the hive

_TABLES: dict[str, list[str]] = {}


def tables_note(memory: Memory, prefix: str) -> str:
    """The section's tables and columns, given up front so no agent spends a tool call listing them."""
    if prefix not in _TABLES:
        _TABLES[prefix] = [f"- {t['artifact']} ({t.get('rows')} rows): " + ", ".join(c["name"] for c in t.get("columns", []))
                           for t in memory.tables().get("tables", []) if str(t["artifact"]).startswith(prefix)]
    return "TABLES (no need to list them again):\n" + "\n".join(_TABLES[prefix])


class Manager(Member):
    brain: Agent | None = None
    tables_prefix: str = ""          # list the tables under this prefix (e.g. "port/") in every prompt; "" lists none

    def think(self, mode: str, text: str, now: str, audience: str, context: str, extra_json: str) -> dict:
        if self.tables_prefix:
            context = (context + "\n\n" if context else "") + tables_note(self.brain.edip, self.tables_prefix)
        res = self.brain.run(mode, text, now, audience, context=context, preamble=self.system(), extra_json=extra_json)
        self.usd += res.usd
        self.calls += 1
        return {"answer": res.answer, "usd": res.usd, "seconds": res.seconds, "tools": [t["tool"] for t in res.trace]}


def facts_for(link: Coordination, run: str):
    """The shared facts an agent may see at `now`: this run's and the site's standing knowledge, dated at or before now."""
    def get(args: dict, now: str) -> list[dict]:
        seen: list[dict] = []
        for subject in (f"run:{run}", KNOWLEDGE):
            seen += link.facts(subject=subject, q=str(args.get("q") or "")[:100], limit=60)
        want = str(args.get("subject") or "").lower()
        ok = [f for f in seen if (f["since"] or "")[:16].replace("T", " ") <= now and (not want or want in f["subjects"])]
        return sorted({f["id"]: f for f in ok}.values(), key=lambda f: f["since"], reverse=True)
    return get
