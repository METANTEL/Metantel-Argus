# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Machines named by a frontier model and followed by SAM 3.1.

SAM 3.1 finds what a noun phrase describes and follows it, but it cannot tell a forklift standing parked from the
transporter driving past it, nor that the small white box by the rack is the floor's mobile robot. Muse Spark can. It
looks at a keyframe with SAM's own proposals drawn on it and names what matters: each machine, what kind it is, whether
it is being driven, and any machine SAM did not box. Each named machine then goes to SAM as a box prompt under the
tagger's own id, and SAM follows it through the video, returning a box and a mask every frame.

When a named machine is lost, or one SAM proposes is not among the tags, the camera supervisor asks for tags again at
that moment (argus/sites/factory/supervise.py), and SAM is prompted again from there: one request carries every prompt, at every
frame where a tag was made.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..sites.factory import feed as FX
from . import floor as F

W, H = F.W, F.H                                   # the 2-frames-a-second clip SAM follows, 960×540
KINDS = {"forklift": "forklift", "transporter": "transporter", "mobile robot": "robot", "humanoid robot": "humanoid"}
COLOURS = ["red", "blue", "lime", "yellow", "magenta", "cyan", "orange", "white"]


def proposals(hall: str, cam: str, frame: int) -> list[tuple[int, int, int, int]]:
    """SAM's own "vehicle" boxes at one frame of the clip, in the clip's pixels."""
    det = FX.detect(None, hall, cam, dense=False, tagged=False)
    return [(b["x1"] * W // b["w"], b["y1"] * H // b["h"], b["x2"] * W // b["w"], b["y2"] * H // b["h"])
            for b in det.get("vehicle", []) if b["frame"] == frame][:len(COLOURS)]


def keyframe(hall: str, cam: str, frame: int, boxes: list[tuple], out: Path) -> Path:
    """The clip's frame with each box drawn in its own colour (the tagger is told which colour is which box)."""
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        draw = [f"drawbox=x={x1}:y={y1}:w={max(4, x2 - x1)}:h={max(4, y2 - y1)}:color={COLOURS[k]}@0.95:t=3"
                for k, (x1, y1, x2, y2) in enumerate(boxes)]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{frame / F.FPS:.2f}", "-i", str(FX.clip(hall, cam)),
                        "-frames:v", "1", *(["-vf", ",".join(draw)] if draw else []), "-q:v", "3", str(out)], check=True)
    return out


def ask(member, hall: str, cam: str, frame: int, boxes: list[tuple], known: list[dict], knowledge: list[str],
        out_dir: Path) -> list[dict]:
    """The tagger's look at one frame: every machine in view, what it is, what it is doing, and its box."""
    img = keyframe(hall, cam, frame, boxes, out_dir / f"{cam}_tag_{frame}.jpg")
    drawn = "; ".join(f"{COLOURS[k]} box at x1={b[0]} y1={b[1]} x2={b[2]} y2={b[3]}" for k, b in enumerate(boxes)) or "none"
    seen = "; ".join(f"id {t['id']}: {t['kind']} last seen at {t['box']}" for t in known) or "none yet"
    got = member.ask_json(
        f"Frame {frame} ({frame / F.FPS:.1f} s) of {cam} in Hall {hall}, 960×540 pixels. The perception model proposed these "
        f"vehicle boxes: {drawn}. Machines already named on this camera: {seen}.\n\nName every machine you can see in this "
        "frame: forklifts, the autonomous transporter (a low, flat cart), mobile robots (small, low, white boxes on wheels), "
        "humanoid robots. For each, give its kind, whether it is being driven or moving on its own, or standing parked or "
        "stopped (judge from the scene: an empty seat, people walking past a still vehicle), the colour of the proposal box "
        "that is it (or null if none is), the id of the machine already named that it is (or null if it is new), and its "
        "box in this frame's pixels. Leave out people, pallets and racks.\n\nReply with JSON only: {\"machines\": [{\"kind\": "
        "\"forklift|transporter|mobile robot|humanoid robot\", \"state\": \"driven|moving|parked|stopped|unsure\", \"proposal\": "
        "\"red|blue|…|null\", \"same_as\": id or null, \"box\": [x1, y1, x2, y2], \"why\": \"one short phrase\"}]}",
        images=[img], max_tokens=3000)
    things = []
    for m in (got.get("machines") or []) if isinstance(got, dict) else []:
        kind = str(m.get("kind") or "").lower()
        if kind not in KINDS:
            continue
        colour = str(m.get("proposal") or "").lower()
        box = boxes[COLOURS.index(colour)] if colour in COLOURS[:len(boxes)] else m.get("box")
        try:
            x1, y1, x2, y2 = (int(round(float(v))) for v in box)
        except (TypeError, ValueError):
            continue
        x1, x2 = sorted((max(0, min(W - 1, x1)), max(0, min(W - 1, x2))))
        y1, y2 = sorted((max(0, min(H - 1, y1)), max(0, min(H - 1, y2))))
        if x2 - x1 < 4 or y2 - y1 < 4:
            continue
        things.append({"kind": kind, "state": str(m.get("state") or "unsure"), "same_as": m.get("same_as"),
                       "box": [x1, y1, x2, y2], "why": str(m.get("why") or ""), "frame": frame, "image": str(img)})
    return things


