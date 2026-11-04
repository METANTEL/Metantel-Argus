# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Ask Argus a question about a site, typed or spoken (a WAV file, transcribed by Muse Voice Transcribe).

    python examples/ask.py port "How long did the last fog closure last?" --now "2024-03-31 23:00" --audience operator
    python examples/ask.py port --wav question.wav --now "2024-03-31 23:00" --audience operator

`--now` is the site's clock, normally the end of the replay that filled the memory. The agent here is not kept at that
moment by its tools (`Agent(bounded=True)`, as the hive's runs and the year's questions are): it sees whatever the memory
holds, so ask at the end of a replay, or against a memory that was filled only up to `--now`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from argus.agent import Agent, Episodes
from argus.memory import Edip
from argus.models import Models, ledger
from argus.worker import SITES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("site", choices=sorted(SITES))
    ap.add_argument("question", nargs="?")
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--now", required=True, help="the site's clock, e.g. the end of a replay")
    ap.add_argument("--audience", default="manager", choices=["operator", "supervisor", "manager", "executive"])
    ap.add_argument("--mode", default="answer", choices=["answer", "warn", "plan", "brief"])
    a = ap.parse_args()
    models = Models()
    question = a.question
    if a.wav:
        seconds = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(a.wav)],
                                       capture_output=True, text=True).stdout.strip() or 0)
        question = models.transcribe(a.wav, seconds)
        print(f"Heard: {question}\n")
    if not question:
        ap.error("a question or --wav is needed")
    edip = Edip()
    site, tables, feats, outs = SITES[a.site]
    agent = Agent(site, edip, models, Episodes(edip, tables, feats, outs))
    r = agent.run(a.mode, question, a.now, audience=a.audience)
    ans = r.answer
    print(f"[{ans.get('level', '')}] {ans.get('headline', '')}\n\n{ans.get('body', '')}")
    for act in ans.get("actions") or []:
        print(f"- {act.get('action')} ({act.get('who')}, {act.get('when')})")
    print(f"\n{json.dumps({'tools': [t['tool'] for t in r.trace], 'usd': r.usd, 'seconds': r.seconds, 'spend': ledger.summary()['usd']})}")


if __name__ == "__main__":
    main()
