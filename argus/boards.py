# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Draft a board from a sentence: Muse Spark writes the board, the memory checks it by running it.

A board is the workflow format Artel's Breadboard draws and the Managed Memory Harness runs. Argus gives the model the
parts, the space's tables and their columns, and the request; the model returns a board; Argus runs it once, and if the
memory refuses it (a wrong column, a missing wire), the error goes back to the model for one repair.

    python -m argus.boards "Every morning, find ships that have gone quiet for more than 6 hours and warn the operators"
"""
from __future__ import annotations

import json
import sys

from .memory import Edip, EdipError
from .models import Models, parse_json

PARTS = """Parts (type: params → outputs):
- source: {codes: [], kinds: []} → items. Every item in the space, or only items tagged with codes.
- find: {query, breadth: "auto", codes: []} → items. Items matching a plain-language question.
- table: {plan: {op, table, ...}, limit} → items. An exact table plan; each row becomes an item. op is one of latest
  (where each entity stands: entity_column, as_of, older_than_hours), rows (where, order_by, limit), trace (entity_column,
  entity), durations (entity_column, start, end), gaps (entity_column, min_hours), aggregate (group_by, bucket, metrics).
  where items are {column, op: eq|ne|gt|gte|lt|lte|in|contains, value}; order_by items are {by, desc}.
- check: {question, threshold: 0.7} → yes, no. A yes/no question asked of every item.
- label: {question, options: [..]} → one output per option.
- score: {question, levels: [low..high], min: index} → high, low.
- filter: {any: [], all: [], none: [], kinds: [], located: false} → items, rest. By tag codes, no model.
- combine: {} → items. limit: {n} → items.
- summarize: {instruction} → text. output: {name}. alert: {name}.
- agent: {mode: answer|warn|plan|brief, audience: operator|supervisor|manager|executive, instruction, max_items}. Hands
  the items to the user's own agent, which writes the answer.
A board is {"kind": "graph", "nodes": [{id, type, title, params, position: {x, y}}], "edges": [{source, sourceHandle,
target, targetHandle: "items"}]}. sourceHandle is the output's name (items, yes, no, high, low, an option, rest)."""

ASK = """You design workflows ("boards") for an operations team. Write one board for the request below.

{parts}

The space's tables (name: columns with their roles):
{tables}

Rules: start from table, find or source; use table plans for anything about numbers, current state, silences or
durations; use check/score/label for judgement; end with an alert, an output or an agent part (an agent part when the
request asks for warnings, plans or briefings in words). Use only tables and columns listed above. Give each part a short
plain title. Lay parts out left to right (x += 320).

Request: {request}

Reply with the board as JSON only."""


def tables_text(edip: Edip) -> str:
    out = []
    for t in edip.tables().get("tables", []):
        cols = ", ".join(f"{c['name']} ({c.get('role')})" for c in t.get("columns", []))
        out.append(f"- {t['artifact']} ({t.get('rows')} rows): {cols}")
    return "\n".join(out)


def draft(request: str, edip: Edip | None = None, models: Models | None = None, run: bool = True) -> dict:
    edip, models = edip or Edip(), models or Models()
    prompt = ASK.format(parts=PARTS, tables=tables_text(edip), request=request)
    board = models.json(prompt, effort="medium", max_tokens=8000)
    if not run:
        return {"board": board}
    try:
        out = edip.flow_graph(board, {"_board": request[:100]})
        return {"board": board, "run": out, "repaired": False}
    except EdipError as e:
        fixed = models.json(prompt + f"\n\nYour board was refused: {str(e.body)[:600]}\nThe board was:\n{json.dumps(board)}\n"
                            "Fix it and reply with the whole board as JSON only.", effort="medium", max_tokens=8000)
        out = edip.flow_graph(fixed, {"_board": request[:100]})
        return {"board": fixed, "run": out, "repaired": True, "first_error": str(e.body)[:600]}


if __name__ == "__main__":
    r = draft(" ".join(sys.argv[1:]))
    print(json.dumps(r["board"], indent=1))
    run = r.get("run") or {}
    print("\nRan:", {k: v.get("out") for k, v in (run.get("nodes") or {}).items()}, "results:",
          [{k: x.get(k) for k in ("name", "kind", "count", "task")} for x in run.get("results", [])], "repaired:", r.get("repaired"))
