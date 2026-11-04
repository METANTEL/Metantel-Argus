# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Camera perception that follows everyone in view.

SAM 3.1 returns at most 16 objects a frame for one noun phrase, and a factory camera sees sixty people: asked about the
whole view, it follows the sixteen it ranks first and drops the rest. So a watcher looks at its view in tiles, at the
camera's own resolution, and looks closer wherever a tile comes back full (`LIMIT` or more in some frame: that tile is
split in four and looked at again). The tiles' boxes are put back in the camera's frame, duplicates where tiles overlap
are merged, and each person keeps one identity across tiles and frames.

SAM follows at most 16 objects in one request over a whole clip as well, so a request that has followed 16 is split in
time (`WINDOW_S`) and the windows are joined by position.
"""
from __future__ import annotations

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..sites.factory import feed as FX
from . import floor as F

LIMIT = 14                       # a tile returning this many objects in a frame is full: SAM stops at 16
TRACKED = 16                     # and it follows at most 16 objects in one request, across the whole clip
WINDOW_S = 60                    # so a tile still full at the finest split is asked about a minute at a time
OVERLAP = 0.18                   # tiles overlap by this share of their size, so a person cut by one is whole in the next
Box = tuple[int, int, int, int]  # x, y, w, h in the camera's own pixels (1920×1080)
_SAM = threading.Semaphore(10)   # requests in flight at once, across cameras and tiles


def _name(box: Box) -> str:
    return "-".join(str(v) for v in box)


def region_clip(hall: str, cam: str, box: Box, fps: int, window: tuple[int, int] | None = None) -> Path:
    """The camera's video cut to one region at its own resolution, sampled at `fps`, optionally one window of seconds."""
    x, y, w, h = box
    span = f"_{window[0]}-{window[1]}s" if window else ""
    out = FX.scene_dir(hall) / "regions" / f"{cam}_{_name(box)}_{fps}fps{span}.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".part.mp4")
        cut = ["-ss", str(window[0]), "-t", str(window[1] - window[0])] if window else []
        subprocess.run(["ffmpeg", "-v", "error", "-y", *cut, "-i", str(FX.scene_dir(hall) / "videos" / f"{cam}.mp4"), "-vf",
                        f"fps={fps},crop={w}:{h}:{x}:{y}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-an",
                        str(tmp)], check=True)
        tmp.rename(out)
    return out


