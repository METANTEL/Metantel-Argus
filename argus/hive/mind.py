# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The hive: agents that share one purpose and one memory, and coordinate the way a CPU's caches keep copies coherent.

No agent here is a stateless function. Each one
- carries the site's **charter** (what the site is for, its goals, who may decide what) in every prompt;
- reads and writes the **shared memory**: the space's tables and items, and facts in sentences that any agent may add
  to or correct, so one agent's correction reaches every agent;
- keeps **working copies** of what it relies on (the floor's list of places where detections mislead, the current
  traffic plan, a queue sequence). A copy is a shared claim on a named resource. When an agent changes the resource it
  takes the claim for itself, and every other copy goes stale at once: the holders re-read before they act again;
- says what it **intends** before it acts, so a collision is seen before it happens, not after;
- talks to other agents directly, and hands what agents cannot settle to people as a decision card.

Perception agents are members like the others: they read the memory that managers keep (what to ignore, where to
look harder) and write what they see, keeping what was expected apart from what was seen.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..memory import Coordination
from ..models import Models, parse_json


@dataclass
class Goal:
    text: str                     # in plain words, as management would say it
    measure: str = ""             # how the hive knows it is meeting it, when it can be measured


@dataclass
class Charter:
    site: str
    purpose: str
    goals: list[Goal]
    sections: dict[str, str]      # section -> what it is responsible for
    authority: dict[str, str]     # role -> what it may decide alone, and what goes to people

    def render(self) -> str:
        lines = [f"SITE: {self.site}", f"PURPOSE: {self.purpose}", "GOALS:"]
        lines += [f"- {g.text}" + (f" (measured by: {g.measure})" if g.measure else "") for g in self.goals]
        lines += ["SECTIONS:"] + [f"- {s}: {d}" for s, d in self.sections.items()]
        lines += ["AUTHORITY:"] + [f"- {r}: {d}" for r, d in self.authority.items()]
        return "\n".join(lines)


@dataclass
class Copy:
    resource: str
    version: str
    data: Any
    stale: bool = False


@dataclass
class Member:
    link: Coordination
    charter: Charter
    agent: str
    role: str
    section: str
    goal: str
    models: Models | None = None
    provider: str = "baseten"           # Baseten's credit is spent first; Meta's API is the fallback and the comparison arm
    model: str | None = None
    copies: dict[str, Copy] = field(default_factory=dict)
    usd: float = 0.0
    calls: int = 0

    def announce(self) -> None:
        self.link.presence(self.agent, self.role, self.section, self.goal)

    # -- working copies --------------------------------------------------------------------------------------------------
    def hold(self, resource: str, version: str, data: Any) -> None:
        """Take a shared copy: the agent will be told (its copy goes stale) when someone changes the resource."""
        self.link.claim(self.agent, [resource], write=False, version=version)
        self.copies[resource] = Copy(resource, version, data)

    def stale(self, resources: list[str] | None = None) -> list[str]:
        """Which copies another agent has made stale since they were taken."""
        mine = [r for r in (resources or list(self.copies)) if r in self.copies]
        if not mine:
            return []
        states = self.link.state(self.agent, mine)["states"]
        out = [r for r, s in states.items() if s == "stale"]
        for r in out:
            self.copies[r].stale = True
        return out

    def change(self, resource: str, version: str, why: str) -> dict:
        """Say what is about to change and why, then own the resource: every other copy goes stale."""
        collisions = self.link.intend(self.agent, resource, "change", why)
        got = self.link.claim(self.agent, [resource], write=True, version=version)
        got["collisions"] = collisions
        return got

    def done(self, resource: str) -> None:
        """Finished changing it: let others claim it again (the change itself is in the memory)."""
        self.link.release(self.agent, [resource])
        self.link.clear(self.agent, resource)

    # -- thinking ---------------------------------------------------------------------------------------------------------
    def system(self, extra: str = "") -> str:
        return (f"You are {self.agent}, the {self.role} for the section '{self.section}' of a site run by a hive of AI agents "
                f"and the people who manage them. Your own goal: {self.goal}\n\n{self.charter.render()}\n\n"
                "You share one memory with every other agent. Facts you are given come from that memory, with who wrote "
                "them; trust what other agents corrected over what they first said. Keep what you expected apart from "
                "what you saw." + (f"\n\n{extra}" if extra else ""))

    def ask_json(self, prompt: str, *, images: list | None = None, extra: str = "", max_tokens: int = 4000) -> dict:
        from ..models import data_url
        content: Any = prompt
        if images:
            content = [{"type": "text", "text": prompt}] + [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        msgs = [{"role": "developer", "content": self.system(extra)}, {"role": "user", "content": content}]
        models = self.models or Models()
        out = models.chat(msgs, provider=self.provider, model=self.model, max_tokens=max_tokens, effort="low")
        self.usd += out.get("_usd", 0.0)
        self.calls += 1
        raw = out["choices"][0]["message"].get("content") or ""
        try:
            return parse_json(raw)
        except (ValueError, json.JSONDecodeError):
            return {"unparsed": raw[:2000]}
