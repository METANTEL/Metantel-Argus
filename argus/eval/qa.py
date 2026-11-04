# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Questions a supervisor or manager would ask, with answers computed by code from the compiled data, asked three ways.

Arms (same model, same question):
- `argus`: the agent with the memory's tools (search, tables, exact plans, similar episodes).
- `window`: no tools; the most recent daily reports pasted into the prompt, the way a long context window would hold them.
- `full`: no tools; every daily report and record since the start pasted into the prompt (the whole history at the
  daily level, which only fits while the site is small).
- `none`: no tools and no context.

A question is answered correctly when its gold value appears in the answer: a number within 2% (or 0.05 absolute), a
date or time as written, or a name. Gold never comes from a model.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass
from typing import Any

from ..agent import Agent
from ..models import Models


@dataclass
class Q:
    id: str
    text: str
    gold: list[Any]                 # every value must appear
    kind: str = "number"            # number | text


def found(answer: str, q: Q) -> bool:
    a = answer.lower().replace(",", "")
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", a)]
    for g in q.gold:
        if isinstance(g, (int, float)):
            tol = max(abs(g) * 0.02, 0.05)
            if not any(abs(n - g) <= tol for n in nums):
                return False
        else:
            if str(g).lower() not in a:
                return False
    return True


def ask_window(models: Models, question: str, now: str, window: str) -> str:
    prompt = (f"It is {now} UTC. Here are the most recent daily reports:\n\n{window}\n\nAnswer the question from these "
              f"reports. Give the exact figures. If the reports do not say, say so.\n\nQuestion: {question}")
    return models.text(prompt, effort="low", max_tokens=3000)


def ask_none(models: Models, question: str, now: str) -> str:
    return models.text(f"It is {now} UTC. Answer the question with exact figures if you can; say if you cannot know.\n\n"
                       f"Question: {question}", effort="low", max_tokens=2000)


def run(qs: list[Q], agent: Agent, models: Models, now: str, window: str, full: str = "",
        arms=("argus", "window", "full", "none")) -> dict:
    rows = []
    for q in qs:
        row: dict[str, Any] = {"id": q.id, "question": q.text, "gold": q.gold}
        for arm in arms:
            try:
                if arm == "argus":
                    r = agent.run("answer", q.text, now, audience="manager")
                    text = json.dumps(r.answer)
                    row["argus_tools"] = [t["tool"] for t in r.trace]
                elif arm == "window":
                    text = ask_window(models, q.text, now, window)
                elif arm == "full":
                    text = ask_window(models, q.text, now, full)
                else:
                    text = ask_none(models, q.text, now)
            except Exception as e:  # noqa: BLE001 - a failed call scores as wrong, with the reason kept
                text = f"ERROR {e}"
            row[arm] = found(text, q)
            row[f"{arm}_answer"] = text[:1500]
        rows.append(row)
    score = {arm: sum(r[arm] for r in rows) for arm in arms}
    return {"n": len(rows), "correct": score, "rows": rows}


# ── question sets, computed from the compiled data ──────────────────────────────────────────────

