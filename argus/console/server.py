# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The console's server: the page, the site's data as the harness compiled it, the runs' records, the live hive, and
questions answered as they are asked. It runs on this machine; no key reaches the browser."""
from __future__ import annotations

import json
import mimetypes
import queue
import re
import threading
import time
from collections import deque
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ..config import DATA, RUNS
from ..sites.factory import feed as FX

STATIC = Path(__file__).parent / "static"
FONTS = DATA / "fonts"


def _latest(kind: str, file: str) -> Path | None:
    runs = sorted((p for p in (RUNS / kind).glob("*") if (p / file).exists()), key=lambda p: p.name)
    return runs[-1] if runs else None


def _r(v: float, n: int = 2) -> float:
    return round(float(v), n)


@lru_cache(maxsize=None)
def compiled() -> dict:
    from ..sites.factory import team as H
    return H.compiled()


@lru_cache(maxsize=None)
def site() -> bytes:
    srcs = {s["hall"]: s for s in compiled_sources()}
    halls = []
    for h, spec in FX.HALLS.items():
        tb = compiled()[h]["tables"]
        halls.append({"id": h, "scene": spec["scene"], "people": spec["people"], "vehicles": spec["vehicles"],
                      "cameras": FX.cameras(h) if spec["people"] == "cameras" or spec["vehicles"] == "cameras" else [],
                      "sources": srcs.get(h, {}), "close_calls": len(tb["close_calls"])})
    return json.dumps({"site": "factory", "clock": FX.CLOCK, "seconds": 300, "halls": halls}).encode()


def compiled_sources() -> list[dict]:
    """What each hall's sources can see, with how many of the people present they track (written at ingest)."""
    p = DATA / "factory-sources.json"
    return json.loads(p.read_text()) if p.exists() else FX.sources()


@lru_cache(maxsize=None)
def hall(h: str) -> bytes:
    d = compiled()[h]
    s, tx, ty, H = FX.map_transform(h)
    tracks = []
    xs, ys = [], []
    for tr in d["tracks"]:
        moving = [1 if FX.moving(tr, i) >= 0.2 else 0 for i in range(len(tr.t))] if tr.kind not in ("person",) else []
        tracks.append({"id": tr.id, "kind": tr.kind, "src": tr.source, "parked": bool(getattr(tr, "parked", False)),
                       "t": [_r(t, 1) for t in tr.t], "x": [_r(x) for x in tr.x], "y": [_r(y) for y in tr.y], "m": moving})
        xs += tr.x
        ys += tr.y
    # the busy part of the floor: where 96% of positions fall, inside the floor plan (a camera's stray projection lands
    # outside the walls and would shrink the hall to a corner of the view)
    import struct
    with (FX.scene_dir(h) / "map.png").open("rb") as f:
        mw = struct.unpack(">I", f.read(24)[16:20])[0]
    wx0, wx1, wy0, wy1 = -tx, mw / s - tx, -ty, H / s - ty
    xs = sorted(x for x in xs if wx0 <= x <= wx1)
    ys = sorted(y for y in ys if wy0 <= y <= wy1)
    q = lambda v, f: v[min(len(v) - 1, int(f * len(v)))] if v else 0.0  # noqa: E731
    calls = [{**e, "t0": FX._secs(e["start"]), "t1": FX._secs(e["end"])} for e in d["tables"]["close_calls"]]
    return json.dumps({"hall": h, "map": f"/media/{h}/map.png", "transform": [s, tx, ty, H],
                       "extent": [q(xs, 0.02), q(ys, 0.02), q(xs, 0.98), q(ys, 0.98)], "zone_m": FX.ZONE_M,
                       "near_m": FX.NEAR_M, "tracks": tracks, "close_calls": calls}).encode()


@lru_cache(maxsize=None)
def camera(h: str, cam: str) -> bytes:
    det = FX.detect(None, h, cam)
    cal = FX.calibration(h)[cam]
    boxes = {}
    for concept in ("person", "humanoid robot", "vehicle"):
        rows = []
        for b in det.get(concept, []):
            sx, sy = 1920 / b["w"], 1080 / b["h"]
            rows.append([b["frame"], b["obj"], round(b["x1"] * sx), round(b["y1"] * sy), round(b["x2"] * sx), round(b["y2"] * sy)])
        boxes[concept] = rows
    dense = (FX.scene_dir(h) / "sam_dense" / f"{cam}_person.json").exists()
    return json.dumps({"hall": h, "camera": cam, "fps": 2, "video": f"/media/{h}/videos/{cam}.mp4", "homography": cal["homography"],
                       "boxes": boxes, "people_in_tiles": dense, "kinds": det.get("_kinds") or {}}).encode()


