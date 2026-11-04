# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Meta models through the Meta Model API, and Muse Spark Open through Baseten.

Routing, by job:
- `chat()` on `muse-spark-1.3-contributor` is the default for development and public data. Contributor mode lets Meta
  train on what is sent, so it gets public datasets and the space's served results only, never client data. A client
  deployment sets `ARGUS_CHAT_MODEL=muse-spark-1.3` (Standard).
- `chat(model="muse-wonder-1.0")` is for rare escalations.
- `chat(provider="baseten")` runs Muse Spark Open, for bulk text.
- `segment()` is SAM 3.1 on an image or a video clip; `transcribe()` is Muse Voice Transcribe on an audio file.

Every call is metered into `ledger` with list prices, so a run can report what it spent.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from .config import Keys, keys as load_keys

META = "https://api.meta.ai/v1"
CHAT_MODEL = os.environ.get("ARGUS_CHAT_MODEL", "muse-spark-1.3-contributor")

# USD per million tokens (input, cached input, output), from dev.meta.ai pricing and Baseten's model page (Nov 2026).
PRICES = {
    "muse-spark-1.3-contributor": (0.10, 0.002, 0.20),
    "muse-spark-1.2-contributor": (0.10, 0.002, 0.20),
    "muse-spark-1.3": (1.25, 0.15, 4.25),
    "muse-spark-1.2": (1.25, 0.15, 4.25),
    "muse-wonder-1.0": (4.00, 0.20, 20.00),
    "meta-models/muse-spark-open-1026": (1.25, 0.15, 4.25),
}
# Where a request goes when the Meta Model API's prompt filter refuses it: Muse Spark Open on Baseten, the same family
# with open weights, served without that filter.
FALLBACK = {"muse-spark-1.3-contributor": ("baseten", None), "muse-spark-1.3": ("baseten", None),
            "muse-spark-1.2-contributor": ("baseten", None)}
SAM_VIDEO_PER_FRAME = 0.20 / 1000
SAM_IMAGE = 2.50 / 1000
TRANSCRIBE_PER_SEC = 0.18 / 3600


@dataclass
class Ledger:
    usd: float = 0.0
    by_model: dict[str, dict[str, float]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, model: str, usd: float, **counts: float) -> None:
        with self.lock:
            self.usd += usd
            m = self.by_model.setdefault(model, {"usd": 0.0, "calls": 0})
            m["usd"] += usd
            m["calls"] += 1
            for k, v in counts.items():
                m[k] = m.get(k, 0) + v

    def summary(self) -> dict:
        return {"usd": round(self.usd, 4), "by_model": {k: {kk: round(vv, 4) for kk, vv in v.items()} for k, v in self.by_model.items()}}


ledger = Ledger()


class ModelError(RuntimeError):
    pass


