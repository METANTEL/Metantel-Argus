# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The warehouse floor: cameras, seen by SAM 3.1, turned into positions and near-misses on the floor plan.

Source: NVIDIA PhysicalAI-SmartSpaces, MTMC_Tracking_2025, scene Warehouse_015 (CC BY 4.0): 13 calibrated cameras,
5 minutes at 30 fps, people, forklifts and mobile robots, with 3D ground truth.

Pipeline, per camera:
1. ffmpeg cuts the video to 2 frames a second at 960×540, so SAM is billed for 600 frames, not 9,000.
2. SAM 3.1 finds every "person" and every "vehicle" in each frame (one request per noun phrase).
3. The bottom-centre of each box is projected onto the floor through the camera's homography (image → metres).
4. Detections from all cameras at the same instant are merged when they fall within a metre or two of each other.
5. A person within `NEAR_M` of a moving vehicle (the autonomous transporter; parked forklifts are left out) is a
   near-miss; consecutive frames make one episode.

The 3D ground truth is used only to score the pipeline, never as an input. A near-miss there is a person within 2 m of
the transporter or the NovaCarter robot; the forklifts never move.
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..config import DATA
from ..models import Models

SCENE = DATA / "smartspaces" / "Warehouse_015"
CLIPS = DATA / "smartspaces" / "clips"
FPS = 2
W, H = 960, 540
SRC_W, SRC_H = 1920, 1080
NEAR_M = 1.5             # detection: person to the moving vehicle's nearest ground point
GT_NEAR_M = 2.0          # truth: person to the transporter's centre


def cameras() -> dict[str, dict]:
    return {s["id"]: s for s in json.loads((SCENE / "calibration.json").read_text())["sensors"]}


def _inv3(m: list[list[float]]) -> list[list[float]]:
    a, b, c = m[0]
    d, e, f = m[1]
    g, h, i = m[2]
    A, B, C = e * i - f * h, -(d * i - f * g), d * h - e * g
    D, E, F = -(b * i - c * h), a * i - c * g, -(a * h - b * g)
    G, Hh, I = b * f - c * e, -(a * f - c * d), a * e - b * d
    det = a * A + b * B + c * C
    return [[A / det, D / det, G / det], [B / det, E / det, Hh / det], [C / det, F / det, I / det]]


def to_floor(hinv: list[list[float]], x: float, y: float) -> tuple[float, float]:
    u = hinv[0][0] * x + hinv[0][1] * y + hinv[0][2]
    v = hinv[1][0] * x + hinv[1][1] * y + hinv[1][2]
    w = hinv[2][0] * x + hinv[2][1] * y + hinv[2][2]
    return u / w, v / w


def clip(camera: str) -> Path:
    CLIPS.mkdir(parents=True, exist_ok=True)
    out = CLIPS / f"{camera}_{FPS}fps_{W}.mp4"
    if not out.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(SCENE / "videos" / f"{camera}.mp4"), "-vf",
                        f"fps={FPS},scale={W}:{H}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-an", str(out)],
                       check=True)
    return out


def detect(models: Models, camera: str, concepts: tuple[str, ...] = ("person", "vehicle")) -> dict[str, list[dict]]:
    """SAM boxes per concept for one camera, cached on disk so a rerun only pays for concepts not yet asked.

    "vehicle" is the phrase that finds both the forklifts and the autonomous transporter; "robot" and "cart" found
    nothing on these frames. The small NovaCarter robot (about 15 px wide here) is not found by any phrase tried."""
    cache = CLIPS / f"{camera}_sam.json"
    out = json.loads(cache.read_text()) if cache.exists() else {}
    todo = [c for c in concepts if c not in out]
    if todo:
        path = clip(camera)
        frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                     "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
        fid = models.upload(path)
        for c in todo:
            out[c] = models.segment(c, video_file_id=fid, frames=frames)
        out["_frames"] = frames
        cache.write_text(json.dumps(out))
    return out


