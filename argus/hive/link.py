# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The hive's link to the Managed Memory Harness: how Argus's agents find each other, say what they intend, claim what
they change, message, hand decisions to people and share facts.

Coordination calls use the space's serve key; facts are memory, so they are written with its ingest key. Every call is
logged, so a run can count what coordination cost and when each agent learned what.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from ..memory import EdipError, Memory


class Link:
    def __init__(self, edip: Memory, log: Path | None = None):
        self.edip, self.log = edip, log
        self.cursor = 0
        self.counts: dict[str, int] = {}
        self._known: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _note(self, what: str, **kw: Any) -> None:
        with self._lock:
            self.counts[what] = self.counts.get(what, 0) + 1
            if self.log:
                with self.log.open("a") as f:
                    f.write(json.dumps({"wall": round(time.time(), 2), "call": what, **kw}, default=str) + "\n")

    def _run(self, method: str, path: str, body: Any = None, params: dict | None = None, key: str | None = None) -> Any:
        """A call to the agent routes. An agent whose presence lapsed (another run signed it out, or a restart) is
        announced again with what it said last time, and the call is made once more."""
        try:
            return self.edip._call(method, f"/agents{path}", key or self.edip.k.serve_key, body, params)
        except EdipError as e:
            who = next((self._known[a] for a in self._known if f"{a} has not announced itself" in str(e.body)), None)
            if e.status != 409 or who is None:
                raise
            self.edip._call("POST", "/agents/presence", self.edip.k.serve_key, who)
            self._note("re-presence", agent=who["agent"])
            return self.edip._call(method, f"/agents{path}", key or self.edip.k.serve_key, body, params)

    # -- presence and intents -----------------------------------------------------------------------------------------
    def presence(self, agent: str, role: str, section: str = "", goal: str = "") -> None:
        body = {"agent": agent, "role": role, "section": section, "goal": goal}
        self._run("POST", "/presence", body)
        self._known[agent] = body
        self._note("presence", agent=agent)

    def leave(self, agent: str) -> None:
        self._run("POST", "/leave", {"agent": agent})
        self._note("leave", agent=agent)

    def roster(self) -> dict:
        return self.edip._call("GET", "/agents", self.edip.k.serve_key)

    def intend(self, agent: str, resource: str, verb: str, why: str, ttl: int = 900) -> list[dict]:
        out = self._run("POST", "/intent", {"agent": agent, "resource": resource, "verb": verb, "why": why, "ttlSecs": ttl})
        self._note("intent", agent=agent, resource=resource, verb=verb, collisions=[c["agent"] for c in out["collisions"]])
        return out["collisions"]

    def clear(self, agent: str, resource: str) -> None:
        self._run("POST", "/intent/clear", {"agent": agent, "resource": resource})

    # -- claims: shared copies, owners, stale copies --------------------------------------------------------------------
    def claim(self, agent: str, resources: list[str], write: bool = False, version: str = "", ttl: int = 1800) -> dict:
        """{granted, stale} or {held: {resource, heldBy, state}} when another agent owns it."""
        try:
            out = self._run("POST", "/claim", {"agent": agent, "resources": resources, "write": write, "version": version,
                                               "ttlSecs": ttl})
        except EdipError as e:
            if e.status == 409 and isinstance(e.body, dict):
                self._note("claim_held", agent=agent, resources=resources, held_by=e.body.get("heldBy"))
                return {"held": e.body}
            raise
        self._note("claim", agent=agent, resources=resources, write=write, made_stale=[s["agent"] for s in out["stale"]])
        return out

    def state(self, agent: str, resources: list[str]) -> dict:
        return self._run("POST", "/claim/state", {"agent": agent, "resources": resources})

    def release(self, agent: str, resources: list[str]) -> None:
        self._run("POST", "/release", {"agent": agent, "resources": resources})
        self._note("release", agent=agent, resources=resources)

    # -- messages -------------------------------------------------------------------------------------------------------
    def send(self, sender: str, to: str, text: str, importance: str = "normal", reply_to: str = "", section: str = "") -> str:
        body = {"from": sender, "to": to, "text": text, "importance": importance, "replyTo": reply_to}
        if section:
            body["section"] = section
        out = self._run("POST", "/messages", body)
        self._note("message", sender=sender, to=to, chars=len(text))
        return out["id"]

    def inbox(self, agent: str) -> list[dict]:
        out = self._run("POST", "/inbox", {"agent": agent})
        if out["messages"]:
            self._note("delivered", agent=agent, n=len(out["messages"]))
        return out["messages"]

    # -- decisions for people -------------------------------------------------------------------------------------------
    def card(self, agent: str, resource: str, title: str, detail: str, options: list[dict], between: list[str],
             positions: dict[str, str], card_id: str = "", at: str = "") -> dict:
        body = {"agent": agent, "resource": resource, "title": title, "detail": detail, "options": options,
                "between": between, "positions": positions, "at": at}
        if card_id:
            body["id"] = card_id
        out = self._run("POST", "/cards", body)
        self._note("card", agent=agent, resource=resource, created=out["created"])
        return out["card"]

    def cards(self, open_only: bool = False) -> list[dict]:
        return self.edip._call("GET", "/agents/cards", self.edip.k.serve_key, params={"open": "1"} if open_only else None)["cards"]

    def resolve(self, card_id: str, resolution: str, note: str = "", by: str = "") -> dict:
        out = self._run("POST", f"/cards/{card_id}/resolve", {"resolution": resolution, "note": note, "by": by})
        self._note("resolve", card=card_id, resolution=resolution)
        return out["card"]

    def signals(self) -> list[dict]:
        out = self.edip._call("GET", "/agents/signals", self.edip.k.serve_key, params={"since": str(self.cursor)})
        self.cursor = out["cursor"]
        return out["signals"]

    # -- facts: the shared memory in sentences ----------------------------------------------------------------------------
    def add_facts(self, agent: str, facts: list[dict]) -> list[dict]:
        out = self._run("POST", "/facts", {"agent": agent, "facts": facts}, key=self.edip.k.ingest_key)
        self._note("facts", agent=agent, n=len(facts))
        return out["facts"]

    def facts(self, **params: Any) -> list[dict]:
        return self.edip._call("GET", "/agents/facts", self.edip.k.serve_key,
                               params={k: str(v) for k, v in params.items() if v not in (None, "")})["facts"]

    def correct(self, agent: str, fact: str, correction: str, why: str, at: str = "") -> dict:
        out = self._run("POST", "/facts/correct", {"agent": agent, "fact": fact, "correction": correction, "why": why, "at": at},
                        key=self.edip.k.ingest_key)
        self._note("correct", agent=agent, ok=out.get("ok"))
        return out
