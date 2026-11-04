# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Replay recorded feeds into the memory in time order, as if they were arriving live.

A site registers its streams (table rows with a time), its documents (each with the time it becomes known) and its
checkpoints (moments when the watcher or the agent acts). `run()` walks the clock forward: before anything happens at
time T, every table row up to T has been appended, so whatever is asked at T sees exactly the past and nothing after.

Tables are created by ingesting their header with the first rows (which replaces any earlier copy of the same name), then
grow by append. Documents are ingested under stable names, so a rerun replaces rather than duplicates.
"""
from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .memory import EdipError, Memory

BATCH = 20000


@dataclass
class Stream:
    name: str
    header: list[str]
    rows: list[tuple[str, list[Any]]]          # (time, row), sorted by time
    tags: list[str] = field(default_factory=list)
    sent: int = 0
    created: bool = False


@dataclass
class Doc:
    at: str
    name: str
    text: str
    kind: str = "document"
    tags: list[str] = field(default_factory=list)


@dataclass
class Checkpoint:
    at: str
    label: str
    fn: Callable[[str], Any]


class Replay:
    def __init__(self, edip: Memory, log: Path):
        self.edip, self.log = edip, log
        self.streams: dict[str, Stream] = {}
        self.docs: list[Doc] = []
        self.checks: list[Checkpoint] = []
        self.stats = {"appends": 0, "rows": 0, "docs": 0, "checkpoints": 0, "errors": 0}
        log.parent.mkdir(parents=True, exist_ok=True)

    def stream(self, name: str, header: list[str], rows: list[dict], time_key: str, tags: list[str] | None = None) -> None:
        rs = sorted(((str(r[time_key]), [r.get(h, "") for h in header]) for r in rows), key=lambda x: x[0])
        self.streams[name] = Stream(name, header, rs, tags or [])

    def doc(self, at: str, name: str, text: str, kind: str = "document", tags: list[str] | None = None) -> None:
        self.docs.append(Doc(at, name, text, kind, tags or []))

    def checkpoint(self, at: str, label: str, fn: Callable[[str], Any]) -> None:
        self.checks.append(Checkpoint(at, label, fn))

    def _note(self, **kw: Any) -> None:
        with self.log.open("a") as f:
            f.write(json.dumps({"t": time.strftime("%H:%M:%S"), **kw}, default=str) + "\n")

    def _flush(self, until: str) -> None:
        for s in self.streams.values():
            k = s.sent
            while k < len(s.rows) and s.rows[k][0] <= until:
                k += 1
            if k == s.sent:
                continue
            batch = [r for _, r in s.rows[s.sent:k]]
            for i in range(0, len(batch), BATCH):
                part = batch[i:i + BATCH]
                try:
                    if not s.created:
                        buf = io.StringIO()
                        w = csv.writer(buf)
                        w.writerow(s.header)
                        w.writerows(part)
                        self.edip.ingest(s.name, buf.getvalue(), kind="table", tags=s.tags)
                        s.created = True
                    else:
                        self.edip.append(s.name, part)
                    self.stats["appends"] += 1
                    self.stats["rows"] += len(part)
                except EdipError as e:
                    self.stats["errors"] += 1
                    self._note(error="table", table=s.name, status=e.status, body=str(e.body)[:300])
            s.sent = k

    def run(self, until: str | None = None, step: str = "day") -> dict:
        events: list[tuple[str, int, Any]] = [(d.at, 0, d) for d in self.docs] + [(c.at, 1, c) for c in self.checks]
        # A flush at the end of every day keeps the tables current even when nothing else happens that day.
        days = sorted({r[0][:10] for s in self.streams.values() for r in s.rows})
        events += [(f"{d} 23:59", 2, None) for d in days]
        events.sort(key=lambda e: (e[0], e[1]))
        for at, _, ev in events:
            if until and at > until:
                break
            self._flush(at)
            if isinstance(ev, Doc):
                try:
                    self.edip.ingest(ev.name, ev.text, kind=ev.kind, tags=ev.tags)
                    self.stats["docs"] += 1
                except EdipError as e:
                    self.stats["errors"] += 1
                    self._note(error="doc", name=ev.name, status=e.status, body=str(e.body)[:300])
            elif isinstance(ev, Checkpoint):
                try:
                    out = ev.fn(at)
                    self.stats["checkpoints"] += 1
                    self._note(checkpoint=ev.label, at=at, out=out)
                except Exception as e:  # noqa: BLE001 - a failed check is recorded, the replay goes on
                    self.stats["errors"] += 1
                    self._note(error="checkpoint", label=ev.label, at=at, detail=repr(e)[:500])
        self._flush(until or "9999")
        return self.stats