def classify(member, hall: str, cam: str, frame: int, box: tuple, knowledge: list[str], out_dir: Path) -> dict:
    """The tagger's close look at one proposed machine: a crop of the camera's own frame around the box, so a small cart
    in a crowded view is seen as clearly as one in the foreground. {kind, driven, why}; kind "none" when it is no machine."""
    sx, sy = F.SRC_W / W, F.SRC_H / H
    x1, y1, x2, y2 = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    side = max(x2 - x1, y2 - y1) * 1.6 + 80
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    w = h = min(F.SRC_H, side)
    left, top = max(0, min(F.SRC_W - w, cx - w / 2)), max(0, min(F.SRC_H - h, cy - h / 2))
    img = out_dir / f"{cam}_crop_{frame}_{box[0]}_{box[1]}.jpg"
    if not img.exists():
        img.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{frame / F.FPS:.2f}", "-i", str(FX.scene_dir(hall) / "videos" / f"{cam}.mp4"),
                        "-frames:v", "1", "-vf", f"crop={int(w)}:{int(h)}:{int(left)}:{int(top)},scale=512:512", "-q:v", "3", str(img)],
                       check=True)
    got = member.ask_json("A close crop from a factory camera, centred on something the perception model took for a vehicle. "
                          "What is the object in the middle? What the site's people say its machines look like:\n- "
                          + "\n- ".join(knowledge) + "\n\nReply with JSON only: {\"kind\": \"forklift|transporter|mobile robot|"
                          "humanoid robot|none\", \"driven\": \"yes|no|unsure\", \"why\": \"what you see, one short phrase\"}",
                          images=[img], max_tokens=1500)
    kind = str((got or {}).get("kind") or "none").lower() if isinstance(got, dict) else "none"
    return {"kind": kind if kind in KINDS else "none", "driven": str(got.get("driven") or "unsure") if isinstance(got, dict) else "unsure",
            "why": str(got.get("why") or "") if isinstance(got, dict) else "", "image": str(img)}


def prompt_text(prompts: list[dict]) -> str:
    """SAM 3.1's box prompts: each named machine under its id, at the frame it was named."""
    return "".join(f"<{p['frame']}f>{p['id']}<|box;x1={p['box'][0]};y1={p['box'][1]};x2={p['box'][2]};y2={p['box'][3]};w={W};h={H}|>"
                   for p in sorted(prompts, key=lambda p: (p["frame"], p["id"])))


def follow(models, hall: str, cam: str, prompts: list[dict], cache: Path) -> list[dict]:
    """SAM 3.1 follows every prompted machine through the clip: its box every frame, under the tagger's id."""
    key = json.dumps(sorted((p["frame"], p["id"], p["box"]) for p in prompts))
    if cache.exists():
        got = json.loads(cache.read_text())
        if got.get("key") == key:
            return got["boxes"]
    clip = FX.clip(hall, cam)
    frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                 "stream=nb_read_frames", "-of", "csv=p=0", str(clip)], capture_output=True, text=True).stdout.strip())
    boxes = models.segment(prompt_text(prompts), video_file_id=models.upload(clip), frames=frames)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"key": key, "boxes": boxes}))
    return boxes


def lost(boxes: list[dict], ids: list[int], frames: int, gap: int = 12) -> list[tuple[int, int]]:
    """(id, frame) where a named machine stopped being followed for at least `gap` frames before the clip's end."""
    out = []
    for i in ids:
        seen = sorted({b["frame"] for b in boxes if b["obj"] == i})
        if not seen:
            continue
        for a, b in zip(seen, seen[1:] + [frames]):
            if b - a > gap:
                out.append((i, a + 1))
                break
    return out


def unnamed(hall: str, cam: str, boxes: list[dict], run: int = 6) -> list[int]:
    """Frames where SAM proposes a vehicle that no named machine overlaps, for `run` frames in a row: something new."""
    det = FX.detect(None, hall, cam, dense=False, tagged=False).get("vehicle", [])
    named: dict[int, list[dict]] = {}
    for b in boxes:
        named.setdefault(b["frame"], []).append(b)
    streak, out = 0, []
    for f in sorted({b["frame"] for b in det}):
        new = [p for p in det if p["frame"] == f and not any(_overlap(p, n) for n in named.get(f, []))]
        streak = streak + 1 if new else 0
        if streak == run:
            out.append(f - run + 1)
            streak = -10_000                     # once per stretch
        elif not new:
            streak = 0
    return out


def _overlap(p: dict, n: dict) -> bool:
    a = (p["x1"] * W / p["w"], p["y1"] * H / p["h"], p["x2"] * W / p["w"], p["y2"] * H / p["h"])
    b = (n["x1"] * W / n["w"], n["y1"] * H / n["h"], n["x2"] * W / n["w"], n["y2"] * H / n["h"])
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy > 0.2 * min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