def _url(p: str | Path) -> str:
    p = Path(p)
    try:
        return "/runs/" + str(p.resolve().relative_to(RUNS.resolve()))
    except ValueError:
        return ""


def supervision() -> bytes:
    """The newest run of each supervisor: every issue its checks raised, what it looked at, found and changed."""
    found: dict[str, dict[tuple, dict]] = {}          # supervisor -> (check, subject) -> its newest finding
    for f in sorted((RUNS / "supervise").glob("*/supervision.json"), key=lambda f: f.parent.name):
        d = json.loads(f.read_text())
        d = d if isinstance(d, dict) else {"watches": "SAM 3.1 on Hall A's cameras", "issues": d}
        for i in d["issues"]:
            i["images"] = [_url(p) for p in i.get("images") or []]
            i["after_images"] = [_url(p) for p in (i.get("result") or {}).get("count_after_images") or []]
            i["supervisor"], i["run"] = d["watches"], f.parent.name
            found.setdefault(d["watches"], {})[(i["check"], i["subject"])] = i
    order = {"implausible": 0, "limit": 1, "disagrees": 2, "missing": 3}
    issues = [i for by in found.values() for i in sorted(by.values(), key=lambda i: (order.get(i["check"], 9), i["subject"]))]
    return json.dumps({"issues": issues}).encode()


def answers() -> bytes:
    """The newest answer to each factory question, from whichever run asked it last."""
    seen: dict[str, dict] = {}
    for run in sorted((RUNS / "factory-qa").glob("*/answers.json"), key=lambda p: p.parent.name):
        for q in json.loads(run.read_text()):
            seen[q["id"]] = {**q, "run": run.parent.name}
    return json.dumps(sorted(seen.values(), key=lambda q: q["id"])).encode()


def hive_run(name: str = "") -> bytes:
    run = (RUNS / "hive-factory" / name) if name else _latest("hive-factory", "decision.json")
    if not run or not (run / "decision.json").exists():
        return b"{}"
    log = [json.loads(x) for x in (run / "hive.jsonl").read_text().splitlines() if x.strip()] if (run / "hive.jsonl").exists() else []
    w0 = log[0]["wall"] if log else 0
    for e in log:
        e["at"] = round(e["wall"] - w0, 1)
    runs = sorted(p.name for p in (RUNS / "hive-factory").glob("*") if (p / "decision.json").exists())
    return json.dumps({"run": run.name, "runs": runs, "decision": json.loads((run / "decision.json").read_text()),
                       "log": log}, default=str).encode()


class Live:
    """The hive as it is now, through the same keyed routes the agents use."""

    def __init__(self) -> None:
        self.link = None

    def _link(self):
        if self.link is None:
            from ..memory import Edip
            from ..hive.link import Link
            self.link = Link(Edip())
        return self.link

    def state(self) -> dict:
        link = self._link()
        roster = link.roster()
        return {"agents": roster["agents"], "intents": roster["intents"], "cards": link.cards()[-30:],
                "facts": link.facts(limit=40)}

    def resolve(self, card: str, resolution: str, note: str) -> dict:
        return self._link().resolve(card, resolution, note, "console")


def ask(who: str, text: str, out: "queue.Queue[tuple[str, dict]]") -> None:
    """A question to one of the factory's managers, answered from the memory; each tool call is sent as it finishes."""
    try:
        from ..memory import Edip
        from ..sites.factory import team as H
        from ..hive.link import Link
        from ..models import Models
        edip, models = Edip(), Models()
        run = time.strftime("console-%Y%m%d%H%M%S")
        hive = H.make(Link(edip), edip, models, run, provider="baseten")
        m = hive.get(who) or hive["director"]
        now = f"{FX.CLOCK[:10]} 08:05"
        out.put(("start", {"role": m.role, "model": models.k.baseten_model, "now": now}))
        o = m.brain.run("answer", text, now, "manager", context=H.KNOWN, preamble=m.system(),
                        on_step=lambda st: out.put(("step", st)))
        out.put(("answer", {"answer": o.answer, "usd": o.usd, "seconds": o.seconds}))
    except Exception as e:  # noqa: BLE001 - the page shows what went wrong
        out.put(("error", {"error": str(e)[:400]}))
    out.put(("end", {}))


