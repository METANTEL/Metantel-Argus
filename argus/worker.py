# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The harness side of a board's agent part: collect the open agent tasks, do them, put the answers back.

A board built in Artel ends in an agent part (answer, warn, plan or brief, for an audience), which leaves a task in the
Managed Memory Harness. This worker collects open tasks, runs Argus's agent on them, puts each answer back as an item
(`agent/answers/<task>.md`), and marks the task done with that item's name, so Artel shows it under the board.

    python -m argus.worker [--once] [--site port|plant] [--now "2024-03-05 08:00"]
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone

from .agent import Agent, Episodes
from .memory import Edip, EdipError

SITES = {
    "port": ("the Port of Houston approaches: the Houston Ship Channel, Galveston Bay and the Bolivar Roads entrance",
             {"slowdown": "port/slowdowns.csv"},
             {"slowdown": ["hours_so_far", "min_traffic_ratio_so_far", "min_visibility_mi_so_far", "queue_start"]},
             {"slowdown": ["hours", "recovery_hours", "queue_growth", "transits_lost"]}),
    "plant": ("the plant: its compressed-air system (unit APU-1) and its warehouse floor",
              {"compressor": "plant/apu_episodes.csv"},
              {"compressor": ["peak_duty_pct", "low_pressure_min", "min_tp3_bar", "hours"]},
              {"compressor": ["failure_within_72h", "hours_to_failure"]}),
}


def answer_markdown(task: dict, ans: dict) -> str:
    lines = [f"# {ans.get('headline') or task.get('title') or 'Agent answer'}", "",
             f"Board: {task.get('board') or '—'} · part: {task.get('title')} · job: {task['mode']} for the {task['audience']}"
             f" · level: {ans.get('level') or '—'} · confidence: {ans.get('confidence') or '—'}", "", ans.get("body") or ""]
    if ans.get("actions"):
        lines += ["", "## Actions"] + [f"- **{a.get('action')}** — {a.get('who', '')}, {a.get('when', '')}. Expected: "
                                       f"{a.get('expected_effect', '')}. Rests on: {a.get('rests_on', '')}" for a in ans["actions"]]
    if ans.get("forecasts"):
        lines += ["", "## Forecasts"] + [f"- {f.get('what')}: {f.get('value')} {f.get('unit', '')} (range {f.get('low')}–{f.get('high')}); "
                                         f"basis: {f.get('basis', '')}" for f in ans["forecasts"]]
    if ans.get("citations"):
        lines += ["", "## Sources"] + [f"- {c}" for c in ans["citations"]]
    return "\n".join(lines) + "\n"


def do(task: dict, agent: Agent, edip: Edip, now: str) -> dict:
    context = "\n".join(f"- {it['item']}: {(it.get('text') or '')[:1500]}" for it in task.get("items") or [] if it.get("text"))
    res = agent.run(task["mode"], task["instruction"], now, audience=task["audience"],
                    context=("Items the board passed on:\n" + context) if context else "")
    name = f"agent/answers/{task['id']}.md"
    edip.ingest(name, answer_markdown(task, res.answer), kind="note",
                tags=["code=AGENT", f"mode={task['mode']}", f"audience={task['audience']}"])
    level = res.answer.get("level") if res.answer.get("level") in ("info", "watch", "act_now") else ""
    edip._read("POST", f"/agent/tasks/{task['id']}", {"answer_item": name, "level": level})
    return {"task": task["id"], "item": name, "level": level, "usd": res.usd, "seconds": res.seconds}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--site", default="port", choices=sorted(SITES))
    ap.add_argument("--now", default=None, help="the clock the agent reasons at (a replayed site's time); default: now")
    ap.add_argument("--every", type=float, default=10.0)
    a = ap.parse_args()
    edip = Edip()
    site, tables, feats, outs = SITES[a.site]
    agent = Agent(site, edip, episodes=Episodes(edip, tables, feats, outs))
    while True:
        try:
            tasks = edip._read("POST", "/agent/tasks/claim", {"harness": "argus", "limit": 3}).get("tasks", [])
        except EdipError as e:
            print("claim failed:", e)
            tasks = []
        for t in tasks:
            now = a.now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            try:
                print(json.dumps(do(t, agent, edip, now)))
            except Exception as e:  # noqa: BLE001 - one failed task is reported back, the worker goes on
                print(f"task {t['id']} failed: {e}")
                try:
                    edip._read("POST", f"/agent/tasks/{t['id']}", {"failed": True})
                except EdipError:
                    pass
        if a.once:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
