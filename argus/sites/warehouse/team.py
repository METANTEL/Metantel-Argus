# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The warehouse floor as a hive: a perceptor per camera, a floor-safety manager, and the memory between them.

The perceptors run SAM 3.1's people and vehicles through each camera's calibration onto the floor plan, as the
isolated pipeline does. What changes is that they are not isolated:
- each perceptor keeps a working copy of the floor's lessons (`memory:plant/floor/false-spots`): the places where its
  detections have misled the hive before (a parked forklift, a rack that looks like a vehicle, a poster that looks like
  a person), written as facts by the manager, with who wrote them and why;
- every close call it flags goes to the floor-safety manager, who looks at two frames of it with Muse Spark vision and
  what the memory says about the place, confirms or rejects it, and when a place will mislead again writes the lesson;
- writing a lesson changes the resource, so every perceptor's copy goes stale and is re-read before the next frame.

The scene's 3D ground truth only scores the run. A close call is a person within 2 m of a moving vehicle or mobile
robot (the transporter or the NovaCarter); the forklifts never move.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...hive.mind import Charter, Goal, Member
from ...perception import floor as F

SECTION = "plant/floor"
LESSONS = "memory:plant/floor/false-spots"
KNOWLEDGE = "site-knowledge"
#: What the people who run this floor tell the hive at setup: what its machines look like, and how its footage looks.
SETUP = [
    "The mobile robots on this floor are small, low, white boxes on wheels (about knee height) with blue trim; they move "
    "on their own and always count as traffic, moving or paused.",
    "The autonomous transporter is a low, flat, yellow cart; it always counts as traffic, moving or paused.",
    "The forklifts on this floor stand parked by the racks with nobody at the controls.",
    "This footage is a simulation: some people are drawn semi-transparent. A translucent figure is still a person on the floor.",
]


def lessons_res(run: str) -> str:
    return f"{LESSONS}/{run}"
CAMS = ["Camera_01", "Camera_10", "Camera_12", "Camera_03"]
NEAR_M = F.NEAR_M
XY = re.compile(r"x=(-?\d+(?:\.\d+)?) y=(-?\d+(?:\.\d+)?)")

CHARTER = Charter(
    site="a warehouse and plant floor where people work beside forklifts, an autonomous transporter and mobile robots",
    purpose="Keep everyone on the floor safe while the floor keeps moving goods, and make every shift safer than the last.",
    goals=[Goal("Nobody comes within 2 m of a moving vehicle or mobile robot", "close calls per hour, by zone"),
           Goal("Every real close call reaches the shift supervisor within a minute", "time from the event to the alert"),
           Goal("Alerts stay trustworthy: a false alarm costs people's attention", "share of alerts that were real"),
           Goal("What one camera's watcher learns, every watcher knows", "repeat false alarms at a place already corrected")],
    sections={"plant/floor": "people, vehicles and robots on the floor; close calls and where they happen",
              "plant/maintenance": "the plant's machines and their health", "plant/operations": "the shift plan and throughput"},
    authority={"perceptor": "reports what its camera sees; may ignore a place only when the floor's memory says why",
               "floor-safety manager": "confirms or rejects close calls, writes the floor's lessons, alerts the supervisor; "
                                       "a change to how the floor works (a walkway, a speed limit) goes to people",
               "people": "decide changes to layout, routes, speed limits and staffing"})


def cam_id(c: str) -> str:
    return "plant/floor/" + c.lower().replace("_", "-")


@dataclass
class Episode:
    start_s: float
    end_s: float
    at_s: float
    distance: float
    person: F.Spot
    vehicle: F.Spot
    seen_by: set[str] = field(default_factory=set)

    def view(self) -> dict:
        return {"start_s": self.start_s, "end_s": self.end_s, "at_s": self.at_s, "min_distance_m": round(self.distance, 2),
                "camera": self.person.camera, "person_xy": (round(self.person.x, 1), round(self.person.y, 1)),
                "forklift_xy": (round(self.vehicle.x, 1), round(self.vehicle.y, 1)), "seen_by": sorted(self.seen_by)}


