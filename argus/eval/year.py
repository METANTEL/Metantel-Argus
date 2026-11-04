# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""A year of the port, asked at the year's end: questions whose evidence is spread over 231,417 vessel events (about
8.8M tokens as text, ten times Muse Spark's context window), with answers computed from the compiled data.

Arms, all on the same model (Muse Spark Open on Baseten):
- `argus`: the memory as tools (search, tables, exact plans), about 20K tokens a question.
- `reports`: every daily report of the year pasted into the prompt (the whole history at the daily level).
- `context`: the most recent vessel events that fit in the context window, raw (23,000 events, 23 Nov to 31 Dec,
  about 874K tokens): what a long context holds when the raw record is poured into it.

Most questions reach back months; the last four are about December, inside the context arm's window, as controls.
Gold never comes from a model. Dates are asked for as YYYY-MM-DD.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter, defaultdict
from typing import Any

from .qa import Q, found

MONTHS = {2: "February", 5: "May", 8: "August", 10: "October", 12: "December"}


def questions(status: list[dict], events: list[dict]) -> list[Q]:
    rnd = random.Random(2024)
    ent = [e for e in events if e["event"] == "entered_bay"]
    anc = [e for e in events if e["event"] == "anchored"]
    by_v: dict[int, list[dict]] = defaultdict(list)
    for e in ent:
        by_v[e["mmsi"]].append(e)
    names = {e["mmsi"]: e["vessel"] for e in events if e["vessel"]}
    spread = [m for m, es in by_v.items() if m in names and len({e["time"][:7] for e in es}) >= 4 and 6 <= len(es) <= 30]
    spread.sort()
    picks = rnd.sample(spread, 6)
    qs: list[Q] = []
    for i, m in enumerate(picks[:3]):
        qs.append(Q(f"y{len(qs) + 1}", f"In 2024, how many times did the {by_v[m][0]['type']} {names[m]} (MMSI {m}) enter Galveston Bay "
                    f"through Bolivar Roads?", [len(by_v[m])]))
        n_anc = sum(1 for e in anc if e["mmsi"] == m)
        qs.append(Q(f"y{len(qs) + 1}", f"In 2024, how many times did {names[m]} (MMSI {m}) drop anchor in the area?", [n_anc]))
    for mo in (2, 5, 8, 10):
        tank = {e["mmsi"] for e in ent if e["type"] == "tanker" and int(e["time"][5:7]) == mo}
        qs.append(Q(f"y{len(qs) + 1}", f"How many different tankers entered Galveston Bay in {MONTHS[mo]} 2024?", [len(tank)]))
    st = {r["time"]: r for r in status}
    hazy = [(r, col, name) for r in status for col, name in (("vis_galveston_mi", "Galveston"), ("vis_baytown_mi", "Baytown"))
            if r[col] not in ("", None) and 0.5 < float(r[col]) < 5 and r["time"][:7] < "2024-11"]
    for r, col, name in rnd.sample(hazy, 2):
        qs.append(Q(f"y{len(qs) + 1}", f"What was the visibility at {name} at {r['time'][11:16]} UTC on {r['time'][:10]}, in miles?",
                    [float(r[col])]))
    for day in ("2024-03-12", "2024-07-09"):
        r = st[f"{day} 15:00"]
        qs.append(Q(f"y{len(qs) + 1}", f"How many deep-draft ships were waiting at the offshore anchorage at 15:00 UTC on {day}?",
                    [r["waiting_outside"]]))
    for m in picks[3:6]:
        es = sorted(by_v[m], key=lambda e: e["time"])
        mid = es[len(es) // 2]["time"]
        before = [e for e in es if e["time"] < mid]
        if before:
            qs.append(Q(f"y{len(qs) + 1}", f"Before {mid[:10]}, when did {names[m]} (MMSI {m}) last enter Galveston Bay? Give the "
                        f"date as YYYY-MM-DD.", [before[-1]["time"][:10]], "text"))
    # Controls inside the context arm's window (December).
    dec = [e for e in ent if e["time"] >= "2024-12-01"]
    dec_v = Counter(e["mmsi"] for e in dec)
    m = sorted((v for v, n in dec_v.items() if n >= 2 and v in names), key=lambda v: (-dec_v[v], v))[0]
    qs.append(Q(f"y{len(qs) + 1}", f"Between 2024-12-01 and 2024-12-31, how many times did {names[m]} (MMSI {m}) enter Galveston Bay?",
                [dec_v[m]]))
    tank = {e["mmsi"] for e in dec if e["type"] == "tanker"}
    qs.append(Q(f"y{len(qs) + 1}", "How many different tankers entered Galveston Bay in December 2024?", [len(tank)]))
    r = st["2024-12-15 12:00"]
    qs.append(Q(f"y{len(qs) + 1}", "How many deep-draft ships were waiting at the offshore anchorage at 12:00 UTC on 2024-12-15?",
                [r["waiting_outside"]]))
    last = max((e for e in dec if e["mmsi"] == m), key=lambda e: e["time"])
    qs.append(Q(f"y{len(qs) + 1}", f"When did {names[m]} (MMSI {m}) last enter Galveston Bay in 2024? Give the date as YYYY-MM-DD.",
                [last["time"][:10]], "text"))
    return qs


FINAL = re.compile(r"FINAL:\s*(.+)", re.I)


def final(text: str) -> str | None:
    """The answer the arm committed to: its FINAL line (pasted arms) or its `final` field (Argus). Scoring reads only
    this, so a long answer that mentions many numbers is not right by accident."""
    m = FINAL.findall(text or "")
    if m:
        return m[-1].strip()
    try:
        v = json.loads(text).get("final")
        return str(v) if v not in (None, "") else None
    except (ValueError, AttributeError):
        return None


PROVIDER = {"provider": "baseten", "model": None}


def ask_pasted(models, question: str, now: str, label: str, text: str) -> str:
    prompt = (f"It is {now} UTC. Here is {label}:\n\n{text}\n\nAnswer the question from this record. Give exact figures and "
              f"dates as YYYY-MM-DD. If the record does not say, say so. End with one line: FINAL: <the answer only, a number "
              f"or a date, or 'unknown'>\n\nQuestion: {question}")
    return models.text(prompt, provider=PROVIDER["provider"], model=PROVIDER["model"], effort="low", max_tokens=6000)


def run(qs: list[Q], agent, models, now: str, reports: str, context: str, arms=("argus", "reports", "context")) -> dict:
    rows = []
    for q in qs:
        row: dict[str, Any] = {"id": q.id, "question": q.text, "gold": q.gold}
        for arm in arms:
            try:
                if arm == "argus":
                    r = agent.run("answer", q.text + " Give dates as YYYY-MM-DD.", now, audience="manager",
                                  extra_json='"final": "the answer only: a number or a date as YYYY-MM-DD, or unknown"')
                    text = json.dumps(r.answer)
                    row["argus_tools"] = [t["tool"] for t in r.trace]
                elif arm == "reports":
                    text = ask_pasted(models, q.text, now, "every daily report of the port for 2024", reports)
                else:
                    text = ask_pasted(models, q.text, now, "the port's most recent vessel events (CSV: time, mmsi, vessel, "
                                      "type, event, zone, sog, note)", context)
            except Exception as e:  # noqa: BLE001 - a failed call scores as wrong, with the reason kept
                text = f"ERROR {e}"
            f = final(text)
            row[arm] = f is not None and found(f, q)
            row[f"{arm}_final"] = f
            row[f"{arm}_answer"] = text[:1500]
        rows.append(row)
        print(q.id, {a: row[a] for a in arms}, q.gold, flush=True)
    return {"n": len(rows), "correct": {a: sum(r[a] for r in rows) for a in arms}, "rows": rows}
