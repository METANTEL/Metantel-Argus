# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""A factory of four halls, each seen through whatever it has: cameras, location tags, or a mix, never complete.

The halls are four scenes of NVIDIA's PhysicalAI-SmartSpaces (CC BY 4.0), shown as one site on one clock:

    A  Warehouse_015   13 cameras                         people, forklifts, the transporter, a mobile robot
    B  Warehouse_016   12 cameras                         people beside humanoid robots, the transporter
    C  Warehouse_000   tags on every vehicle; 6 of its    people, forklifts, mobile robots, the transporter
                       25 cameras for people
    D  Warehouse_010   location tags only, worn by 70%    people, a mobile robot, the transporter
                       of the people

Cameras are seen with SAM 3.1 and put on the floor through each camera's calibration; tags are the scene's recorded
positions (its 3D ground truth), thinned to the people who wear them. Everything is compiled, with no model, into what
the memory keeps: who is where by zone every 10 seconds, every vehicle's state, close calls, a per-minute summary of
each hall, and what each hall's sources can and cannot see. Raw frames and positions stay here.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ...config import DATA
from ...perception import floor as F

ROOT = DATA / "smartspaces"
CLOCK = "2026-11-04 08:00:00"             # the four scenes share one shift clock
FPS_MEM = 2                               # what the memory keeps: positions twice a second
ZONE_M = 5.0                              # a zone is a 5 m square of floor
NEAR_M = 1.5
KINDS = {"Person": "person", "Forklift": "forklift", "Transporter": "transporter", "NovaCarter": "robot",
         "FourierGR1T2": "humanoid"}
VEHICLES = ("forklift", "transporter", "robot")
HALLS = {
    "A": {"scene": "Warehouse_015", "people": "cameras", "vehicles": "cameras", "cameras": None},
    "B": {"scene": "Warehouse_016", "people": "cameras", "vehicles": "cameras", "cameras": None},
    "C": {"scene": "Warehouse_000", "people": "cameras", "vehicles": "tags",
          "cameras": ["Camera_0000", "Camera_0004", "Camera_0008", "Camera_0012", "Camera_0016", "Camera_0020"]},
    "D": {"scene": "Warehouse_010", "people": "tags", "vehicles": "tags", "cameras": [], "badge_share": 0.7},
}
CONCEPTS = {"A": ("person", "vehicle"), "B": ("person", "humanoid robot", "vehicle"), "C": ("person",), "D": ()}


def scene_dir(hall: str) -> Path:
    return ROOT / HALLS[hall]["scene"]


def calibration(hall: str) -> dict[str, dict]:
    return {s["id"]: s for s in json.loads((scene_dir(hall) / "calibration.json").read_text())["sensors"] if s["type"] == "camera"}


def cameras(hall: str) -> list[str]:
    chosen = HALLS[hall]["cameras"]
    return sorted(calibration(hall)) if chosen is None else list(chosen)


def map_transform(hall: str) -> tuple[float, float, float, int]:
    """(scale px/m, tx, ty, map height px): map pixel = ((x + tx)·s, H − (y + ty)·s)."""
    s = next(iter(calibration(hall).values()))
    import struct
    with (scene_dir(hall) / "map.png").open("rb") as f:
        head = f.read(24)
    h = struct.unpack(">I", head[20:24])[0]
    return s["scaleFactor"], s["translationToGlobalCoordinates"]["x"], s["translationToGlobalCoordinates"]["y"], h


def to_map(hall: str, x: float, y: float) -> tuple[float, float]:
    s, tx, ty, h = map_transform(hall)
    return (x + tx) * s, h - (y + ty) * s


# ── perception: SAM 3.1 per camera, cached per scene ─────────────────────────────────────────────────────────────