class Episodes:
    """Close calls formed frame by frame, as a live floor would form them; one closes after `gap_s` without a hit."""

    def __init__(self, near: float = NEAR_M, gap_s: float = 1.0):
        self.near, self.gap_s, self.open, self.closed = near, gap_s, [], []

    def step(self, t: float, merged: list[F.Spot], still: list[tuple[float, float]], cams_at: dict) -> list[Episode]:
        veh = [s for s in merged if s.kind == "vehicle" and not any(math.dist((s.x, s.y), q) < 1.5 for q in still)]
        for p in (s for s in merged if s.kind == "person"):
            for v in veh:
                d = math.dist((p.x, p.y), (v.x, v.y))
                if d >= self.near:
                    continue
                e = next((e for e in self.open if t - e.end_s <= self.gap_s and math.dist((p.x, p.y), (e.person.x, e.person.y)) < 2.0), None)
                if e is None:
                    e = Episode(t, t, t, d, p, v)
                    self.open.append(e)
                e.end_s = t
                e.seen_by |= cams_at.get((p.kind, round(p.x, 1), round(p.y, 1)), {p.camera})
                if d < e.distance:
                    e.distance, e.at_s, e.person, e.vehicle = d, t, p, v
        done = [e for e in self.open if t - e.end_s > self.gap_s]
        self.open = [e for e in self.open if e not in done]
        self.closed += done
        return done

    def flush(self) -> list[Episode]:
        done, self.open = self.open, []
        self.closed += done
        return done


def raw(cams: list[str] = CAMS) -> dict[float, list[F.Spot]]:
    cal = F.cameras()
    by_t: dict[float, list[F.Spot]] = {}
    for c in cams:
        for s in F.spots(c, json.loads((F.CLIPS / f"{c}_sam.json").read_text()), cal[c]):
            by_t.setdefault(s.t, []).append(s)
    return by_t


LESSON_RE = re.compile(r"\((parked equipment|not a vehicle|not a person)\)")


def lessons_from(facts: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """The floor's lessons as places where detections mislead. A parked machine is acted on at once; a place where the
    detector saw a vehicle or a person that was not there is acted on only once two reviews agree on it (within the
    radius), so one wrong review cannot hide part of the floor from every watcher."""
    seen: dict[str, list[tuple[float, float]]] = {"parked equipment": [], "not a vehicle": [], "not a person": []}
    for f in facts:
        m, c = XY.search(f["text"]), LESSON_RE.search(f["text"])
        if m and c:
            seen[c.group(1)].append((float(m.group(1)), float(m.group(2))))

    def agreed(pts: list[tuple[float, float]], r: float) -> list[tuple[float, float]]:
        return [p for i, p in enumerate(pts) if any(math.dist(p, q) < r for j, q in enumerate(pts) if j != i)]
    return {"vehicle": seen["parked equipment"] + agreed(seen["not a vehicle"], RADIUS["vehicle"]),
            "person": agreed(seen["not a person"], RADIUS["person"])}


RADIUS = {"vehicle": 1.5, "person": 0.8}


def keep(s: F.Spot, places: dict[str, list[tuple[float, float]]]) -> bool:
    return not any(math.dist((s.x, s.y), q) < RADIUS[s.kind] for q in places.get(s.kind, []))


class Perceptor(Member):
    """One camera's watcher. Its copy of the floor's lessons decides what it reports."""
    places: dict[str, list[tuple[float, float]]]

    def refresh(self, run: str) -> None:
        facts = self.link.facts(subject=f"run:{run}", limit=300)
        self.places = lessons_from(facts)
        self.hold(lessons_res(run), str(len(facts)), self.places)


def project(cal: dict, x: float, y: float) -> tuple[float, float]:
    h = cal["homography"]
    u, v, w = (h[0][0] * x + h[0][1] * y + h[0][2], h[1][0] * x + h[1][1] * y + h[1][2], h[2][0] * x + h[2][1] * y + h[2][2])
    return u / w, v / w


def _frame(cam: str, t: float, boxes: list[tuple[tuple, str, int]], p: Path) -> Path:
    if not p.exists():
        draw = []
        for (x1, y1, x2, y2), col, thick in boxes:
            x1, y1 = max(0, min(1915, x1)), max(0, min(1075, y1))
            w, h = max(4, min(1919 - x1, x2 - x1)), max(4, min(1079 - y1, y2 - y1))
            draw.append(f"drawbox=x={x1:.0f}:y={y1:.0f}:w={w:.0f}:h={h:.0f}:color={col}@0.9:t={thick}")
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(F.SCENE / "videos" / f"{cam}.mp4"),
                        "-frames:v", "1", "-vf", ",".join(draw + ["scale=1280:-2"]), str(p)], check=True)
    return p


