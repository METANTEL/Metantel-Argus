# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The camera supervisor: a hive member that watches over SAM 3.1 on one hall's cameras.

It holds SAM's output on every camera to the invariants of `argus.hive.supervise`: is the view followed to its limit
(`at_limit`, per frame and per request), is a "moving" vehicle really moving (`implausible`, from the fused floor
tracks), and, with the site's description of its machines, is a machine named and followed (`name_machines`). Where a check
fires it looks for itself (the frame, with what SAM boxed drawn on it), chooses a remedy, and the remedy is the site's to
carry out: look again in tiles (`argus.perception.tiles`), name the machines from close crops and have SAM follow the names
(`argus.perception.naming`), or correct the memory.
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...hive.supervise import Issue, Supervisor, at_limit, implausible
from ...perception import floor as F
from ...perception import naming as T
from ...perception import tiles as P
from . import feed as FX


def frame(hall: str, cam: str, t: float, boxes: list[tuple[tuple, str, int]], out: Path, crop: tuple | None = None,
          width: int = 1280) -> str:
    """One frame of a camera at `t` seconds with boxes drawn (camera pixels), optionally cut to `crop` (x, y, w, h)."""
    if not out.exists():
        draw = []
        for (x1, y1, x2, y2), col, thick in boxes:
            x1, y1 = max(0, min(1915, x1)), max(0, min(1075, y1))
            w, h = max(4, min(1919 - x1, x2 - x1)), max(4, min(1079 - y1, y2 - y1))
            draw.append(f"drawbox=x={x1:.0f}:y={y1:.0f}:w={w:.0f}:h={h:.0f}:color={col}@0.9:t={thick}")
        if crop:
            draw.append("crop={2}:{3}:{0}:{1}".format(*[int(v) for v in crop]))
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(FX.scene_dir(hall) / "videos" / f"{cam}.mp4"),
                        "-frames:v", "1", "-vf", ",".join(draw + [f"scale={width}:-2"]), "-q:v", "3", str(out)], check=True)
    return str(out)


def project(cal: dict, x: float, y: float) -> tuple[float, float]:
    h = cal["homography"]
    u, v, w = (h[0][0] * x + h[0][1] * y + h[0][2], h[1][0] * x + h[1][1] * y + h[1][2], h[2][0] * x + h[2][1] * y + h[2][2])
    return u / w, v / w


def boxes_at(det: list[dict], t: float, colour: str = "cyan", thick: int = 3) -> list[tuple[tuple, str, int]]:
    f = int(round(t * F.FPS))
    return [((b["x1"] * F.SRC_W / b["w"], b["y1"] * F.SRC_H / b["h"], b["x2"] * F.SRC_W / b["w"], b["y2"] * F.SRC_H / b["h"]),
             colour, thick) for b in det if b["frame"] == f]


