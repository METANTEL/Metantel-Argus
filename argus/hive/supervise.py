# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Supervisors: hive members that watch over a model or a system and keep what it puts into memory honest.

A model is good at one thing and blind to the site. SAM 3.1 boxes what it is asked about, sixteen a frame at most, and
cannot tell a forklift being driven from one parked by a wall while people walk past it. A sensor feed can freeze on one
value for hours while the machine runs. A compiler turns whatever it is given into rows. None of them knows it is wrong.

A supervisor holds the output of the system it watches to four invariants, the same whatever the system (each
supervisor runs the ones that apply to its system):

- **limit**: the output stopped at a known cap (sixteen objects a frame, a page of rows, a tool budget);
- **disagrees**: an independent look disagrees (the supervisor's own reading of a frame, another camera, the memory's
  expectations);
- **implausible**: the physics is wrong (a "moving" vehicle that never leaves a two-metre circle, a pressure that does not
  change for hours while the compressor cycles);
- **missing**: something the site's knowledge says exists is not in the output (a robot the people said runs here).

They are the functions `at_limit`, `disagrees`, `implausible` and `missing` below. Two supervisors ship: the camera
supervisor (SAM 3.1 on a hall's cameras) runs `at_limit` and `implausible`, and the factory example adds `missing`; the
sensor supervisor (a logger's channels) runs `implausible`. `disagrees` is there for a system with an independent reading;
no shipped supervisor calls it yet.

Checks are cheap and run on everything. The supervisor's judgement (Muse Spark, with the site's charter, the hive's
knowledge and the evidence, images included) is spent only on what a check flags, and it chooses among the same
remedies every supervisor has: **split** the work and ask again, **reprompt** in the site's own words, **rederive** the
result robustly, **correct** the memory, or **ask people**. A correction claims the memory it changes, so every agent
holding a copy of it is told its copy is stale and re-reads before it acts again: a decision built on the wrong picture
is revisited by the agent that made it. Every issue, judgement and remedy is kept in the supervisor's log.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .mind import Member

REMEDIES = {
    "split": "ask the system again on smaller parts of the input (tiles of a view, shorter windows, pages)",
    "reprompt": "ask the system again in other words, the site's own (give the phrases)",
    "rederive": "recompute the result from the raw output with a method robust to this failure",
    "correct": "change what the memory holds, and tell every agent that relied on it",
    "ask_people": "the evidence cannot settle it: put it to people as a decision",
    "accept": "the output is right; record why the check fired",
}


@dataclass
class Issue:
    check: str                    # limit | disagrees | implausible | missing
    subject: str                  # the camera, track, sensor or table it is about
    evidence: dict
    images: list[str] = field(default_factory=list)
    verdict: dict = field(default_factory=dict)
    remedy: str = ""
    result: dict = field(default_factory=dict)


# -- the four invariants, for any system's output ------------------------------------------------------------------

def at_limit(counts: dict[Any, int], limit: int, subject: str, share: float = 0.2, **evidence: Any) -> Issue | None:
    """The output stopped at the system's cap in at least `share` of its units (frames, pages, calls)."""
    hit = sum(n >= limit for n in counts.values())
    if not counts or hit < share * len(counts):
        return None
    return Issue("limit", subject, {"units": len(counts), "units_at_limit": hit, "limit": limit, **evidence})


def disagrees(system: float, independent: float, subject: str, tolerance: float = 0.7, **evidence: Any) -> Issue | None:
    """An independent look finds clearly more (or less) than the system."""
    lo, hi = sorted((system, independent))
    if hi <= 0 or lo / hi >= tolerance:
        return None
    return Issue("disagrees", subject, {"system": system, "independent": independent, **evidence})


def implausible(subject: str, why: str, **evidence: Any) -> Issue:
    return Issue("implausible", subject, {"why": why, **evidence})


def missing(expected: set[str], seen: set[str], subject: str, **evidence: Any) -> Issue | None:
    gone = sorted(expected - seen)
    return Issue("missing", subject, {"expected": sorted(expected), "missing": gone, **evidence}) if gone else None


@dataclass
class Supervisor(Member):
    """The loop every supervisor shares: check, judge what was flagged, choose a remedy, apply it, tell the hive."""
    watches: str = ""                                       # what it supervises, in words
    log: list[Issue] = field(default_factory=list)
    out_dir: Path = Path(".")
    remedies: dict[str, Callable[[Issue], dict]] = field(default_factory=dict)

    def judge(self, issue: Issue, what: str, knowledge: list[str], options: list[str], max_tokens: int = 3000) -> dict:
        """The supervisor's own reading of a flagged issue, with the evidence and images; it chooses the remedy."""
        menu = "\n".join(f"- {k}: {REMEDIES[k]}" for k in options)
        prompt = (f"You supervise {self.watches} for the hive. A check flagged an issue.\n\nCHECK: {issue.check} on "
                  f"{issue.subject}\nEVIDENCE: {json.dumps(issue.evidence)}\nWHAT THE IMAGES SHOW: {what}\n\nWHAT THE SITE "
                  "KNOWS:\n" + "\n".join(f"- {k}" for k in knowledge) + f"\n\nREMEDIES YOU CAN CHOOSE:\n{menu}\n\nSay what is "
                  "true, then choose one remedy and give what it needs. Reply with JSON only: {\"finding\": \"what is true, "
                  "one or two sentences\", \"remedy\": \"" + "|".join(options) + "\", \"params\": {}, \"lesson\": \"what every "
                  "agent should know from now on, one sentence, or empty\"}")
        verdict = self.ask_json(prompt, images=[Path(p) for p in issue.images], max_tokens=max_tokens)
        issue.verdict = verdict
        return verdict

    def apply(self, issue: Issue, remedy: str) -> dict:
        issue.remedy = remedy
        fn = self.remedies.get(remedy)
        issue.result = fn(issue) if fn else {}
        self.log.append(issue)
        return issue.result

    def tell(self, text: str, kind: str, subjects: list[str], at: str) -> None:
        """What the hive should know now, as a fact every agent reads."""
        self.link.add_facts(self.agent, [{"text": text, "kind": kind, "subjects": [self.section, *subjects], "since": at}])

    def correct_memory(self, resource: str, version: str, why: str) -> list[str]:
        """Claim the memory being changed: every agent holding a copy of it is told the copy is stale. [those agents]"""
        got = self.change(resource, version, why)
        self.done(resource)
        return [s["agent"] for s in got.get("stale", [])]

    def save(self) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / "supervision.json"
        out.write_text(json.dumps({"watches": self.watches, "agent": self.agent, "issues": [vars(i) for i in self.log]},
                                  indent=1, default=str))
        return out


# -- a machine's sensor log ----------------------------------------------------------------------------------------

def frozen(rows: list[dict], keys: list[str], against: str, min_rows: int) -> list[tuple[int, int]]:
    """Index ranges where every one of `keys` repeats its value exactly while `against` keeps changing: a logger that
    stalled on its analog channels while another channel kept reporting."""
    out, start = [], None
    for i in range(1, len(rows) + 1):
        same = i < len(rows) and all(abs(rows[i][k] - rows[i - 1][k]) < 1e-9 for k in keys)
        if same and start is None:
            start = i - 1
        if not same and start is not None:
            span = rows[start:i]
            if i - start >= min_rows and max(r[against] for r in span) - min(r[against] for r in span) > 1.0:
                out.append((start, i - 1))
            start = None
    return out


@dataclass
class SensorSupervisor(Supervisor):
    """Watches over a machine's sensor log and what the watcher reads from it."""

    def frozen_check(self, rows: list[dict], keys: list[str], against: str, min_rows: int = 24) -> list[Issue]:
        issues = []
        for a, b in frozen(rows, keys, against, min_rows):
            r0, r1 = rows[a], rows[b]
            issues.append(implausible(
                f"{r0['time']} to {r1['time']}", f"{', '.join(keys)} did not change for {(b - a + 1) * 5 / 60:.1f} h while "
                f"{against} ranged {min(r[against] for r in rows[a:b + 1]):.0f}–{max(r[against] for r in rows[a:b + 1]):.0f}",
                start=r0["time"], end=r1["time"], hours=round((b - a + 1) * 5 / 60, 1), frozen={k: r0[k] for k in keys},
                before=[{k: rows[i][k] for k in ("time", *keys, against)} for i in range(max(0, a - 3), a)],
                during=[{k: rows[i][k] for k in ("time", *keys, against)} for i in range(a, min(b + 1, a + 4))],
                after=[{k: rows[i][k] for k in ("time", *keys, against)} for i in range(b + 1, min(len(rows), b + 4))]))
        return issues
