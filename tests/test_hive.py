# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The hive's pure logic: keeping an agent at its moment, reading what a reply committed to, and which lessons a watcher
may act on."""
from argus.agent import _object, _salvage, bound, stamp_of
from argus.eval.year import final
from argus.sites.port import taf
from argus.sites.warehouse import team as H


def test_a_plan_cannot_see_past_now_even_when_it_asks_to():
    p = bound({"op": "latest", "table": "port/slowdowns.csv", "time": {"to": "2025-01-01"},
               "then": {"op": "rows", "table": "port/traffic_hourly.csv"}}, "2024-03-04 02:00", {"port/slowdowns.csv": "known_at"})
    assert p["time"]["to"] == "2024-03-04 02:00" and p["as_of"] == "2024-03-04 02:00"
    assert {"column": "known_at", "op": "lte", "value": "2024-03-04 02:00"} in p["where"]
    assert p["then"]["time"]["to"] == "2024-03-04 02:00"
    assert bound({"op": "rows", "table": "x", "time": {"to": "2024-01-01"}}, "2024-03-04 02:00", {})["time"]["to"] == "2024-01-01"


def test_a_document_is_known_from_its_stamp():
    assert stamp_of(["site=port", "t=2024-03-05T23:59"]) == "2024-03-05 23:59"
    assert stamp_of(["site=port"]) == ""
    assert stamp_of(["t=2024-03-05T23:59"]) > "2024-03-05 02:00"   # same day, later hour: compared as text


def test_a_plan_is_recovered_from_a_reply_whose_json_is_broken():
    raw = '{"level": "watch", "body": "two\nlines", "plan": {"state": "hold", "why": "a \\"quoted\\" {brace}"}, "x": 1'
    assert _object(raw, "plan") == {"state": "hold", "why": 'a "quoted" {brace}'}
    assert _salvage(raw)["plan"]["state"] == "hold"
    assert _object('{"plan": "not an object"}', "plan") is None


def test_only_the_committed_answer_is_scored():
    assert final("I counted 6 events in the window, maybe 12.\nFINAL: 12") == "12"
    assert final('{"final": "2024-07-29", "body": "6 entries"}') == "2024-07-29"
    assert final("I think 6") is None


def test_a_watcher_acts_on_parked_equipment_at_once_and_on_a_phantom_only_when_two_reviews_agree():
    def fact(x, y, what):
        return {"text": f"Vehicle detections at x={x} y={y} on the floor plan are not traffic ({what}): why.", "subjects": []}
    places = H.lessons_from([fact(4.4, -1.0, "parked equipment"), fact(1.0, 1.0, "not a vehicle"),
                             fact(9.0, 9.0, "not a vehicle"), fact(1.5, 1.2, "not a vehicle")])
    assert (4.4, -1.0) in places["vehicle"]
    assert (1.0, 1.0) in places["vehicle"] and (1.5, 1.2) in places["vehicle"]
    assert (9.0, 9.0) not in places["vehicle"], "one review alone must not hide a place from every camera"


def test_the_airport_forecast_lifts_at_its_first_prevailing_group_above_the_threshold():
    p = {"issued": "2024-01-23 05:22", "groups": [
        {"start": "2024-01-23 05:22", "tempo": False, "vis": 0.25, "raw": "1/4SM FG"},
        {"start": "2024-01-23 08:00", "tempo": True, "vis": 5.0, "raw": "TEMPO 5SM"},
        {"start": "2024-01-23 10:00", "tempo": False, "vis": 2.0, "raw": "FM231000 2SM BR"},
        {"start": "2024-01-23 15:00", "tempo": False, "vis": 5.0, "raw": "FM231500 5SM"}]}
    assert taf.lift(p, "2024-01-23 07:00")[0] == "2024-01-23 15:00"      # a TEMPO group and exactly 2 SM do not lift it
    assert taf.lift(p, "2024-01-23 16:00")[0] == "2024-01-23 16:00"      # already lifted: now


def _crossing() -> dict:
    """Hall A in miniature: a vehicle drives through K9 past a person standing there."""
    from argus.sites.factory.feed import Track
    ts = [i * 0.5 for i in range(21)]
    vehicle = Track("A-vehicle-c15", "vehicle", "camera", ts, [0.5 + 0.4 * i for i in range(21)], [-2.0] * 21)
    person = Track("A-person-c1", "person", "camera", ts, [3.0] * 21, [-2.5] * 21)
    return {"A": {"tracks": [vehicle, person]}}


def test_the_what_if_finds_a_vehicle_named_without_its_hall():
    from argus.sites.factory import team as F
    run = F.whatif_fn(_crossing())
    full = run({"hall": "A", "vehicle": "A-vehicle-c15", "avoid_zones": ["K9"]}, "")
    assert full["vehicle"] == "A-vehicle-c15" and full["avoid"]["inside_zones"] == full["avoid"]["close_calls"] > 0
    assert run({"hall": "a", "vehicle": "vehicle-C15"}, "")["by_shift"] == full["by_shift"]
    assert "error" in run({"hall": "A", "vehicle": "vehicle-c99"}, "")


def test_safetys_request_carries_the_what_if_as_its_evidence():
    from argus.sites.factory import team as F
    wf = F.whatif_fn(_crossing())({"hall": "A", "vehicle": "A-vehicle-c15", "avoid_zones": ["K9", "K10"]}, "")
    ask = F.route_ask("route:A-vehicle-c15", "Stop its route through K9 and K10", wf, ["K9", "K10"])
    n = wf["avoid"]["close_calls"]
    assert ask.startswith("[route:A-vehicle-c15] Safety asks: Stop its route through K9 and K10.")
    assert f"of A-vehicle-c15's {n} close calls" in ask and "inside K9, K10" in ask and f"(as run: {n})" in ask


def test_every_supervisor_holds_output_to_the_same_checks():
    from argus.hive import supervise as S
    assert S.at_limit({0: 16, 1: 16, 2: 3}, 14, "cam").evidence["units_at_limit"] == 2
    assert S.at_limit({0: 3, 1: 4}, 14, "cam") is None
    assert S.disagrees(12, 60, "cam").check == "disagrees" and S.disagrees(55, 60, "cam") is None
    assert S.missing({"robot", "transporter"}, {"transporter"}, "hall:A").evidence["missing"] == ["robot"]
    assert S.missing({"robot"}, {"robot"}, "hall:A") is None


def test_a_person_seen_from_two_tiles_is_one_box_with_one_identity():
    from argus.perception import tiles as P
    left, right = (0, 0, 1000, 600), (800, 0, 1000, 600)
    seen_left = [{"frame": f, "obj": 0, "x1": 850 + f, "y1": 100, "x2": 900 + f, "y2": 300, "c": 0.9} for f in range(4)]
    seen_right = [{"frame": f, "obj": 5, "x1": 851 + f, "y1": 101, "x2": 901 + f, "y2": 301, "c": 0.9} for f in range(4)]
    someone_else = [{"frame": f, "obj": 1, "x1": 100, "y1": 100, "x2": 150, "y2": 300, "c": 0.9} for f in range(4)]
    out = P.merge([(left, seen_left + someone_else), (right, seen_right)])
    assert len(out) == 8 and len({o["obj"] for o in out}) == 2
    assert all(o["w"] == 1920 and o["h"] == 1080 for o in out)


def test_a_vehicle_jittering_in_place_is_not_moving_but_one_driving_is():
    from argus.sites.factory.feed import Track, moving
    ts = [i * 0.5 for i in range(60)]
    jitter = Track("j", "vehicle", "camera", ts, [(-1) ** i * 1.0 for i in range(60)], [0.0] * 60)
    drive = Track("d", "vehicle", "camera", ts, [0.5 * i for i in range(60)], [0.0] * 60)
    parked = Track("p", "vehicle", "camera", ts, [0.5 * i for i in range(60)], [0.0] * 60, parked=True)
    assert max(moving(jitter, i) for i in range(10, 50)) < 0.2
    assert min(moving(drive, i) for i in range(10, 50)) > 0.8
    assert moving(parked, 30) == 0.0


def test_a_stalled_logger_is_found_while_the_machine_keeps_reporting():
    from argus.hive import supervise as S
    live = [{"p": 8 + 0.1 * (i % 3), "duty": 10.0 * (i % 4)} for i in range(10)]
    stuck = [{"p": 8.248, "duty": 10.0 * (i % 4)} for i in range(30)]
    idle = [{"p": 8.5, "duty": 0.0} for i in range(30)]          # frozen too, but the machine is off: not an issue
    rows = live + stuck + live + idle
    assert S.frozen(rows, ["p"], "duty", 24) == [(10, 39)]


def test_named_machines_go_to_sam_as_box_prompts_and_lost_ones_are_found():
    from argus.perception import naming as T
    prompts = [{"frame": 40, "id": 2, "box": [10, 20, 60, 80]}, {"frame": 0, "id": 1, "box": [100, 200, 180, 260]}]
    assert T.prompt_text(prompts) == ("<0f>1<|box;x1=100;y1=200;x2=180;y2=260;w=960;h=540|>"
                                      "<40f>2<|box;x1=10;y1=20;x2=60;y2=80;w=960;h=540|>")
    boxes = [{"frame": f, "obj": 1} for f in range(0, 30)] + [{"frame": f, "obj": 2} for f in range(40, 600)]
    assert T.lost(boxes, [1, 2], 600) == [(1, 30)]