def look(models, hall: str, cam: str, box: Box, concept: str, fps: int = F.FPS, window: tuple[int, int] | None = None) -> list[dict]:
    """SAM 3.1 on one region (and window of seconds): boxes in the camera's own pixels and the clip's frame numbers,
    cached per region, window, rate and concept."""
    span = f"_{window[0]}-{window[1]}s" if window else ""
    cache = FX.scene_dir(hall) / "sam_regions" / f"{cam}_{_name(box)}_{fps}fps{span}_{concept.replace(' ', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    path = region_clip(hall, cam, box, fps, window)
    frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                 "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
    with _SAM:
        raw = models.segment(concept, video_file_id=models.upload(path), frames=frames)
    x0, y0, w, h = box
    f0 = window[0] * fps if window else 0
    out = [{"frame": f0 + b["frame"], "obj": b["obj"], "x1": x0 + b["x1"] * w / b["w"], "y1": y0 + b["y1"] * h / b["h"],
            "x2": x0 + b["x2"] * w / b["w"], "y2": y0 + b["y2"] * h / b["h"], "c": b.get("c")} for b in raw]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def split(box: Box, n: int = 2, overlap: float = OVERLAP) -> list[Box]:
    x, y, w, h = box
    tw, th = w / (n - (n - 1) * overlap), h / (n - (n - 1) * overlap)
    out = []
    for j in range(n):
        for i in range(n):
            bx, by = x + i * tw * (1 - overlap), y + j * th * (1 - overlap)
            out.append((int(bx) // 2 * 2, int(by) // 2 * 2, int(tw) // 2 * 2, int(th) // 2 * 2))
    return out


def crowded(boxes: list[dict]) -> bool:
    """Some frame came back with as many objects as SAM returns in a frame: look at a smaller region."""
    per: dict[int, int] = {}
    for b in boxes:
        per[b["frame"]] = per.get(b["frame"], 0) + 1
    return max(per.values(), default=0) >= LIMIT


def followed_all(boxes: list[dict]) -> bool:
    """The request followed as many objects as SAM follows in one request: look at a shorter stretch of time."""
    return len({b["obj"] for b in boxes}) >= TRACKED


def full(boxes: list[dict]) -> bool:
    return crowded(boxes) or followed_all(boxes)


def tiled(models, hall: str, cam: str, concept: str = "person", box: Box = (0, 0, F.SRC_W, F.SRC_H), depth: int = 0,
          max_depth: int = 2, fps: int = F.FPS) -> list[tuple[Box, list[dict]]]:
    """The view in 2×2 tiles; a tile that comes back full is split again, down to `max_depth`. [(tile, boxes)]."""
    def one(t: Box) -> list[tuple[Box, list[dict]]]:
        # split along whichever limit was hit: space where a frame was full, time where the request followed all it can
        got = look(models, hall, cam, t, concept, fps)
        if crowded(got) and depth + 1 < max_depth:
            return tiled(models, hall, cam, concept, t, depth + 1, max_depth, fps)
        if followed_all(got):
            last = max((b["frame"] for b in got), default=0) // fps + 1
            return [(t, look(models, hall, cam, t, concept, fps, (s, min(s + WINDOW_S, last))))
                    for s in range(0, last, WINDOW_S)]
        return [(t, got)]
    with ThreadPoolExecutor(4) as ex:
        return [x for part in ex.map(one, split(box)) for x in part]


def _iou(a: dict, b: dict) -> tuple[float, float]:
    """(intersection over union, intersection over the smaller box)."""
    ix = max(0.0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
    iy = max(0.0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]))
    inter = ix * iy
    aa, ab = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]), (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    return (inter / (aa + ab - inter) if inter else 0.0), (inter / min(aa, ab) if inter and min(aa, ab) > 0 else 0.0)


def _cut(b: dict, tile: Box, margin: float = 4.0) -> bool:
    """The box touches an inner edge of its tile: the person runs on into the next tile."""
    x, y, w, h = tile
    return ((b["x1"] <= x + margin and x > 0) or (b["y1"] <= y + margin and y > 0)
            or (b["x2"] >= x + w - margin and x + w < F.SRC_W) or (b["y2"] >= y + h - margin and y + h < F.SRC_H))


def _follow(tr: dict, b: dict) -> float:
    """How surely box `b` is the object `tr` last seen: SAM's own identity within a tile is sure; otherwise the box must
    be about where the object was (within 0.6 of its height) and about its size."""
    if tr["key"] == b["key"]:
        return 2.0
    a = tr["box"]
    ha, hb = a["y2"] - a["y1"], b["y2"] - b["y1"]
    if not ha or not hb or not 0.6 < hb / ha < 1.6:
        return 0.0
    d = ((a["x1"] + a["x2"] - b["x1"] - b["x2"]) ** 2 / 4 + (a["y2"] - b["y2"]) ** 2) ** 0.5
    return max(0.0, 1 - d / (0.6 * max(ha, hb)))


def merge(tiles: list[tuple[Box, list[dict]]]) -> list[dict]:
    """One box per object per frame in the camera's frame, and one identity per object. Boxes of the same object from
    overlapping tiles are one box: the tile that has followed it longest keeps it, so it does not flip between tiles.
    SAM keeps an object's identity within a tile as long as it follows it, so an identity follows SAM's; an object SAM
    starts afresh is matched to one last seen just there, a moment before."""
    by_frame: dict[int, list[dict]] = {}
    for n, (tile, boxes) in enumerate(tiles):
        x, y, w, h = tile
        for b in boxes:
            if b["y2"] >= y + h - 4 and y + h < F.SRC_H:     # its feet are below the tile: it cannot be put on the floor
                continue
            by_frame.setdefault(b["frame"], []).append({**b, "key": (n, b["obj"]), "cut": _cut(b, tile)})
    seen: dict[tuple, int] = {}
    key_id: dict[tuple, int] = {}
    last: dict[int, tuple[int, dict]] = {}
    out: list[dict] = []
    next_id = 0
    for f in sorted(by_frame):
        kept: list[dict] = []
        for b in sorted(by_frame[f], key=lambda b: (b["cut"], -seen.get(b["key"], 0), -(b["x2"] - b["x1"]) * (b["y2"] - b["y1"]))):
            if not any(k["key"][0] != b["key"][0] and (lambda u: u[0] > 0.45 or u[1] > 0.8)(_iou(b, k)) for k in kept):
                kept.append(b)
        used: set[int] = set()
        for b in kept:
            i = key_id.get(b["key"])
            if i is None:
                best = max(((_follow({"key": None, "box": box}, b), j) for j, (fr, box) in last.items()
                            if 0 < f - fr <= 4), default=(0.0, None))
                i = best[1] if best[0] > 0.4 else None
            if i is None or i in used:
                i, next_id = next_id, next_id + 1
            key_id[b["key"]] = i
            seen[b["key"]] = seen.get(b["key"], 0) + 1
            used.add(i)
            last[i] = (f, b)
            out.append({"frame": f, "obj": i, "x1": round(b["x1"], 1), "y1": round(b["y1"], 1), "x2": round(b["x2"], 1),
                        "y2": round(b["y2"], 1), "w": F.SRC_W, "h": F.SRC_H, "c": b.get("c")})
    return out


def dense(models, hall: str, cam: str, concept: str = "person", max_depth: int = 2) -> list[dict]:
    """Everyone the camera sees, in its own pixels, one identity each: the tiled look, merged. Cached per camera."""
    cache = FX.scene_dir(hall) / "sam_dense" / f"{cam}_{concept.replace(' ', '_')}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    tiles = tiled(models, hall, cam, concept, max_depth=max_depth)
    out = merge(tiles)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"boxes": out, "tiles": [t for t, _ in tiles]}))
    return json.loads(cache.read_text())


def run_all(models, hall: str, concept: str = "person", workers: int = 4) -> dict[str, int]:
    """Every camera of a hall, `workers` at a time: the number of boxes each ended with."""
    def one(cam: str) -> tuple[str, int]:
        return cam, len(dense(models, hall, cam, concept)["boxes"])
    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, FX.cameras(hall)))