@dataclass
class Spot:
    t: float                 # seconds from the start of the clip
    kind: str                # person | vehicle
    x: float
    y: float
    camera: str
    c: float | None
    box: tuple[float, float, float, float] | None = None   # the detection's box in the camera's own pixels (1920×1080)


def spots(camera: str, det: dict, cal: dict) -> list[Spot]:
    hinv = _inv3(cal["homography"])
    out = []
    for kind in ("person", "vehicle"):
        for b in det.get(kind, []):
            sx, sy = SRC_W / b["w"], SRC_H / b["h"]
            fx, fy = to_floor(hinv, (b["x1"] + b["x2"]) / 2 * sx, b["y2"] * sy)
            if abs(fx) > 200 or abs(fy) > 200:          # projections near the horizon are meaningless
                continue
            out.append(Spot(b["frame"] / FPS, kind, fx, fy, camera, b.get("c"), (b["x1"] * sx, b["y1"] * sy, b["x2"] * sx, b["y2"] * sy)))
    return out


def merge(all_spots: list[Spot], radius: dict[str, float] = {"person": 1.0, "vehicle": 2.0}) -> dict[float, list[Spot]]:
    """At each instant, detections of the same kind seen by several cameras within `radius` are one object."""
    by_t: dict[float, list[Spot]] = {}
    for s in sorted(all_spots, key=lambda s: (s.t, -(s.c or 0))):
        kept = by_t.setdefault(s.t, [])
        if not any(k.kind == s.kind and math.dist((k.x, k.y), (s.x, s.y)) < radius[s.kind] for k in kept):
            kept.append(s)
    return by_t


def parked(by_t: dict[float, list[Spot]], share: float = 0.6, radius: float = 1.5) -> list[tuple[float, float]]:
    """Places where a vehicle stands in most frames: parked forklifts, not traffic."""
    pts = [(s.x, s.y) for ss in by_t.values() for s in ss if s.kind == "vehicle"]
    spots: list[tuple[float, float]] = []
    for p in pts:
        if any(math.dist(p, q) < radius for q in spots):
            continue
        n = sum(any(s.kind == "vehicle" and math.dist((s.x, s.y), p) < radius for s in ss) for ss in by_t.values())
        if n >= share * len(by_t):
            spots.append(p)
    return spots


def only_moving(by_t: dict[float, list[Spot]], still: list[tuple[float, float]], frames: int = 4,
                min_move: float = 0.5) -> dict[float, list[Spot]]:
    """Keep a vehicle detection only if it can be followed back through the previous `frames - 1` frames (within 1.5 m
    each) and moved at least `min_move` metres over them: a single-frame false detection, or a parked vehicle seen
    from a new angle, is dropped. Chosen on this scene against a truth that counted only the transporter (P 0.39 → 0.53,
    R 0.84 → 0.76); with the NovaCarter robot counted too it gives P 0.75 → 0.85 but R 0.73 → 0.53, so the hive drops it."""
    ts = sorted(by_t)
    veh = {t: [s for s in by_t[t] if s.kind == "vehicle" and not any(math.dist((s.x, s.y), q) < 1.5 for q in still)] for t in ts}
    out: dict[float, list[Spot]] = {}
    for i, t in enumerate(ts):
        keep = []
        for v in veh[t]:
            cur, chain = v, [v]
            for j in range(1, frames):
                if i - j < 0:
                    break
                prev = [p for p in veh[ts[i - j]] if math.dist((p.x, p.y), (cur.x, cur.y)) < 1.5]
                if not prev:
                    break
                cur = min(prev, key=lambda p: math.dist((p.x, p.y), (cur.x, cur.y)))
                chain.append(cur)
            if len(chain) >= frames and math.dist((chain[0].x, chain[0].y), (chain[-1].x, chain[-1].y)) >= min_move:
                keep.append(v)
        out[t] = [s for s in by_t[t] if s.kind == "person"] + keep
    return out