class Models:
    def __init__(self, k: Keys | None = None):
        self.k = k or load_keys()
        self.http = httpx.Client(timeout=httpx.Timeout(30, read=600))

    def _post(self, url: str, key: str, body: dict, stream: bool = False) -> Any:
        for wait in (2, 5, 15, 30, 0):
            try:
                r = self.http.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
            except httpx.TransportError as e:
                if not wait:
                    raise ModelError(str(e)) from e
                time.sleep(wait)
                continue
            if r.status_code in (429, 500, 502, 503, 504) and wait:
                time.sleep(int(r.headers.get("Retry-After", wait)))
                continue
            if r.status_code >= 400:
                raise ModelError(f"{r.status_code}: {r.text[:400]}")
            return r if stream else r.json()
        raise ModelError("still failing")

    # -- text and vision ---------------------------------------------------------------------------------------------
    def chat(self, messages: list[dict], *, model: str | None = None, provider: str = "meta", tools: list | None = None,
             effort: str | None = "low", max_tokens: int = 4000, json_mode: bool = False) -> dict:
        model = model or (self.k.baseten_model if provider == "baseten" else CHAT_MODEL)
        if provider == "baseten":
            messages = [{**m, "role": "system"} if m.get("role") == "developer" else m for m in messages]
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if tools:
            body["tools"] = tools
        if effort:
            body["reasoning_effort"] = effort            # Baseten's Spark Open takes it too (3 Nov)
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url, key = (f"{self.k.baseten_url}/chat/completions", self.k.baseten_key) if provider == "baseten" \
            else (f"{META}/chat/completions", self.k.meta_key)
        t0 = time.time()
        try:
            out = self._post(url, key, body)
        except ModelError as e:
            # Spark 1.3 Contributor's prompt filter refuses some harmless prompts (seen on "how did it compare with the
            # day before?" with tools). The same request goes to the next model in line, and the fallback is counted.
            nxt = FALLBACK.get(model) if provider == "meta" and "content_policy_violation" in str(e) else None
            if not nxt:
                raise
            ledger.add(model, 0.0, refused=1)
            return self.chat(messages, model=nxt[1], provider=nxt[0], tools=tools, effort=effort, max_tokens=max_tokens,
                             json_mode=json_mode)
        u = out.get("usage") or {}
        pin, pcache, pout = PRICES.get(model, (1.25, 0.15, 4.25))
        cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
        prompt = u.get("prompt_tokens", 0) - cached
        usd = (prompt * pin + cached * pcache + u.get("completion_tokens", 0) * pout) / 1e6
        ledger.add(model, usd, prompt_tokens=u.get("prompt_tokens", 0), completion_tokens=u.get("completion_tokens", 0),
                   seconds=time.time() - t0)
        out["_usd"], out["_seconds"] = usd, time.time() - t0
        return out

    def text(self, prompt: str, *, system: str | None = None, images: list[Path] | None = None, **kw: Any) -> str:
        content: list[dict] | str = prompt
        if images:
            content = [{"type": "text", "text": prompt}] + [
                {"type": "image_url", "image_url": {"url": data_url(p)}} for p in images]
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
        out = self.chat(msgs, **kw)
        return (out["choices"][0]["message"].get("content") or "").strip()

    def json(self, prompt: str, **kw: Any) -> Any:
        raw = self.text(prompt, json_mode=True, **kw)
        return parse_json(raw)

    # -- SAM 3.1 ----------------------------------------------------------------------------------------------------
    def upload(self, path: Path) -> str:
        with path.open("rb") as f:
            r = self.http.post(f"{META}/files", headers={"Authorization": f"Bearer {self.k.meta_key}"},
                               data={"purpose": "user_data"}, files={"file": (path.name, f)})
        if r.status_code >= 400:
            raise ModelError(f"upload {r.status_code}: {r.text[:300]}")
        return r.json()["id"]

    def segment(self, concept: str, *, image: Path | None = None, video_file_id: str | None = None,
                frames: int = 1, confidence: bool = True) -> list[dict]:
        """SAM 3.1 boxes for one noun phrase: [{frame, obj, x1, y1, x2, y2, w, h, c}]. Masks are dropped."""
        part = {"type": "input_image", "image_url": data_url(image)} if image else \
            {"type": "input_video", "file_id": video_file_id}
        body = {"model": "sam-3.1", "stream": True,
                "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": concept}, part]}],
                "metadata": {"include_confidence": "true" if confidence else "false", "mask_encoding": "one_bit"}}
        text = []
        for wait in (2, 5, 15, 0):
            try:
                with self.http.stream("POST", f"{META}/responses", headers={"Authorization": f"Bearer {self.k.meta_key}"},
                                      json=body) as r:
                    if r.status_code >= 400:
                        r.read()
                        if r.status_code in (429, 500, 502, 503) and wait:
                            time.sleep(wait)
                            continue
                        raise ModelError(f"sam {r.status_code}: {r.text[:300]}")
                    for line in r.iter_lines():
                        if line.startswith("data:"):
                            try:
                                ev = json.loads(line[5:].strip())
                            except ValueError:
                                continue
                            if ev.get("type") == "response.output_text.delta":
                                text.append(ev.get("delta", ""))
                break
            except httpx.TransportError:
                if not wait:
                    raise
                time.sleep(wait)
        billed = SAM_IMAGE if image else SAM_VIDEO_PER_FRAME * max(frames, 50)
        ledger.add("sam-3.1", billed, frames=frames)
        return parse_boxes("".join(text))

    # -- voice ------------------------------------------------------------------------------------------------------
    def transcribe(self, audio: Path, seconds: float, mode: str = "PUSH_TO_TALK") -> str:
        """Muse Voice Transcribe on a WAV file (at most 10 minutes); the transcript as plain text."""
        req = json.dumps({"model": "muse-voice-transcribe-1.0", "audioEncoding": "WAV", "mode": mode})
        with audio.open("rb") as f:
            r = self.http.post(f"{META}/asr/transcribe", headers={"Authorization": f"Bearer {self.k.meta_key}", "Accept": "text/plain"},
                               files={"request": (None, req, "application/json"), "audio": (audio.name, f, "audio/wav")})
        if r.status_code >= 400:
            raise ModelError(f"transcribe {r.status_code}: {r.text[:300]}")
        ledger.add("muse-voice-transcribe-1.0", seconds * TRANSCRIBE_PER_SEC, seconds=seconds)
        return " ".join(line.split(":", 1)[1] if line.startswith(("unknown:", "A:", "B:")) else line
                        for line in r.text.splitlines() if line.strip()).strip()


_BOX = re.compile(r"(?:<(\d+)f>)?(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(?:;c=([0-9.]+))?\|>")


def parse_boxes(text: str) -> list[dict]:
    out, frame = [], 0
    for m in _BOX.finditer(text):
        f, o, x1, y1, x2, y2, w, h, c = m.groups()
        if f is not None:
            frame = int(f)
        out.append({"frame": frame, "obj": int(o), "x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2),
                    "w": int(w), "h": int(h), "c": float(c) if c else None})
    return out


def data_url(p: Path) -> str:
    mime = {".png": "image/png", ".webp": "image/webp"}.get(p.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"


def parse_json(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw).strip()
    try:
        return json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}|\[.*\]", raw, re.S)
        if m:
            return json.loads(m.group(0))
        raise
