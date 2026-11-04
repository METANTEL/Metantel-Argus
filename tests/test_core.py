# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The pure parts of Argus: parsing SAM's output, the floor geometry, the slowdown detector, the replay's ordering, and
answer scoring. Nothing here calls a model or the memory."""
from __future__ import annotations

from argus.eval.qa import Q, found
from argus.models import parse_boxes, parse_json
from argus.perception import floor as F
from argus.replay import Replay
from argus.sites.port.feed import slowdowns


def test_sam_boxes_after_the_first_in_a_frame_carry_no_marker():
    text = ("<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=960;h=540;c=0.9|><|mask;x=0;y=0;data=1,2!|>,"
            "1<|box;x1=5;y1=6;x2=7;y2=8;w=960;h=540;c=0.8|><|mask;x=0;y=0;data=3!|>"
            "<1f>0<|box;x1=9;y1=9;x2=10;y2=10;w=960;h=540|><|mask;x=0;y=0;data=4!|>")
    b = parse_boxes(text)
    assert [(x["frame"], x["obj"]) for x in b] == [(0, 0), (0, 1), (1, 0)]
    assert b[1]["x1"] == 5 and b[1]["c"] == 0.8 and b[2]["c"] is None


def test_parse_json_reads_fenced_or_embedded_objects():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here it is: {"level": "watch"} done') == {"level": "watch"}


def test_a_homography_and_its_inverse_round_trip():
    h = [[2.0, 0.1, 5.0], [0.0, 1.5, -3.0], [0.001, 0.0, 1.0]]
    hi = F._inv3(h)
    x, y = F.to_floor(h, 3.0, 4.0)
    bx, by = F.to_floor(hi, x, y)
    assert abs(bx - 3.0) < 1e-9 and abs(by - 4.0) < 1e-9


def test_near_misses_skip_parked_vehicles_and_merge_frames():
    by_t = {t / 2: [F.Spot(t / 2, "vehicle", 0.0, 0.0, "c", 0.9),             # parked: there in every frame
                    F.Spot(t / 2, "vehicle", 10.0 + t * 1.0, 0.0, "c", 0.9),   # moving, 2 m/s
                    F.Spot(t / 2, "person", 10.6 + t * 1.0, 0.0, "c", 0.9),    # walking beside the moving one
                    F.Spot(t / 2, "person", 0.3, 0.0, "c", 0.9)]               # beside the parked one
            for t in range(6)}
    eps = F.near_misses(by_t)
    assert len(eps) == 1 and eps[0]["start_s"] == 0 and eps[0]["end_s"] == 2.5 and eps[0]["min_distance_m"] == 0.6


def _hours(values: list[int], vis: dict[int, str] | None = None) -> list[dict]:
    rows = []
    for i, v in enumerate(values):
        d, h = divmod(i, 24)
        rows.append({"time": f"2024-01-{d + 1:02d} {h:02d}:00", "moving_total": v, "inbound_transits": 1, "outbound_transits": 1,
                     "waiting_outside": 30 + (5 if v < 3 else 0), "vis_galveston_mi": (vis or {}).get(i, "10"), "vis_baytown_mi": ""})
    return rows


def test_a_slowdown_is_judged_against_the_hours_before_it():
    vals = [10] * 48 + [1, 0, 1, 2] + [10] * 20
    sl = slowdowns(_hours(vals, {48: "0.25", 49: "0.25"}))
    assert len(sl) == 1
    s = sl[0]
    assert s.start == "2024-01-03 00:00" and s.hours == 4 and s.cause == "dense fog" and s.baseline_moving == 10
    assert slowdowns(_hours([10] * 20 + [0] * 4)) == []          # under a day of history: no baseline, no verdict


def test_replay_runs_documents_and_checkpoints_in_time_order_after_the_rows():
    class FakeEdip:
        def __init__(self):
            self.log = []

        def ingest(self, name, text, kind="document", tags=None):
            self.log.append(("ingest", name, text.count("\n")))

        def append(self, name, rows):
            self.log.append(("append", name, len(rows)))

    import tempfile
    from pathlib import Path
    e = FakeEdip()
    rp = Replay(e, Path(tempfile.mkdtemp()) / "log.jsonl")
    rp.stream("t.csv", ["time", "v"], [{"time": "2024-01-01 01:00", "v": 1}, {"time": "2024-01-01 05:00", "v": 2},
                                       {"time": "2024-01-02 01:00", "v": 3}], "time")
    seen = []
    rp.checkpoint("2024-01-01 03:00", "check", lambda now: seen.append((now, list(e.log))))
    rp.doc("2024-01-01 23:59", "d.md", "day one")
    rp.run()
    now, before = seen[0]
    assert now == "2024-01-01 03:00" and before == [("ingest", "t.csv", 2)]   # only the 01:00 row (plus header) exists then
    assert e.log[1:] == [("append", "t.csv", 1), ("ingest", "d.md", 0), ("append", "t.csv", 1)]


def test_scoring_needs_every_gold_value():
    q = Q("x", "?", ["2020-04-18", 98.91])
    assert found('{"body": "The highest was 98.9% on 2020-04-18."}', q)
    assert not found('{"body": "The highest was 98.9%."}', q)
    assert found("about 1,000 ships", Q("y", "?", [1000]))


def test_a_compiled_cache_written_under_the_old_layout_still_loads(tmp_path):
    import pickle
    import sys
    import types

    from argus.config import load_cache
    old = types.ModuleType("argus.feeds.floor")           # where the floor model lived before the package was laid out by capability
    old.Spot = F.Spot
    sys.modules["argus.feeds.floor"] = old
    here, F.Spot.__module__ = F.Spot.__module__, "argus.feeds.floor"
    try:
        (tmp_path / "old.pkl").write_bytes(pickle.dumps([F.Spot(1.5, "person", 2.0, 3.0, "Camera_01", 0.9)]))
    finally:
        F.Spot.__module__ = here
        del sys.modules["argus.feeds.floor"]
    got = load_cache(tmp_path / "old.pkl")
    assert isinstance(got[0], F.Spot) and got[0].camera == "Camera_01" and got[0].x == 2.0


def test_the_plants_warnings_come_from_the_latest_replay(tmp_path):
    import json

    from argus.sites.plant.pack import firings
    older, newer = tmp_path / "equipment" / "20261103-0046", tmp_path / "equipment" / "20261103-0150"
    for d in (older, newer):
        d.mkdir(parents=True)
        (d / "summary.json").write_text("{}")
    (older / "warnings.json").write_text(json.dumps([{"at": "2020-01-01 00:00", "episode_start": "x", "truth_failure_within_72h": 0,
                                                      "truth_failure_id": None}]))
    (newer / "warnings.json").write_text(json.dumps([{"at": "2020-04-17 09:00", "episode_start": "2020-04-17 08:00",
                                                      "truth_failure_within_72h": 1, "truth_failure_id": "F1",
                                                      "answer": {"level": "act_now", "headline": "Inspect now"}}]))
    assert firings(tmp_path) == [{"fired_at": "2020-04-17 09:00", "episode_start": "2020-04-17 08:00", "failure_within_72h": "1",
                                  "failure": "F1", "level": "act_now", "headline": "Inspect now"}]
    assert firings(tmp_path / "nowhere") == []
