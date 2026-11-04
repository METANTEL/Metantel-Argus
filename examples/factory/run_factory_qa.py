# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The questions a plant manager, a supervisor and an operator ask the factory's hive, answered from the memory with
the harness's what-if, by the agent whose section it is. One question is spoken (macOS speech, or a person's recording
with --voice, then Muse Voice Transcribe). Answers and every tool call are saved for the console's Ask view.

    python examples/factory/run_factory_qa.py [--only q1,q4] [--voice recording.m4a]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from argus.config import RUNS
from argus.hive.link import Link
from argus.memory import Edip
from argus.models import Models, ledger
from argus.sites.factory import feed as FX
from argus.sites.factory import team as H

NOW = f"{FX.CLOCK[:10]} 08:05"
QUESTIONS = [
    {"id": "q1", "who": "director", "mode": "brief", "audience": "executive",
     "text": "Brief me on the whole site: the last five minutes across all four halls, what matters, and what you would do."},
    {"id": "q2", "who": "floor", "mode": "plan", "audience": "manager",
     "text": "Where is the floor most crowded, and what should we change?"},
    {"id": "q3", "who": "logistics", "mode": "answer", "audience": "manager",
     "text": "Are our vehicles and robots earning their keep? What would you reassign?"},
    {"id": "q4", "who": "safety", "mode": "plan", "audience": "manager",
     "text": "What single change would remove the most close calls? Show me the evidence."},
    {"id": "q5", "who": "director", "mode": "plan", "audience": "manager",
     "text": "Plan the next shift for all four halls: people, vehicle routes and robots."},
    {"id": "q6", "who": "safety", "mode": "answer", "audience": "manager",
     "text": "Hall D has no cameras and only 70 percent of people wear badges. How far can we trust its safety numbers, "
             "and what would you add?"},
    {"id": "q7", "who": "safety", "mode": "answer", "audience": "operator", "voice": True,
     "text": "Is it safe to send the transporter across Hall C right now?"},
]
MODELS = {"director": "muse-wonder-1.0", "floor": "muse-spark-1.3", "safety": "muse-spark-1.3", "logistics": "muse-spark-1.3"}


def speak(text: str, out: Path) -> tuple[Path, float]:
    """The question spoken by macOS's own voice, as 16 kHz mono WAV for Muse Voice Transcribe. For runs only: Apple
    licenses its system voices for personal, non-commercial use, so anything published uses a person's recording (--voice)."""
    aiff = out.with_suffix(".aiff")
    subprocess.run(["say", "-v", "Samantha", "-r", "175", "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(out)], check=True)
    secs = float(subprocess.run(["afinfo", str(out)], capture_output=True, text=True).stdout.split("estimated duration:")[1].split()[0])
    return out, secs


def record(src: Path, out: Path) -> tuple[Path, float]:
    """A person's recording of the question (any format ffmpeg reads), as 16 kHz mono WAV."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(out)],
                   check=True)
    secs = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
                                capture_output=True, text=True, check=True).stdout)
    return out, secs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--voice", type=Path, help="a person's recording of the spoken question, used instead of macOS's voice")
    ap.add_argument("--provider", default="meta", help="meta, or baseten for Muse Spark Open on every role")
    a = ap.parse_args()
    run = time.strftime("%Y%m%d%H%M")
    out = RUNS / "factory-qa" / run
    out.mkdir(parents=True, exist_ok=True)
    edip, models = Edip(), Models()
    link = Link(edip, out / "hive.jsonl")
    by_role = MODELS if a.provider == "meta" else {}
    hive = H.make(link, edip, models, run, provider=a.provider, models_by_role=by_role)
    for m in hive.values():
        m.announce()
    results = []
    for q in QUESTIONS:
        if a.only and q["id"] not in a.only.split(","):
            continue
        rec = {**q, "now": NOW, "model": by_role.get(q["who"]) or models.k.baseten_model}
        text = q["text"]
        if q.get("voice"):
            wav, secs = record(a.voice, out / f"{q['id']}.wav") if a.voice else speak(text, out / f"{q['id']}.wav")
            heard = models.transcribe(wav, secs)
            rec.update(audio=str(wav), audio_seconds=round(secs, 1), transcript=heard)
            text = heard or text
        m = hive[q["who"]]
        t0 = time.time()
        o = m.brain.run(q["mode"], text, NOW, q["audience"], context=H.KNOWN, preamble=m.system())
        rec.update(answer=o.answer, trace=o.trace, usd=o.usd, seconds=round(time.time() - t0, 1), role=m.role)
        results.append(rec)
        print(q["id"], m.role, "|", (o.answer or {}).get("headline"), f"| {len(o.trace)} tools, {rec['seconds']} s", flush=True)
        (out / "answers.json").write_text(json.dumps(results, indent=1, default=str))
    print(json.dumps(ledger.summary(), indent=1))
    print(out)


if __name__ == "__main__":
    main()