def clip(hall: str, camera: str) -> Path:
    out = scene_dir(hall) / "clips" / f"{camera}_{F.FPS}fps_{F.W}.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(scene_dir(hall) / "videos" / f"{camera}.mp4"), "-vf",
                        f"fps={F.FPS},scale={F.W}:{F.H}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-an",
                        str(out)], check=True)
    return out


def detect(models, hall: str, camera: str, dense: bool = True, tagged: bool = True) -> dict:
    """SAM boxes per concept for one camera of one hall; Hall A reuses the whole-view detections made on 2–3 Nov.
    Where the camera's supervisor had the view looked at in tiles (argus/perception/tiles.py), its people are those; where
    it had the machines named and followed (argus/perception/naming.py), its vehicles are those, each with its kind."""
    if hall == "A":
        out = json.loads((F.CLIPS / f"{camera}_sam.json").read_text())
        out = _dense(hall, camera, out) if dense else out
        return _tagged(hall, camera, out) if tagged else out
    cache = scene_dir(hall) / "sam" / f"{camera}.json"
    out = json.loads(cache.read_text()) if cache.exists() else {}
    todo = [c for c in CONCEPTS[hall] if c not in out]
    if todo:
        path = clip(hall, camera)
        frames = int(subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                     "stream=nb_read_frames", "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
        fid = models.upload(path)
        for c in todo:
            out[c] = models.segment(c, video_file_id=fid, frames=frames)
        out["_frames"] = frames
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out))
    out = _dense(hall, camera, out) if dense else out
    return _tagged(hall, camera, out) if tagged else out


def _tagged(hall: str, camera: str, out: dict) -> dict:
    p = scene_dir(hall) / "sam_tagged" / f"{camera}.json"
    if not p.exists():
        return out
    t = json.loads(p.read_text())
    kinds = {int(i): v["kind"] for i, v in t["tags"].items()}
    # one machine named twice (two naming rounds, two ids) is one box a frame: the earlier name keeps it
    keep, by_frame = [], {}
    for b in sorted(t["boxes"], key=lambda b: (b["frame"], b["obj"])):
        same = [k for k in by_frame.get(b["frame"], []) if kinds.get(k["obj"]) == kinds.get(b["obj"]) and _iou(k, b) > 0.5]
        if not same:
            by_frame.setdefault(b["frame"], []).append(b)
            keep.append(b)
    return {**out, "vehicle": keep, "_kinds": kinds}


def _dense(hall: str, camera: str, out: dict) -> dict:
    for concept in ("person", "humanoid robot"):
        p = scene_dir(hall) / "sam_dense" / f"{camera}_{concept.replace(' ', '_')}.json"
        if p.exists():
            out = {**out, concept: json.loads(p.read_text())["boxes"]}
    return out


def camera_spots(hall: str) -> list[F.Spot]:
    """Every detection of the hall's cameras on its floor plan. In Hall B a 'humanoid robot' box over a 'person' box
    is the robot; in Hall C only people are taken from cameras (vehicles carry tags)."""
    cal = calibration(hall)
    spots: list[F.Spot] = []
    for cam in cameras(hall):
        det = detect(None, hall, cam)
        hinv = F._inv3(cal[cam]["homography"])
        hum = {(b["frame"]): [] for b in det.get("humanoid robot", [])}
        for b in det.get("humanoid robot", []):
            hum[b["frame"]].append(b)
        for concept, kind in (("person", "person"), ("humanoid robot", "humanoid"), ("vehicle", "vehicle")):
            if hall == "C" and kind != "person":
                continue
            for b in det.get(concept, []):
                if kind == "person" and any(_iou(b, h) > 0.5 for h in hum.get(b["frame"], [])):
                    continue
                sx, sy = F.SRC_W / b["w"], F.SRC_H / b["h"]
                fx, fy = F.to_floor(hinv, (b["x1"] + b["x2"]) / 2 * sx, b["y2"] * sy)
                if abs(fx) > 200 or abs(fy) > 200:
                    continue
                spots.append(F.Spot(b["frame"] / F.FPS, kind, fx, fy, cam, b.get("c"),
                                    (b["x1"] * sx, b["y1"] * sy, b["x2"] * sx, b["y2"] * sy)))
    return spots


