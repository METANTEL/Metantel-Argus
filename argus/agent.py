# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The reasoning layer: a frontier model that answers, warns, plans and briefs from what the memory serves.

The model never invents a number. Every figure comes from a tool: the memory's search and exact queries, or the harness's
own analog forecast over past episodes. The model chooses what to ask, reads what comes back, and writes for
the person who will act on it.

Modes:
- `answer`: a question in plain words.
- `warn`: something just happened; say what, why it matters now, what to do, how sure.
- `plan`: options with trade-offs, a recommendation, its expected effect and what it rests on.
- `brief`: a shift or daily briefing for an audience (operator, supervisor, manager, executive).
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from .memory import Edip, EdipError, Memory
from .models import Models

AUDIENCES = {
    "operator": "a field operator (pilot, crane or forklift operator, technician) who needs the next action now: two to four "
                "short lines, the action first, no background",
    "supervisor": "a shift supervisor who allocates people and equipment for the next hours: what changed, what to do this "
                  "shift, who does it",
    "manager": "an operations manager planning the next days: the situation, the forecast with its range, the options and "
               "their trade-offs, the decision needed",
    "executive": "an executive: the business impact in two or three sentences, the trend, and the one decision that needs "
                 "them, if any",
}

TOOLS = [
    {"type": "function", "function": {
        "name": "search", "description": "Search the site's memory (reports, episode write-ups, records) with a full sentence. "
        "Returns the best passages with the item they came from.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer", "default": 8},
            "codes": {"type": "array", "items": {"type": "string"}, "description": "only items with all these tag codes"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "tables", "description": "List the site's tables and their columns (names, kinds, roles). Read before a plan.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "table_query", "description": "Run an exact table plan. Use for every number: counts, latest states, "
        "durations, gaps, traces. Plan grammar: op (aggregate|rows|latest|trace|durations|gaps|around|entities|linked), "
        "table, where [{column, op, value}], time {from, to}, group_by, bucket (hour|day|week|month), "
        "metrics [{fn: count|count_distinct|sum|avg|min|max, column, as}], order_by [{by, desc}], limit, columns, "
        "entity_column, entity, as_of, older_than_hours, start/end (durations), min_hours (gaps).",
        "parameters": {"type": "object", "properties": {"plan": {"type": "object"}}, "required": ["plan"]}}},
    {"type": "function", "function": {
        "name": "similar_episodes", "description": "Past episodes like the current one (from the site's episode table, only "
        "those that ended before now), with their outcomes and the spread of those outcomes. Use for any forecast.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "description": "episode kind, e.g. 'halt' or 'failure'"},
            "features": {"type": "object", "description": "what is known so far, e.g. {\"hours_so_far\": 3, \"queue_now\": 14, "
                                                          "\"min_visibility_mi\": 0.25}"}},
            "required": ["kind", "features"]}}},
]

FACTS_TOOL = {"type": "function", "function": {
    "name": "memory_facts", "description": "The shared memory's facts: one sentence each, written by other agents and by "
    "people, newest first. A fact someone corrected shows only its correction. Use it for what the hive has decided, "
    "learned or corrected (plans, causes, lessons).",
    "parameters": {"type": "object", "properties": {
        "q": {"type": "string", "description": "words the fact contains"},
        "subject": {"type": "string", "description": "a subject, e.g. port/channel, port/weather, site-knowledge"}}}}}

SYSTEM = """You are Argus, the operational intelligence layer for {site}. You help the people who run it see what is happening, what is likely next, and what to do.

The time now is {now} (UTC). Only facts dated at or before now exist; never use or guess anything later.

Rules:
- Every number you state must come from a tool result in this conversation. If you could not get a number, say so.
- Use table_query for counts, current states, durations and silences; use search to find reports and explanations; use similar_episodes before any forecast.
- Cite your sources: item names from search hits, and the table and plan for table results.
- Prefer few, decisive tool calls. You have at most {max_calls} tool calls.
- Write plain language for {audience_desc}.
- Say how sure you are and why (how many past episodes, how close they were).

When you are done, reply with JSON only:
{{"level": "info|watch|act_now", "headline": "one line", "body": "markdown for the reader", "actions": [{{"action": "...", "who": "role", "when": "...", "expected_effect": "...", "rests_on": "..."}}], "forecasts": [{{"what": "...", "value": number or null, "low": number or null, "high": number or null, "unit": "...", "basis": "..."}}], "confidence": "low|medium|high", "citations": ["..."]}}
"""