def serve(port: int) -> None:
    live = Live()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("content-type", ctype)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, body: bytes) -> None:
            self._send(200, body, "application/json")

        def _file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                self._send(404, b"not found", "text/plain")
                return
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            rng = self.headers.get("range")
            start, end = 0, size - 1
            if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = size - int(m.group(2))
                end = min(end, size - 1)
                self.send_response(206)
                self.send_header("content-range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("content-type", ctype)
            self.send_header("accept-ranges", "bytes")
            self.send_header("content-length", str(end - start + 1))
            self.send_header("cache-control", "max-age=3600")
            self.end_headers()
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def do_GET(self) -> None:  # noqa: N802 - the stdlib's name
            u = urlparse(self.path)
            path, qs = unquote(u.path), parse_qs(u.query)
            parts = path.strip("/").split("/")
            try:
                if path in ("/", "/index.html"):
                    self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
                elif parts[0] == "static" and len(parts) == 2:
                    self._file(STATIC / parts[1])
                elif parts[0] == "fonts" and len(parts) == 2:
                    self._file(FONTS / parts[1])
                elif parts[0] == "media" and len(parts) >= 3 and parts[1] in FX.HALLS:
                    p = (FX.scene_dir(parts[1]) / "/".join(parts[2:])).resolve()
                    self._file(p if str(p).startswith(str(FX.scene_dir(parts[1]).resolve())) else Path("/nonexistent"))
                elif parts[0] == "runs" and len(parts) >= 2:
                    p = (RUNS / "/".join(parts[1:])).resolve()
                    self._file(p if str(p).startswith(str(RUNS.resolve())) and p.suffix in (".jpg", ".png") else Path("/nonexistent"))
                elif path == "/api/site":
                    self._json(site())
                elif len(parts) == 3 and parts[:2] == ["api", "hall"] and parts[2] in FX.HALLS:
                    self._json(hall(parts[2]))
                elif len(parts) == 5 and parts[:2] == ["api", "hall"] and parts[3] == "camera":
                    self._json(camera(parts[2], parts[4]))
                elif path == "/api/supervision":
                    self._json(supervision())
                elif path == "/api/answers":
                    self._json(answers())
                elif path == "/api/hive":
                    self._json(hive_run((qs.get("run") or [""])[0]))
                elif path == "/api/state":
                    self._json(json.dumps(live.state(), default=str).encode())
                else:
                    self._send(404, b"not found", "text/plain")
            except Exception as e:  # noqa: BLE001 - one failing panel must not take the console down
                self._send(502, json.dumps({"error": str(e)[:300]}).encode(), "application/json")

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            parts = path.strip("/").split("/")
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
            if path == "/api/ask":
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("cache-control", "no-store")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                threading.Thread(target=ask, args=(str(body.get("who") or "director"), str(body.get("text") or ""), q),
                                 daemon=True).start()
                while True:
                    kind, data = q.get()
                    try:
                        self.wfile.write(f"event: {kind}\ndata: {json.dumps(data, default=str)}\n\n".encode())
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    if kind == "end":
                        self.close_connection = True
                        return
            elif len(parts) == 4 and parts[:2] == ["api", "cards"] and parts[3] == "resolve":
                try:
                    card = live.resolve(parts[2], str(body.get("resolution") or ""), str(body.get("note") or ""))
                    self._json(json.dumps(card).encode())
                except Exception as e:  # noqa: BLE001
                    self._send(502, json.dumps({"error": str(e)[:300]}).encode(), "application/json")
            else:
                self._send(404, b"not found", "text/plain")

        def log_message(self, *a) -> None:  # quiet
            pass

    print(f"Metantel Argus console on http://127.0.0.1:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def recent_log(run: Path, n: int = 150) -> list[dict]:
    with (run / "hive.jsonl").open() as f:
        tail = deque(f, maxlen=n)
    return [json.loads(x) for x in tail if x.strip()]