@dataclass
class CameraSupervisor(Supervisor):
    """Watches over SAM 3.1 on one hall's cameras: is everyone in view followed, and is a moving vehicle moving?"""
    hall: str = "A"

    def people_check(self, cam: str, det: list[dict]) -> Issue | None:
        """SAM 3.1 stops at 16 objects in a frame, and follows at most 16 in one request: either is the limit."""
        per: dict[int, int] = {}
        for b in det:
            per[b["frame"]] = per.get(b["frame"], 0) + 1
        followed = len({b["obj"] for b in det})
        return at_limit(per, P.LIMIT, cam, concept="person", most_in_a_frame=max(per.values(), default=0),
                        followed_in_the_request=followed) or \
            at_limit({"the request": followed}, P.TRACKED, cam, share=1.0, concept="person",
                     most_in_a_frame=max(per.values(), default=0), followed_in_the_request=followed)

    def count(self, issue: Issue, det: list[dict], t: float, tag: str, knowledge: list[str]) -> dict:
        """The supervisor's own count of the people in one frame, with the system's boxes drawn; it chooses the remedy."""
        drawn = boxes_at(det, t)
        issue.images = [frame(self.hall, issue.subject, t, drawn, self.out_dir / f"{issue.subject}_{tag}_{t:.0f}.jpg")]
        issue.evidence.update(boxes_in_frame=len(drawn), at_s=t)
        return self.judge(issue, f"{issue.subject} in Hall {self.hall}, {t:.0f} s into the shift; a cyan box on each person "
                          "the perception model found. First count the people you can see yourself (far away, partly hidden "
                          "and semi-transparent ones too: this is a simulation) and put the count and how many have no box "
                          "in your finding.", knowledge, ["split", "reprompt", "accept"])

    def vehicle_check(self, tr: FX.Track, moving_share: float, close_calls: int) -> Issue | None:
        mx, my = FX._median(tr.x), FX._median(tr.y)
        spread = sorted(math.dist((x, y), (mx, my)) for x, y in zip(tr.x, tr.y))[int(0.9 * (len(tr.x) - 1))]
        if moving_share < 0.2 or spread >= 3.0 or tr.t[-1] - tr.t[0] < 30:
            return None
        return implausible(tr.id, f"memory says it moved {moving_share:.0%} of the shift, yet 90% of its positions lie within "
                           f"{spread:.1f} m of one spot", moving_share=round(moving_share, 2), close_calls=close_calls,
                           spread_m=round(spread, 1), median_xy=[round(mx, 1), round(my, 1)], zone=FX.zone(mx, my))

    def best_view(self, x: float, y: float, t: float) -> tuple[str, tuple] | None:
        """The camera that sees a floor point largest at `t`, and the vehicle box it detected there."""
        cal = FX.calibration(self.hall)
        best = None
        f = int(round(t * F.FPS))
        for cam in FX.cameras(self.hall):
            u, v = project(cal[cam], x, y)
            if not (60 < u < F.SRC_W - 60 and 60 < v < F.SRC_H - 20):
                continue
            for b in FX.detect(None, self.hall, cam).get("vehicle", []):
                if b["frame"] != f:
                    continue
                sx, sy = F.SRC_W / b["w"], F.SRC_H / b["h"]
                box = (b["x1"] * sx, b["y1"] * sy, b["x2"] * sx, b["y2"] * sy)
                if box[0] - 120 <= u <= box[2] + 120 and box[1] - 120 <= v <= box[3] + 120:
                    area = (box[2] - box[0]) * (box[3] - box[1])
                    if best is None or area > best[2]:
                        best = (cam, box, area)
        return (best[0], best[1]) if best else None

    def look_at_vehicle(self, issue: Issue, tr: FX.Track, knowledge: list[str]) -> dict:
        """Three frames a minute apart from the camera that sees the vehicle best, cut around it; it chooses the remedy."""
        mx, my = issue.evidence["median_xy"]
        times = [tr.t[0] + 20, tr.t[0] + 80, tr.t[0] + 140]
        view = next((v for v in (self.best_view(mx, my, t) for t in times) if v), None)
        if not view:
            return {}
        cam, box = view
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        w = min(F.SRC_W, max(720, (box[2] - box[0]) * 3.2))
        h = w * 9 / 16
        crop = (max(0, min(F.SRC_W - w, cx - w / 2)), max(0, min(F.SRC_H - h, cy - h / 2)), w, h)
        issue.images = [frame(self.hall, cam, t, [(box, "orange", 4)], self.out_dir / f"{tr.id}_{cam}_{t:.0f}.jpg", crop, 960)
                        for t in times]
        issue.evidence["camera"] = cam
        return self.judge(issue, f"three frames from {cam}, a minute apart, cut around the vehicle the memory calls {tr.id} "
                          "(orange box at the first frame's position). Say whether it is being driven or stands parked while "
                          "people walk past, what kind of vehicle it is, and whether anyone is at its controls.",
                          knowledge, ["rederive", "correct", "accept", "ask_people"])