MODE_ASK = {
    "answer": "Answer this question: {text}",
    "warn": "Something has just happened that may need action. Assess it and warn the right people. Situation: {text}",
    "plan": "Make a plan. Give two or three options with their trade-offs, recommend one, and forecast its effect. Goal: {text}",
    "brief": "Write the briefing. Focus: {text}",
}


@dataclass
class Episodes:
    """The harness's analog forecaster: reads the episode table from the memory and compares like with like."""
    edip: Memory
    tables: dict[str, str]                      # kind -> table name
    features: dict[str, list[str]]              # kind -> feature columns, in the order they matter
    outcomes: dict[str, list[str]]              # kind -> outcome columns
    time_column: str = "start"

    def similar(self, kind: str, now: str, known: dict[str, Any], k: int = 5) -> dict:
        table = self.tables.get(kind)
        if not table:
            return {"error": f"no episodes of kind {kind!r}; kinds: {sorted(self.tables)}"}
        plan = {"op": "rows", "table": table, "time": {"to": now}, "limit": 200}
        try:
            res = self.edip.query(plan=plan, budget=40000)
        except EdipError as e:
            if e.status == 404:          # no episode has played out yet, so the table does not exist
                return {"episodes": [], "note": "no finished episodes before now", "plan": plan}
            raise
        result = res.get("result") or {}
        cols = result.get("columns") or []
        rows = [dict(zip(cols, r)) if isinstance(r, list) else r for r in result.get("rows") or []]
        # An episode counts once it has ended and its outcome is known (a recovery is learned after the end).
        past = [r for r in rows if str(r.get("end") or "") and str(r.get("end"))[:16] <= now
                and str(r.get("known_at") or r.get("end"))[:16] <= now]
        if not past:
            return {"episodes": [], "note": "no finished episodes before now", "plan": plan}

        def num(v: Any) -> float | None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        feats = [f for f in self.features[kind] if num(known.get(f)) is not None]
        spans = {f: (max(num(r.get(f)) or 0 for r in past) - min(num(r.get(f)) or 0 for r in past)) or 1 for f in feats}

        def dist(r: dict) -> float:
            return sum(abs((num(r.get(f)) or 0) - num(known[f])) / spans[f] for f in feats) / max(len(feats), 1)

        ranked = sorted(past, key=dist)[:k]
        spread = {}
        for o in self.outcomes[kind]:
            vals = [num(r.get(o)) for r in ranked if num(r.get(o)) is not None]
            if vals:
                spread[o] = {"median": round(statistics.median(vals), 2), "mean": round(statistics.fmean(vals), 2),
                             "low": min(vals), "high": max(vals), "n": len(vals)}
        return {"episodes": [{**{c: r.get(c) for c in (["start", "end"] + self.features[kind] + self.outcomes[kind] + ["cause"]) if c in r},
                              "similarity": round(1 - dist(r), 3)} for r in ranked],
                "outcome_spread": spread, "compared_on": feats, "finished_before_now": len(past), "table": table}


@dataclass
class Result:
    mode: str
    audience: str
    question: str
    answer: dict
    trace: list[dict] = field(default_factory=list)
    usd: float = 0.0
    seconds: float = 0.0


def bound(plan: dict, now: str, known_at: dict[str, str]) -> dict:
    """The same plan, unable to see past `now`: its time window ends at now, `latest` is taken as of now, and a table
    whose rows hold outcomes learned later (an episode's recovery) keeps only rows known by now. Nested `then` plans too."""
    p = dict(plan)
    t = dict(p.get("time") or {})
    if not t.get("to") or str(t["to"]) > now:
        t["to"] = now
    p["time"] = t
    if p.get("op") == "latest" and (not p.get("as_of") or str(p["as_of"]) > now):
        p["as_of"] = now
    col = known_at.get(str(p.get("table") or ""))
    if col:
        p["where"] = list(p.get("where") or []) + [{"column": col, "op": "lte", "value": now}]
    if isinstance(p.get("then"), dict):
        p["then"] = bound(p["then"], now, known_at)
    return p