def _projected(cal: dict, s: F.Spot, tall: float) -> tuple:
    u, v = project(cal, s.x, s.y)
    return (u - tall * 0.6, v - tall, u + tall * 0.6, v)


def frames(e: Episode, out_dir: Path, cal: dict) -> list[Path]:
    """The close call as the cameras saw it. One camera saw both: two frames from it, a second apart. Two cameras: one
    frame from each, every object boxed with a thick line where its camera detected it and a thin line where the floor
    plan puts an object the other camera saw. Person in red, vehicle in blue."""
    pc, vc = e.person.camera, e.vehicle.camera
    tag = f"{e.at_s:.1f}"
    if pc == vc:
        boxes = [(e.person.box, "red", 5), (e.vehicle.box, "blue", 5)]
        return [_frame(pc, max(0.0, e.at_s - 1), boxes, out_dir / f"{pc}_{tag}_a.jpg"),
                _frame(pc, e.at_s, boxes, out_dir / f"{pc}_{tag}_b.jpg")]
    return [_frame(pc, e.at_s, [(e.person.box, "red", 5), (_projected(cal[pc], e.vehicle, 170), "blue", 2)], out_dir / f"{pc}_{tag}_p.jpg"),
            _frame(vc, e.at_s, [(e.vehicle.box, "blue", 5), (_projected(cal[vc], e.person, 200), "red", 2)], out_dir / f"{vc}_{tag}_v.jpg")]


VERIFY = """The floor's detector flagged a possible close call at {t1:.1f} s into the shift: a PERSON (red box) and a VEHICLE OR MOBILE ROBOT (blue box), about {d:.1f} m apart on the floor plan (person at x={px:.1f} y={py:.1f}, vehicle at x={vx:.1f} y={vy:.1f}). {how}

What the floor's memory says about these places (lessons other agents wrote):
{memory}

What the people who run this floor have told every agent:
{knowledge}

What counts: a real person within about 2 m of a vehicle or robot that is part of floor traffic. The autonomous transporter (a low, flat yellow cart) and mobile robots ALWAYS count, moving or paused, because they move on their own. A forklift counts when someone is driving it. Parked equipment with nobody at the controls does not count, and neither do racks, pallets, boxes or empty floor.

A thin box is only where the floor plan puts an object another camera saw, and can be off by a metre or two: judge
each object in the frame where its own camera drew a thick box.

Reject only when you can see the red box is not a person, or the blue object is parked equipment or not a vehicle. When you are unsure, confirm: a missed close call costs more than a false alarm.

Reply with JSON only:
{{"red_is_person": "yes|no|unclear", "blue_is": "transporter or mobile robot|vehicle being driven|parked equipment|not a vehicle|unclear", "verdict": "confirm|reject", "reason": "one sentence on what you see"}}"""