def equipment_questions(daily: list[dict], fm: list[dict], episodes: list[dict], failures: list[dict]) -> list[Q]:
    by = {d["date"]: d for d in daily}
    april = [d for d in daily if d["date"].startswith("2020-04") and d["hours_recorded"] >= 6]
    top_apr = max(april, key=lambda d: d["duty_pct"])
    june = [d["duty_pct"] for d in daily if d["date"].startswith("2020-06") and d["hours_recorded"] >= 6]
    march_tp3 = min(r["tp3_min_bar"] for r in fm if r["time"].startswith("2020-03"))
    aug_oil = max(r["oil_temp_max_c"] for r in fm if r["time"].startswith("2020-08"))
    sev_jul = [e for e in episodes if e["severity"] == "severe" and e["start"].startswith("2020-07")]
    before_july = [f for f in failures if f["repaired"] < "2020-07-01"]
    return [
        Q("eq1", "How many air-leak failures were reported on APU-1 between February and September 2020?", [len(failures)]),
        Q("eq2", "When was the most recent air-leak repair on APU-1 completed before 1 July 2020? Give the date and time.",
          [before_july[-1]["repaired"][:10]], "text"),
        Q("eq3", "Which day in April 2020 had the highest compressor duty cycle on APU-1, and what was the duty cycle?",
          [top_apr["date"], top_apr["duty_pct"]]),
        Q("eq4", "For how many minutes was the low-pressure switch on during 18 May 2020?", [by["2020-05-18"]["low_pressure_min"]]),
        Q("eq5", "What was APU-1's average daily duty cycle in June 2020?", [round(statistics.fmean(june), 1)]),
        Q("eq6", "How many severe compressor episodes did APU-1 have in July 2020?", [len(sev_jul)]),
        Q("eq7", "What was the lowest TP3 pressure recorded on APU-1 in March 2020?", [round(march_tp3, 2)]),
        Q("eq8", "What was the highest oil temperature on APU-1 in August 2020?", [round(aug_oil, 1)]),
        Q("eq9", "How many load cycles did the compressor make on 17 April 2020?", [by["2020-04-17"]["load_cycles"]]),
        Q("eq10", "How many hours did APU-1 record on 1 March 2020, and what was its duty cycle that day?",
          [by["2020-03-01"]["hours_recorded"], by["2020-03-01"]["duty_pct"]]),
        # Finer than a day: only the 5-minute table holds these.
        Q("eq11", "At what time on 17 April 2020 did APU-1's TP3 pressure first fall below 7 bar? Give the time (HH:MM).",
          [next(r["time"][11:16] for r in fm if r["time"].startswith("2020-04-17") and r["tp3_min_bar"] < 7)], "text"),
        Q("eq12", "What was APU-1's mean motor current in the five minutes from 14:00 on 15 July 2020?",
          [next(r["motor_current_a"] for r in fm if r["time"] == "2020-07-15 14:00")]),
        Q("eq13", "At what time on 2 June 2020 did APU-1's low-pressure switch first come on? Give the time (HH:MM).",
          [next(r["time"][11:16] for r in fm if r["time"].startswith("2020-06-02") and r["low_pressure_s"] > 0)], "text"),
    ]


def port_questions(status: list[dict], events: list[dict], slow_rows: list[dict]) -> list[Q]:
    from collections import Counter
    days = sorted({r["time"][:10] for r in status})

    def day(d: str) -> list[dict]:
        return [r for r in status if r["time"].startswith(d)]
    qs: list[Q] = []
    fog = [r for r in slow_rows if "fog" in r["cause"]]
    if fog:
        f0 = fog[0]
        qs.append(Q("p1", f"How long did the traffic slowdown that began at {f0['start']} UTC last, and how many ships were waiting "
                          f"offshore at its peak?", [f0["hours"], f0["queue_peak"]]))
        qs.append(Q("p2", "How many traffic slowdowns caused by dense fog have been recorded so far?", [len([r for r in fog if 'dense' in r['cause']])]))
    for i, d in enumerate([x for x in ("2024-03-05", "2024-01-19", "2024-02-11", "2024-01-23") if x in days][:3]):
        rs = day(d)
        qs.append(Q(f"p3{i}", f"How many deep-draft ships entered the bay through Bolivar Roads on {d} (UTC)?",
                    [sum(r["inbound_transits"] for r in rs)]))
    jan = [r for r in status if r["time"].startswith("2024-01")]
    if jan:
        top = max(jan, key=lambda r: r["waiting_outside"])
        qs.append(Q("p4", "What was the largest number of deep-draft ships waiting at the offshore anchorage in January 2024?",
                    [top["waiting_outside"]]))
    vis_days = [d for d in days if any(r["vis_galveston_mi"] != "" for r in day(d))]
    for d in [x for x in ("2024-03-04", "2024-01-26") if x in vis_days][:1]:
        low = min(float(r["vis_galveston_mi"]) for r in day(d) if r["vis_galveston_mi"] != "")
        qs.append(Q("p5", f"What was the lowest visibility reported at Galveston on {d}?", [low]))
    sil = Counter(e["vessel"] for e in events if e["event"] == "went_silent" and e["sog"] >= 2 and e["vessel"]
                  and e["zone"] not in ("Gulf approach", "Offshore anchorage"))
    if sil:
        name, n = sil.most_common(1)[0]
        qs.append(Q("p6", "Which deep-draft vessel went silent on AIS most often while moving inside the area, and how many times?",
                    [name, n]))
    for d in [x for x in ("2024-03-04", "2024-01-23") if x in days][:1]:
        rs = day(d)
        qs.append(Q("p7", f"On average, how many deep-draft ships were moving in the channels per hour on {d}?",
                    [round(statistics.fmean(r["moving_total"] for r in rs), 1)]))
    rec = [r for r in slow_rows if r["recovery_hours"] != ""]
    if rec:
        r0 = rec[-1]
        qs.append(Q("p8", f"After the slowdown that began at {r0['start']} UTC, how many hours did the offshore queue take to "
                          f"return to its starting size?", [float(r0["recovery_hours"])]))
    return qs