def stamp_of(tags: list[str]) -> str:
    """When an item became known, from its `t=YYYY-MM-DD HH:MM` tag ('' if it has none)."""
    return next((x[2:].replace("T", " ") for x in tags or [] if x.startswith("t=")), "")


class Agent:
    def __init__(self, site: str, edip: Memory | None = None, models: Models | None = None, episodes: Episodes | None = None,
                 model: str | None = None, effort: str = "low", max_calls: int = 8, provider: str = "meta",
                 bounded: bool = False, known_at: dict[str, str] | None = None, site_tag: str = "",
                 facts: Callable[[dict, str], list[dict]] | None = None,
                 extra: dict[str, tuple[dict, Callable[[dict, str], Any]]] | None = None):
        self.site, self.edip, self.models = site, edip or Edip(), models or Models()
        self.episodes, self.model, self.effort, self.max_calls = episodes, model, effort, max_calls
        # `bounded`: the memory holds the whole record, so every tool keeps the agent at `now` (plans are bounded; search
        # hits must carry a `t=` stamp at or before now and the site's tag). Without it, the replay guarantees the same
        # by never having put the future in.
        self.provider, self.bounded, self.known_at, self.site_tag = provider, bounded, known_at or {}, site_tag
        # `facts(args, now)`: the shared memory's facts as this agent may see them at `now` (the hive filters by time and run).
        self.facts = facts
        # `extra`: tools the harness computes itself (a what-if over recorded tracks), as {name: (schema, fn(args, now))}.
        self.extra = extra or {}
        self._tables: dict | None = None

    def _tool(self, name: str, args: dict, now: str) -> Any:
        try:
            if name == "search":
                limit = min(int(args.get("limit") or 8), 15)
                out = self.edip.search(args["query"], limit=limit * 3 if self.bounded else limit, codes=args.get("codes"))
                hits = out.get("hits", [])
                if self.bounded:
                    hits = [h for h in hits if (self.site_tag in (h.get("tags") or []))
                            and stamp_of(h.get("tags")) and stamp_of(h.get("tags")) <= now][:limit]
                return {"hits": [{"item": h["item"], "record": h.get("record"), "text": (h.get("text") or "")[:700],
                                  "tags": [t for t in h.get("tags") or [] if t.startswith("code=")]} for h in hits]}
            if name == "tables":
                if self._tables is None:
                    self._tables = self.edip.tables()
                return {"tables": [{"table": t["artifact"], "rows": t.get("rows"),
                                    "columns": [(c["name"], c.get("kind"), c.get("role")) for c in t.get("columns", [])]}
                                   for t in self._tables.get("tables", [])]}
            if name == "table_query":
                plan = bound(args["plan"], now, self.known_at) if self.bounded else args["plan"]
                out = self.edip.query(plan=plan, budget=8000)
                return {"text": (out.get("text") or "")[:8000], "repairs": out.get("repairs")}
            if name in self.extra:
                return self.extra[name][1](args, now)
            if name == "memory_facts":
                if not self.facts:
                    return {"error": "no shared facts for this agent"}
                return {"facts": [{"text": f["text"], "by": f["author"], "since": f["since"], "corrects": f.get("corrects", "")}
                                  for f in self.facts(args, now)[:15]]}
            if name == "similar_episodes":
                if not self.episodes:
                    return {"error": "no episode memory for this site"}
                return self.episodes.similar(args["kind"], now, args.get("features") or {})
            return {"error": f"unknown tool {name}"}
        except EdipError as e:
            return {"error": f"{e.status}: {str(e.body)[:400]}"}
        except (KeyError, TypeError, ValueError) as e:
            return {"error": f"bad arguments: {e}"}

    def run(self, mode: str, text: str, now: str, audience: str = "manager", context: str = "", preamble: str = "",
            extra_json: str = "", on_step: Callable[[dict], None] | None = None) -> Result:
        """`preamble`: who this agent is in a hive (its charter and role), ahead of the rules. `extra_json`: fields the
        caller needs in the final JSON besides the standard ones, described in words. `on_step`: called with each tool
        call as it finishes (the console shows them as they happen)."""
        import time
        from .models import ledger
        t0, usd0 = time.time(), ledger.usd
        sys = SYSTEM.format(site=self.site, now=now, max_calls=self.max_calls,
                            audience_desc=AUDIENCES.get(audience, AUDIENCES["manager"]))
        if preamble:
            sys = preamble + "\n\n" + sys
        if extra_json:
            sys += f"\nAlso include in that JSON: {extra_json}\n"
        user = MODE_ASK[mode].format(text=text) + (f"\n\nWhat the harness already knows:\n{context}" if context else "")
        # The instructions go in the developer role: Spark Contributor's prompt filter refused this system prompt together
        # with tools (HTTP 400, content_policy_violation) while accepting the same text as developer instructions.
        msgs: list[dict] = [{"role": "developer", "content": sys}, {"role": "user", "content": user}]
        trace: list[dict] = []
        calls = 0
        while True:
            tools = TOOLS + ([FACTS_TOOL] if self.facts else []) + [schema for schema, _ in self.extra.values()]
            out = self.models.chat(msgs, model=self.model, provider=self.provider, tools=tools if calls < self.max_calls else None,
                                   effort=self.effort, max_tokens=9000)
            msg = out["choices"][0]["message"]
            tcs = msg.get("tool_calls") or []
            if not tcs:
                raw = msg.get("content") or ""
                try:
                    from .models import parse_json
                    ans = parse_json(raw)
                except (ValueError, json.JSONDecodeError):
                    ans = _salvage(raw)
                if extra_json and isinstance(ans, dict) and not isinstance(ans.get("plan"), dict) and "plan" in extra_json:
                    # The extra fields were asked for and are missing: one short call restates them from the answer.
                    try:
                        from .models import parse_json
                        fix = self.models.chat([{"role": "user", "content": f"From this answer, write only {extra_json}, as one JSON "
                                                 f"object with the key \"plan\". Answer:\n{raw[:6000]}"}],
                                               model=self.model, provider=self.provider, effort="low", max_tokens=1500)
                        got = parse_json(fix["choices"][0]["message"].get("content") or "")
                        if isinstance(got, dict) and isinstance(got.get("plan"), dict):
                            ans["plan"] = got["plan"]
                    except Exception:  # noqa: BLE001 - the answer stands without its plan; the caller sees it is missing
                        pass
                return Result(mode, audience, text, ans, trace, round(ledger.usd - usd0, 5), round(time.time() - t0, 1))
            msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tcs})
            for tc in tcs:
                calls += 1
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                res = self._tool(tc["function"]["name"], args, now) if calls <= self.max_calls else \
                    {"error": "tool budget spent; answer now"}
                trace.append({"tool": tc["function"]["name"], "args": args, "result": _short(res)})
                if on_step:
                    on_step(trace[-1])
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res, default=str)[:12000]})