def _iou(a: dict, b: dict) -> float:
    ix = max(0, min(a["x2"], b["x2"]) - max(a["x1"], b["x1"]))
    iy = max(0, min(a["y2"], b["y2"]) - max(a["y1"], b["y1"]))
    inter = ix * iy
    union = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"]) + (b["x2"] - b["x1"]) * (b["y2"] - b["y1"]) - inter
    return inter / union if union else 0.0


# ── tracks: one object over time, whichever source saw it ────────────────────────────────────────────────────────

@dataclass
class Track:
    id: str
    kind: str                     # person | humanoid | forklift | transporter | robot | vehicle (a camera cannot tell which)
    source: str                   # camera | tag
    t: list[float] = field(default_factory=list)
    x: list[float] = field(default_factory=list)
    y: list[float] = field(default_factory=list)
    parked: bool = False          # never left a few metres' circle: a parked vehicle, whatever its jitter says

    def at(self, t: float) -> tuple[float, float] | None:
        """Position at time t, interpolated; None outside the track or across a gap of more than 1.5 s."""
        import bisect
        if not self.t or t < self.t[0] or t > self.t[-1]:
            return None
        i = bisect.bisect_left(self.t, t)
        if i < len(self.t) and self.t[i] == t:
            return self.x[i], self.y[i]
        a, b = i - 1, i
        if self.t[b] - self.t[a] > 1.5:
            return None
        u = (t - self.t[a]) / (self.t[b] - self.t[a])
        return self.x[a] + (self.x[b] - self.x[a]) * u, self.y[a] + (self.y[b] - self.y[a]) * u


def tag_tracks(hall: str, kinds: tuple[str, ...], every: int = 1, share: float = 1.0) -> list[Track]:
    """Recorded positions as a location system would report them: `every` n-th frame (30 fps / n), for the object
    kinds that carry tags, and for people only the `share` who wear a badge (chosen once, the same every run)."""
    gt = json.loads((scene_dir(hall) / "ground_truth.json").read_text())
    tracks: dict[tuple, Track] = {}
    for k in sorted(gt, key=int):
        f = int(k)
        if f % every:
            continue
        for o in gt[k]:
            kind = KINDS.get(o["object type"])
            if kind not in kinds:
                continue
            key = (kind, o["object id"])
            tr = tracks.get(key)
            if tr is None:
                tr = tracks[key] = Track(f"{hall}-{kind}-{o['object id']}", kind, "tag")
            tr.t.append(f / 30)
            tr.x.append(o["3d location"][0])
            tr.y.append(o["3d location"][1])
    out = list(tracks.values())
    if share < 1.0:
        people = sorted(tr.id for tr in out if tr.kind == "person")
        keep = set(random.Random(f"badges-{hall}").sample(people, round(len(people) * share)))
        out = [tr for tr in out if tr.kind != "person" or tr.id in keep]
    return out


def _smooth(v: list[float], k: int = 2) -> list[float]:
    return [sum(v[max(0, i - k):i + k + 1]) / len(v[max(0, i - k):i + k + 1]) for i in range(len(v))]


