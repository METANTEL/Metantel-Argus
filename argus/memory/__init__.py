# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The memory Argus works through.

Argus never holds a site's raw feeds in a model's context. Compilers and perception models turn them into a compact record
in a memory, and every agent reasons and coordinates through it. The harness asks two things of a memory, written down here
as protocols so that a backend can be put behind them:

- `Memory`: read and write the site's knowledge: search, exact queries, ingest, append. The agent (`argus.agent`), the
  replay (`argus.replay`) and the section managers (`argus.hive.manager`) use it.
- `Coordination`: how agents find each other, say what they intend, claim and release what they rely on, message each
  other, hand decisions to people and share facts. `argus.hive.link.Link` is the one implementation.

The reference memory is Metantel's Managed Memory Harness (`argus.memory.metantel.Edip` is its client). See docs/MEMORY.md.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .metantel import DryEdip, Edip, EdipError

__all__ = ["Coordination", "DryEdip", "Edip", "EdipError", "Memory"]


@runtime_checkable
class Memory(Protocol):
    """What the harness needs to read from and write to a site's memory."""

    def search(self, query: str, limit: int = 10, codes: list[str] | None = None, passages: bool = False) -> dict:
        """Items and records that answer a request in plain words: {"hits": [{item, record, locator, text, tags, score}]}."""

    def items(self, limit: int = 100, codes: list[str] | None = None) -> dict:
        """What the memory holds, newest first, optionally only items carrying all of the tag codes."""

    def tables(self) -> dict:
        """The tables and their columns: {"tables": [{"artifact", "rows", "columns": [{"name", "kind", "role"}]}]}."""

    def query(self, plan: dict | None = None, question: str | None = None, table: str | None = None,
              budget: int = 6000) -> dict:
        """An exact table plan (counts, latest states, durations, gaps, traces): {"text", "result": {"columns", "rows"}}.
        A backend that cannot run a plan raises `EdipError`."""

    def ingest(self, name: str, text: str, kind: str = "document", tags: list | None = None) -> dict:
        """Put an item in, under a stable name: ingesting the name again replaces it."""

    def ingest_table(self, name: str, header: list[str], rows: list[list[Any]], tags: list | None = None) -> dict:
        """Create (or replace) a table from rows."""

    def append(self, artifact: str, rows: list[list[Any]]) -> dict:
        """Append rows to a table created by `ingest_table` or `ingest(kind="table")`."""


@runtime_checkable
class Coordination(Protocol):
    """How agents coordinate through the memory. Presence and intents say who is there and what they will change; a claim
    is a shared copy of a named resource that goes stale when another agent takes it to change it."""

    def presence(self, agent: str, role: str, section: str = "", goal: str = "") -> None: ...
    def leave(self, agent: str) -> None: ...
    def roster(self) -> dict: ...
    def intend(self, agent: str, resource: str, verb: str, why: str, ttl: int = 900) -> list[dict]: ...
    def clear(self, agent: str, resource: str) -> None: ...
    def claim(self, agent: str, resources: list[str], write: bool = False, version: str = "", ttl: int = 1800) -> dict: ...
    def state(self, agent: str, resources: list[str]) -> dict: ...
    def release(self, agent: str, resources: list[str]) -> None: ...
    def send(self, sender: str, to: str, text: str, importance: str = "normal", reply_to: str = "", section: str = "") -> str: ...
    def inbox(self, agent: str) -> list[dict]: ...
    def card(self, agent: str, resource: str, title: str, detail: str, options: list[dict], between: list[str],
             positions: dict[str, str], card_id: str = "", at: str = "") -> dict: ...
    def cards(self, open_only: bool = False) -> list[dict]: ...
    def resolve(self, card_id: str, resolution: str, note: str = "", by: str = "") -> dict: ...
    def signals(self) -> list[dict]: ...
    def add_facts(self, agent: str, facts: list[dict]) -> list[dict]: ...
    def facts(self, **params: Any) -> list[dict]: ...
    def correct(self, agent: str, fact: str, correction: str, why: str, at: str = "") -> dict: ...