class Safety(Member):
    """The floor-safety manager: confirms or rejects close calls, and writes what the floor learns."""

    def verify(self, e: Episode, places: dict, out_dir: Path, cal: dict, facts: list[dict], knowledge: list[dict] = ()) -> dict:
        near = [f for f in facts if (m := XY.search(f["text"])) and (math.dist((float(m.group(1)), float(m.group(2))), (e.person.x, e.person.y)) < 4
                                                                        or math.dist((float(m.group(1)), float(m.group(2))), (e.vehicle.x, e.vehicle.y)) < 4)]
        memory = "\n".join(f"- {f['text']} (by {f['author']})" for f in near[:8]) or "- nothing yet about these places"
        imgs = frames(e, out_dir, cal)
        how = (f"Two frames from {e.person.camera.replace('_', ' ')}, one second apart, both boxes detected by that camera."
               if e.person.camera == e.vehicle.camera else
               f"The first frame is from {e.person.camera.replace('_', ' ')}, which detected the person; the second from "
               f"{e.vehicle.camera.replace('_', ' ')}, which detected the vehicle. A thin box is where the floor plan puts the "
               "object the other camera saw.")
        known = "\n".join(f"- {f['text']}" for f in knowledge) or "- nothing"
        prompt = VERIFY.format(t1=e.at_s, d=e.distance, px=e.person.x, py=e.person.y, vx=e.vehicle.x, vy=e.vehicle.y,
                               memory=memory, how=how, knowledge=known)
        return self.ask_json(prompt, images=imgs, max_tokens=5000)

    def learn(self, e: Episode, v: dict, run: str, now: str) -> list[dict]:
        """A rejected close call whose cause is a place (parked equipment, a fixture the detector misreads) becomes a lesson
        every watcher reads. The category is in the sentence, so a watcher knows how far to trust it."""
        if v.get("verdict") != "reject":
            return []
        why = str(v.get("reason") or "").strip().rstrip(".")
        src = f"{SECTION}/close-calls/{run}/{e.at_s:.1f}"
        facts = []
        if v.get("blue_is") in ("parked equipment", "not a vehicle"):
            facts.append({"text": f"Vehicle detections at x={e.vehicle.x:.1f} y={e.vehicle.y:.1f} on the floor plan are not traffic "
                                  f"({v['blue_is']}): {why}.", "kind": "lesson", "subjects": [SECTION, "false-vehicle", f"run:{run}"],
                          "since": now, "source": src})
        if v.get("red_is_person") == "no":
            facts.append({"text": f"Person detections at x={e.person.x:.1f} y={e.person.y:.1f} on the floor plan are not people "
                                  f"(not a person): {why}.", "kind": "lesson", "subjects": [SECTION, "false-person", f"run:{run}"],
                          "since": now, "source": src})
        if facts:
            self.link.add_facts(self.agent, facts)
        return facts


def score(found: list[dict], gold: list[dict]) -> dict:
    return F.score(found, gold)


def truth(cams: list[str] = CAMS, near: float = F.GT_NEAR_M) -> list[dict]:
    """Close calls in the 3D ground truth: a person within `near` m of the transporter or the NovaCarter robot."""
    return F.truth(cams, near)[0]


def stamp(t: float) -> str:
    """Seconds into the clip as a time on the shift (the clip is treated as starting at 08:00)."""
    s = int(t)
    return f"2026-11-03T08:{s // 60:02d}:{s % 60:02d}"


def merge_with_cams(spots: list[F.Spot]) -> tuple[list[F.Spot], dict]:
    """`floor.merge` for one instant, plus which cameras saw each merged object (corroboration)."""
    merged = F.merge(spots).get(spots[0].t, []) if spots else []
    cams: dict[tuple, set[str]] = {}
    for m in merged:
        r = {"person": 1.0, "vehicle": 2.0}[m.kind]
        cams[(m.kind, round(m.x, 1), round(m.y, 1))] = {s.camera for s in spots if s.kind == m.kind and math.dist((s.x, s.y), (m.x, m.y)) < r}
    return merged, cams


def place_of(e: Episode) -> dict[str, Any]:
    return {"person": (round(e.person.x, 1), round(e.person.y, 1)), "vehicle": (round(e.vehicle.x, 1), round(e.vehicle.y, 1))}