def camera_tracks(hall: str, near_m: float = 2.0, agree_share: float = 0.5) -> list[Track]:
    """SAM 3.1 follows each object through a camera's video; each camera's tracks are put on the floor plan and
    smoothed, and tracks from different cameras that stay within a metre or two of each other are one object."""
    cal = calibration(hall)
    per: dict[tuple, list[tuple[float, float, float]]] = {}
    for cam in cameras(hall):
        det = detect(None, hall, cam)
        hinv = F._inv3(cal[cam]["homography"])
        hum: dict[int, list[dict]] = {}
        for b in det.get("humanoid robot", []):
            hum.setdefault(b["frame"], []).append(b)
        for concept, kind in (("person", "person"), ("humanoid robot", "humanoid"), ("vehicle", "vehicle")):
            if hall == "C" and kind != "person":
                continue
            for b in det.get(concept, []):
                if kind == "person" and any(_iou(b, h) > 0.5 for h in hum.get(b["frame"], [])):
                    continue
                sx, sy = F.SRC_W / b["w"], F.SRC_H / b["h"]
                fx, fy = F.to_floor(hinv, (b["x1"] + b["x2"]) / 2 * sx, b["y2"] * sy)
                if abs(fx) > 200 or abs(fy) > 200:
                    continue
                per.setdefault((cam, kind, b["obj"]), []).append((b["frame"] / F.FPS, fx, fy))
    singles: list[tuple[str, str, dict[float, tuple[float, float]]]] = []
    for (cam, kind, obj), pts in per.items():
        pts.sort()
        if len(pts) < 6:
            continue
        xs, ys = _smooth([p[1] for p in pts]), _smooth([p[2] for p in pts])
        singles.append((cam, kind, {p[0]: (xs[i], ys[i]) for i, p in enumerate(pts)}))
    # One object seen by several cameras: union the tracks that agree where they overlap.
    parent = list(range(len(singles)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    near = {"person": near_m, "humanoid": near_m, "vehicle": 2.5}
    for i in range(len(singles)):
        ci, ki, ti = singles[i]
        for j in range(i + 1, len(singles)):
            cj, kj, tj = singles[j]
            if ki != kj or ci == cj:
                continue
            common = ti.keys() & tj.keys()
            if len(common) < 8:
                continue
            agree = sum(1 for t in common if math.dist(ti[t], tj[t]) < near[ki])
            if agree >= agree_share * len(common):
                parent[root(i)] = root(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(singles)):
        groups.setdefault(root(i), []).append(i)
    out = []
    for n, members in enumerate(groups.values(), 1):
        kind = singles[members[0]][1]
        times = sorted(set().union(*(singles[m][2].keys() for m in members)))
        tr = Track(f"{hall}-{kind}-c{n}", kind, "camera")
        for t in times:
            pts = [singles[m][2][t] for m in members if t in singles[m][2]]
            tr.t.append(t)
            tr.x.append(sum(p[0] for p in pts) / len(pts))
            tr.y.append(sum(p[1] for p in pts) / len(pts))
        out.append(tr)
    return out


def vehicle_tracks(hall: str, fuse_m: float = 2.0, gate_m: float = 2.0, coast_s: float = 3.0) -> list[Track]:
    """Vehicles on the floor plan from every camera at once. At each instant, detections from different cameras within
    `fuse_m` are one vehicle (a camera's own detections are distinct vehicles); from instant to instant a vehicle goes
    to the nearest fused position within `gate_m` and is kept for `coast_s` without one. A track whose positions
    never leave a 2.5 m circle is parked: the jitter of a forklift with people walking in front of it is not motion."""
    cal = calibration(hall)
    by_t: dict[float, list[tuple[str, float, float, float]]] = {}
    # Positions come from SAM's own vehicle detections, which follow each machine in more frames; names come from the
    # machines the tagger named (argus/perception/naming.py), put on the floor the same way and matched to the tracks below.
    kinds_of = {"forklift": "forklift", "transporter": "transporter", "mobile robot": "robot", "humanoid robot": "humanoid"}
    named_at: dict[float, list[tuple[float, float, str]]] = {}
    for cam in cameras(hall):
        hinv = F._inv3(cal[cam]["homography"])
        for b in detect(None, hall, cam, tagged=False).get("vehicle", []):
            sx, sy = F.SRC_W / b["w"], F.SRC_H / b["h"]
            fx, fy = F.to_floor(hinv, (b["x1"] + b["x2"]) / 2 * sx, b["y2"] * sy)
            if abs(fx) < 200 and abs(fy) < 200:
                by_t.setdefault(b["frame"] / F.FPS, []).append((cam, fx, fy, b.get("c") or 0.5, ""))
        tagged = detect(None, hall, cam)
        names = tagged.get("_kinds") or {}
        for b in tagged.get("vehicle", []) if names else []:
            sx, sy = F.SRC_W / b["w"], F.SRC_H / b["h"]
            fx, fy = F.to_floor(hinv, (b["x1"] + b["x2"]) / 2 * sx, b["y2"] * sy)
            if abs(fx) < 200 and abs(fy) < 200 and names.get(b["obj"]) in kinds_of:
                named_at.setdefault(b["frame"] / F.FPS, []).append((fx, fy, kinds_of[names[b["obj"]]]))
    live: list[dict] = []
    done: list[dict] = []
    for t in sorted(by_t):
        clusters: list[dict] = []
        for cam, x, y, c, kind in sorted(by_t[t], key=lambda d: -d[3]):
            cl = next((k for k in clusters if cam not in k["cams"] and math.dist((x, y), k["c"]) < fuse_m), None)
            if cl is None:
                clusters.append({"cams": {cam}, "pts": [(x, y)], "c": (x, y), "kinds": [kind] if kind else []})
            else:
                cl["cams"].add(cam)
                cl["pts"].append((x, y))
                if kind:
                    cl["kinds"].append(kind)
                cl["c"] = (_median([p[0] for p in cl["pts"]]), _median([p[1] for p in cl["pts"]]))
        pairs = sorted(((math.dist(tr["p"][-1][1:3], cl["c"]), i, j) for i, tr in enumerate(live)
                        for j, cl in enumerate(clusters)), key=lambda p: p[0])
        used_t, used_c = set(), set()
        for d, i, j in pairs:
            if d > gate_m * max(1.0, (t - live[i]["p"][-1][0]) / 0.5) or i in used_t or j in used_c:
                continue
            live[i]["p"].append((t, *clusters[j]["c"], len(clusters[j]["cams"])))
            live[i].setdefault("kinds", []).extend(clusters[j]["kinds"])
            used_t.add(i)
            used_c.add(j)
        for j, cl in enumerate(clusters):
            if j not in used_c:
                live.append({"p": [(t, *cl["c"], len(cl["cams"]))], "kinds": list(cl["kinds"])})
        done += [tr for tr in live if t - tr["p"][-1][0] > coast_s]
        live = [tr for tr in live if t - tr["p"][-1][0] <= coast_s]
    out: list[Track] = []
    for tr in sorted(done + live, key=lambda tr: tr["p"][0][0]):
        ts, xs, ys = [p[0] for p in tr["p"]], _smooth([p[1] for p in tr["p"]]), _smooth([p[2] for p in tr["p"]])
        seen_twice = sum(p[3] >= 2 for p in tr["p"]) / len(tr["p"])
        if ts[-1] - ts[0] < 8 or seen_twice < 0.4:      # a glimpse, or one camera's view of a vehicle's edge: not a vehicle
            continue
        mx, my = _median(xs), _median(ys)
        spread = sorted(math.dist((x, y), (mx, my)) for x, y in zip(xs, ys))[int(0.9 * (len(xs) - 1))]
        parked = spread < 2.5 and ts[-1] - ts[0] >= 30
        twin = next((o for o in out if o.parked and parked and math.dist((_median(o.x), _median(o.y)), (mx, my)) < 3.0), None)
        if twin is None:                                 # two cameras' views of one parked forklift are one forklift
            votes = [min(named_at[t], key=lambda q: math.dist(q[:2], (x, y)))[2] for t, x, y in zip(ts, xs, ys)
                     if named_at.get(t) and min(math.dist(q[:2], (x, y)) for q in named_at[t]) < 2.5]
            kind = max(set(votes), key=votes.count) if votes else "vehicle"     # what the tagger named it, most often
            n = sum(1 for o in out if o.kind == kind) + 1
            out.append(Track(f"{hall}-{kind}-{'v' if kind == 'vehicle' else ''}{n}", kind, "camera", ts, xs, ys, parked=parked))
    return out


def tracks(hall: str) -> list[Track]:
    h = HALLS[hall]
    out: list[Track] = []
    if h["people"] == "cameras":
        # Followed in tiles, with the feet in view, two cameras' tracks of one person agree within a metre (set on Hall A,
        # all 13 cameras: 68.5 people at an instant against 73 present, 92 close calls against 110 in the truth). From the
        # whole view, a person's box is often cut and two metres is the tolerance.
        dense = any((scene_dir(hall) / "sam_dense").glob("*_person.json"))
        out += [tr for tr in camera_tracks(hall, *((1.0, 0.5) if dense else (2.0, 0.5))) if tr.kind in ("person", "humanoid")]
    if h["vehicles"] == "cameras":
        out += vehicle_tracks(hall)
    tag_kinds = tuple(k for k, src in (("person", h["people"]), ("forklift", h["vehicles"]), ("transporter", h["vehicles"]),
                                       ("robot", h["vehicles"]), ("humanoid", h["people"])) if src == "tags")
    if tag_kinds:
        out += tag_tracks(hall, tag_kinds, every=30 // FPS_MEM, share=h.get("badge_share", 1.0))
    return out


# ── what the memory keeps ────────────────────────────────────────────────────────────────────────────────────────

def zone(x: float, y: float) -> str:
    col = int(math.floor(x / ZONE_M)) + 10
    row = int(math.floor(y / ZONE_M)) + 10
    return f"{chr(ord('A') + max(0, min(25, col)))}{max(0, row)}"


def stamp(t: float) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(CLOCK, "%Y-%m-%d %H:%M:%S") + timedelta(seconds=t)).strftime("%Y-%m-%d %H:%M:%S")


def _median(v: list[float]) -> float:
    s = sorted(v)
    return (s[len(s) // 2] + s[(len(s) - 1) // 2]) / 2


def moving(tr: Track, i: int, window: int = 4) -> float:
    """Speed in m/s around sample i. Tags: over about four seconds. Cameras: a vehicle's position jumps by a metre or
    more when people walk in front of it, so it is where it stood over the two to six seconds after, against where it
    stood over the two to six seconds before (medians); a parked vehicle is not moving whatever the jitter."""
    if tr.parked:
        return 0.0
    if tr.source != "camera":
        a, b = max(0, i - window), min(len(tr.t) - 1, i + window)
        if b == a or tr.t[b] == tr.t[a]:
            return 0.0
        return math.dist((tr.x[a], tr.y[a]), (tr.x[b], tr.y[b])) / (tr.t[b] - tr.t[a])
    import bisect
    t = tr.t[i]
    lo0, lo1 = bisect.bisect_left(tr.t, t - 6), bisect.bisect_right(tr.t, t - 2)
    hi0, hi1 = bisect.bisect_left(tr.t, t + 2), bisect.bisect_right(tr.t, t + 6)
    before = range(lo0, lo1) if lo1 - lo0 >= 3 else range(max(0, i - 2), i + 1)
    after = range(hi0, hi1) if hi1 - hi0 >= 3 else range(i, min(len(tr.t), i + 3))
    if not before or not after:
        return 0.0
    pa = (_median([tr.x[k] for k in before]), _median([tr.y[k] for k in before]))
    pb = (_median([tr.x[k] for k in after]), _median([tr.y[k] for k in after]))
    dt = _median([tr.t[k] for k in after]) - _median([tr.t[k] for k in before])
    return math.dist(pa, pb) / dt if dt > 0 else 0.0


def close_calls(hall: str, trs: list[Track], step: float = 0.5, near: float = NEAR_M) -> list[dict]:
    """A person within `near` m of a moving vehicle, episode by episode (a gap of over a second ends one)."""
    people = [tr for tr in trs if tr.kind in ("person",)]
    vehicles = [tr for tr in trs if tr.kind in VEHICLES + ("vehicle", "humanoid")]
    end_t = max((tr.t[-1] for tr in trs), default=0)
    eps: list[dict] = []
    open_: dict[tuple, dict] = {}
    t = 0.0
    while t <= end_t:
        live_v = []
        for v in vehicles:
            p = v.at(t)
            if p is None:
                continue
            import bisect
            i = min(len(v.t) - 1, bisect.bisect_left(v.t, t))
            if moving(v, i) >= 0.2 or v.kind == "humanoid":
                live_v.append((v, p))
        seen = set()
        for pe in people:
            pp = pe.at(t)
            if pp is None:
                continue
            for v, vp in live_v:
                d = math.dist(pp, vp)
                if d < near:
                    key = (pe.id, v.id)
                    seen.add(key)
                    e = open_.get(key)
                    if e is None:
                        e = open_[key] = {"hall": hall, "start_s": t, "end_s": t, "min_m": d, "zone": zone(*pp),
                                          "vehicle": v.id, "vehicle_kind": v.kind, "person": pe.id,
                                          "source": "+".join(sorted({pe.source, v.source}))}
                    e["end_s"], e["min_m"] = t, min(e["min_m"], d)
        for key in [k for k in open_ if k not in seen and t - open_[k]["end_s"] > 1.0]:
            eps.append(open_.pop(key))
        t = round(t + step, 3)
    eps += list(open_.values())
    return sorted(eps, key=lambda e: e["start_s"])


def tables(hall: str, trs: list[Track]) -> dict[str, list[dict]]:
    h = HALLS[hall]
    occ: dict[tuple, dict] = {}
    veh: list[dict] = []
    walked: dict[int, float] = {}
    for tr in trs:
        for i, t in enumerate(tr.t):
            b = int(t // 10) * 10
            z = zone(tr.x[i], tr.y[i])
            row = occ.setdefault((b, z), {"time": stamp(b), "hall": hall, "zone": z, "people": set(), "vehicles_moving": set(),
                                          "vehicles_idle": set(), "humanoids": set()})
            if tr.kind == "person":
                row["people"].add(tr.id)
                if i >= 4 and i % 4 == 0:            # two-second steps: camera jitter would otherwise add distance
                    walked[int(t // 60)] = walked.get(int(t // 60), 0) + math.dist((tr.x[i - 4], tr.y[i - 4]), (tr.x[i], tr.y[i]))
            elif tr.kind == "humanoid":
                row["humanoids"].add(tr.id)
            else:
                (row["vehicles_moving"] if moving(tr, i) >= 0.2 else row["vehicles_idle"]).add(tr.id)
        if tr.kind in VEHICLES + ("vehicle", "humanoid"):
            for i in range(0, len(tr.t), FPS_MEM * 5):           # every 5 seconds
                veh.append({"time": stamp(tr.t[i]), "hall": hall, "vehicle": tr.id, "kind": tr.kind, "zone": zone(tr.x[i], tr.y[i]),
                            "state": "moving" if moving(tr, i) >= 0.2 else "idle", "speed_mps": round(moving(tr, i), 2),
                            "x_m": round(tr.x[i], 1), "y_m": round(tr.y[i], 1), "source": tr.source})
    occ_rows = [{**{k: v for k, v in r.items() if not isinstance(v, set)}, "people": len(r["people"]),
                 "humanoids": len(r["humanoids"]), "vehicles_moving": len(r["vehicles_moving"]),
                 "vehicles_idle": len(r["vehicles_idle"])} for r in occ.values()]
    calls = close_calls(hall, trs)
    call_rows = [{"start": stamp(e["start_s"]), "end": stamp(e["end_s"]), "hall": hall, "zone": e["zone"],
                  "vehicle": e["vehicle"], "vehicle_kind": e["vehicle_kind"], "min_distance_m": round(e["min_m"], 2),
                  "seconds": round(e["end_s"] - e["start_s"] + 0.5, 1), "source": e["source"]} for e in calls]
    minutes = []
    end = max((tr.t[-1] for tr in trs), default=0)
    for m in range(int(end // 60) + 1):
        lo, hi = m * 60, (m + 1) * 60
        ppl = {tr.id for tr in trs if tr.kind == "person" and any(lo <= t < hi for t in tr.t)}
        vm = {r["vehicle"] for r in veh if r["state"] == "moving" and lo <= _secs(r["time"]) < hi}
        vi = {r["vehicle"] for r in veh if r["state"] == "idle" and lo <= _secs(r["time"]) < hi} - vm
        minutes.append({"time": stamp(lo), "hall": hall, "people_seen": len(ppl), "vehicles_moving": len(vm), "vehicles_idle": len(vi),
                        "close_calls": sum(1 for e in calls if lo <= e["start_s"] < hi),
                        "metres_walked": round(walked.get(m, 0)), "people_source": h["people"], "vehicle_source": h["vehicles"]})
    return {"occupancy": sorted(occ_rows, key=lambda r: (r["time"], r["zone"])), "vehicles": veh, "close_calls": call_rows,
            "minutes": minutes}


def _secs(stamp_: str) -> float:
    from datetime import datetime
    return (datetime.strptime(stamp_, "%Y-%m-%d %H:%M:%S") - datetime.strptime(CLOCK, "%Y-%m-%d %H:%M:%S")).total_seconds()


def sources() -> list[dict]:
    """What each hall's sources can and cannot see: the memory says so, so every answer can."""
    return [
        {"hall": "A", "people": "13 cameras (SAM 3.1)", "vehicles": "13 cameras (SAM 3.1); a camera sees 'a vehicle', not which",
         "coverage": "most of the floor; people hidden by racks or other people are missed"},
        {"hall": "B", "people": "12 cameras (SAM 3.1); humanoid robots told apart from people", "vehicles": "12 cameras (SAM 3.1)",
         "coverage": "most of the floor"},
        {"hall": "C", "people": "6 of 25 cameras (SAM 3.1)", "vehicles": "location tags on every forklift, robot and the transporter",
         "coverage": "vehicles everywhere; people only where those 6 cameras look"},
        {"hall": "D", "people": "location badges, worn by 70% of the people", "vehicles": "location tags",
         "coverage": "no cameras; 3 in 10 people are not tracked"},
    ]


def whatif_shift(trs: list[Track], vehicle: str, shifts: range = range(-60, 61, 15)) -> list[dict]:
    """The same vehicle run earlier or later against the people as they actually moved: close calls for each shift in
    seconds. People are assumed to move as recorded, which a real change would not guarantee."""
    v = next(tr for tr in trs if tr.id == vehicle)
    out = []
    for s in shifts:
        moved = Track(v.id, v.kind, v.source, [t + s for t in v.t], list(v.x), list(v.y))
        others = [tr for tr in trs if tr.id != vehicle and tr.kind == "person"]
        out.append({"shift_s": s, "close_calls": len(close_calls("x", others + [moved]))})
    return out


def whatif_avoid(trs: list[Track], vehicle: str, zones: set[str]) -> dict:
    """Close calls this vehicle had inside `zones`: what keeping it out of them could at most avoid."""
    calls = [e for e in close_calls("x", trs) if e["vehicle"] == vehicle]
    inside = [e for e in calls if e["zone"] in zones]
    return {"vehicle": vehicle, "close_calls": len(calls), "inside_zones": len(inside), "zones": sorted(zones)}