def _salvage(raw: str) -> dict:
    """An answer whose JSON did not parse (usually cut off at the token limit): keep what can be read from it."""
    import re

    def field(name: str) -> str:
        m = re.search(rf'"{name}"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        if not m:
            return ""
        try:
            return json.loads(f'"{m.group(1)}"')
        except ValueError:
            return m.group(1)
    out = {"level": field("level"), "headline": field("headline"), "body": field("body") or raw, "actions": [],
           "forecasts": [], "confidence": field("confidence") or "low", "citations": [], "salvaged": True}
    plan = _object(raw, "plan")
    if plan is not None:
        out["plan"] = plan
    return out


def _object(raw: str, key: str) -> dict | None:
    """The JSON object under `key` in a reply whose whole JSON does not parse (brace-matched, strings respected)."""
    import re
    m = re.search(rf'"{key}"\s*:\s*\{{', raw)
    if not m:
        return None
    i, depth, in_str, esc = m.end() - 1, 0, False, False
    for j in range(i, len(raw)):
        ch = raw[j]
        if in_str:
            esc, in_str = (not esc and ch == "\\"), (in_str if esc or ch != '"' else False)
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[i:j + 1])
                except ValueError:
                    return None
    return None


def _short(v: Any, n: int = 600) -> Any:
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n] + "…"