def name_machines(sup: "CameraSupervisor", models, cam: str, knowledge: list[str], rounds: int = 2) -> dict:
    """The camera supervisor has the machines in one camera named and followed (argus/perception/naming.py). Every machine SAM
    proposes on the first frame is looked at close up by Muse Spark and named; SAM follows each name with a box prompt.
    Where a named machine is lost, or SAM proposes one no name covers, the new proposals at that moment are looked at
    and named (a machine of the same kind reappearing near where one was lost keeps its name), and SAM is prompted again
    from there. Saved per camera; each naming round is an issue in the supervisor's log."""
    hall = sup.hall
    det = FX.detect(None, hall, cam, dense=False, tagged=False).get("vehicle", [])
    if not det:
        return {}
    frames = FX.detect(None, hall, cam, dense=False, tagged=False).get("_frames") or 600
    tags: dict[int, dict] = {}
    prompts: list[dict] = []
    cache = FX.scene_dir(hall) / "sam_tagged" / f"{cam}_follow.json"

    def last_box(i: int, before: int, boxes: list[dict]) -> tuple | None:
        seen = [b for b in boxes if b["obj"] == i and b["frame"] < before]
        if not seen:
            return None
        b = seen[-1]
        return (b["x1"] * T.W // b["w"], b["y1"] * T.H // b["h"], b["x2"] * T.W // b["w"], b["y2"] * T.H // b["h"])

    def name(frame: int, boxes: list[dict], why: str) -> None:
        props = T.proposals(hall, cam, frame)
        named, seen = [], []
        for box in props:
            if any(_box_iou(box, b) > 0.5 for b, _ in seen):
                continue
            c = T.classify(sup, hall, cam, frame, box, knowledge, sup.out_dir)
            seen.append((box, c))
            if c["kind"] == "none":
                continue
            again = [i for i, t in tags.items() if t["kind"] == c["kind"] and (lb := last_box(i, frame, boxes))
                     and abs((lb[0] + lb[2]) / 2 - (box[0] + box[2]) / 2) < 120 and abs(lb[3] - box[3]) < 80]
            i = again[0] if again else max(tags, default=0) + 1
            if i > 16:                                    # SAM follows 16 prompted objects in one request
                continue
            tags.setdefault(i, {"kind": c["kind"], "first_frame": frame})
            tags[i].update(driven=c["driven"], why=c["why"])
            prompts[:] = [p for p in prompts if not (p["frame"] == frame and p["id"] == i)]
            prompts.append({"frame": frame, "id": i, "box": list(box)})
            named.append((i, c))
        sup.log.append(Issue("missing", f"{cam}, {frame / F.FPS:.0f} s", {"why": why, "named": [c["kind"] for _, c in named]},
                             images=[c["image"] for _, c in seen][:4], remedy="reprompt",
                             verdict={"finding": "; ".join(f"{c['kind']}{', driven' if c['driven'] == 'yes' else ''}: {c['why']}"
                                                           for _, c in seen) or "nothing to name"},
                             result={"named": {i: c["kind"] for i, c in named}, "at_frame": frame}))
    name(min(b["frame"] for b in det), [], "SAM's vehicle boxes say nothing of what each machine is")
    boxes = T.follow(models, hall, cam, prompts, cache) if prompts else []
    for _ in range(rounds):
        when = sorted({f for _, f in T.lost(boxes, list(tags), frames)} | set(T.unnamed(hall, cam, boxes)))[:3]
        if not when:
            break
        for f in when:
            name(f, boxes, "a named machine was lost, or SAM proposed one no name covers")
        boxes = T.follow(models, hall, cam, prompts, cache) if prompts else []
    out = {"tags": tags, "prompts": prompts, "boxes": boxes}
    (FX.scene_dir(hall) / "sam_tagged" / f"{cam}.json").write_text(json.dumps(out))
    return {"tags": len(tags), "prompts": len(prompts), "boxes": len(boxes),
            "kinds": dict(sorted({t["kind"]: sum(1 for u in tags.values() if u["kind"] == t["kind"]) for t in tags.values()}.items()))}


def _box_iou(a: tuple, b: tuple) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0