def near_misses(by_t: dict[float, list[Spot]], near: float = NEAR_M, gap_s: float = 1.0,
                still: list[tuple[float, float]] | None = None) -> list[dict]:
    """A person within `near` metres of a vehicle that is not parked, episode by episode."""
    still = still if still is not None else parked(by_t)
    hits = []
    for t, ss in sorted(by_t.items()):
        fl = [s for s in ss if s.kind == "vehicle" and not any(math.dist((s.x, s.y), q) < 1.5 for q in still)]
        for p in (s for s in ss if s.kind == "person"):
            for f in fl:
                d = math.dist((p.x, p.y), (f.x, f.y))
                if d < near:
                    hits.append((t, d, p, f))
    episodes: list[dict] = []
    for t, d, p, f in hits:
        e = next((e for e in episodes if t - e["end_s"] <= gap_s and math.dist((p.x, p.y), e["_p"]) < 2.0), None)
        if e:
            e["end_s"] = t
            if d < e["min_distance_m"]:
                e.update(min_distance_m=round(d, 2), at_s=t, camera=p.camera, person_xy=(round(p.x, 1), round(p.y, 1)),
                         forklift_xy=(round(f.x, 1), round(f.y, 1)))
            e["_p"] = (p.x, p.y)
        else:
            episodes.append({"start_s": t, "end_s": t, "at_s": t, "min_distance_m": round(d, 2), "camera": p.camera,
                             "person_xy": (round(p.x, 1), round(p.y, 1)), "forklift_xy": (round(f.x, 1), round(f.y, 1)),
                             "_p": (p.x, p.y)})
    for e in episodes:
        e.pop("_p")
        e["seconds"] = round(e["end_s"] - e["start_s"] + 1 / FPS, 1)
    return episodes


MOVERS = ("Transporter", "NovaCarter")   # both move on their own (87 m and 77 m in the clip); the forklifts never move


def truth(cams: list[str], near: float = GT_NEAR_M, movers: tuple[str, ...] = MOVERS) -> tuple[list[dict], dict]:
    """Near-miss episodes in the 3D ground truth, among objects visible to the chosen cameras, at the same 2 fps: a person
    within `near` m of a vehicle that moves. Until 3 Nov only the Transporter counted, which left out every close call
    with the NovaCarter robot and scored its true detections as false alarms."""
    gt = json.loads((SCENE / "ground_truth.json").read_text())
    step = 30 // FPS
    by_t: dict[float, list[Spot]] = {}
    counts = {"frames": 0, "person_obs": 0, "vehicle_obs": 0}
    for k in sorted(gt, key=int):
        f = int(k)
        if f % step:
            continue
        t = f / 30
        counts["frames"] += 1
        for o in gt[k]:
            kind = "person" if o["object type"] == "Person" else "vehicle" if o["object type"] in movers else None
            if not kind or not set(o.get("2d bounding box visible") or {}) & set(cams):
                continue
            counts[f"{kind}_obs"] += 1
            x, y = o["3d location"][:2]
            by_t.setdefault(t, []).append(Spot(t, kind, x, y, "truth", 1.0))
    return near_misses(by_t, near=near, still=[]), counts


def score(found: list[dict], gold: list[dict], tol_s: float = 2.0, tol_m: float = 2.5) -> dict:
    def overlaps(a: dict, b: dict) -> bool:
        return a["start_s"] - tol_s <= b["end_s"] and b["start_s"] - tol_s <= a["end_s"] \
            and math.dist(a["person_xy"], b["person_xy"]) <= tol_m
    tp_found = sum(any(overlaps(f, g) for g in gold) for f in found)
    tp_gold = sum(any(overlaps(g, f) for f in found) for g in gold)
    return {"found": len(found), "truth": len(gold), "precision": round(tp_found / len(found), 3) if found else None,
            "recall": round(tp_gold / len(gold), 3) if gold else None}


def keyframe(camera: str, t: float, out: Path, width: int = 1280) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(SCENE / "videos" / f"{camera}.mp4"),
                    "-frames:v", "1", "-vf", f"scale={width}:-2", str(out)], check=True)
    return out
