# Factory: four halls, each seen through what it has

The full deployment: every layer of the harness on one site. The site is four halls on one shift clock, and no hall has
complete sources:

| Hall | Scene | What sees it |
|---|---|---|
| A | Warehouse_015 | 13 cameras: people, forklifts, an autonomous transporter, a mobile robot |
| B | Warehouse_016 | 12 cameras: people beside humanoid robots, the transporter |
| C | Warehouse_000 | tags on every vehicle; 6 of its 25 cameras for people |
| D | Warehouse_010 | location badges worn by 70% of the people, no cameras |

Cameras are seen with SAM 3.1 and put on the floor through each camera's calibration; tags are the scene's recorded
positions, thinned to the people who wear them. Everything is compiled, with no model, into what the memory keeps: who is
where by zone every 10 seconds, every vehicle's state, close calls, a summary per minute, and what each hall's sources can and
cannot see, so that every answer can say how far to trust it.

**Data.** NVIDIA PhysicalAI-SmartSpaces, MTMC_Tracking_2025 (CC BY 4.0), four scenes. The scenes are simulated and unrelated;
they are shown as one site on one clock.

## Run, in order

```sh
examples/factory/get_factory_halls.sh                      # the four scenes (about 6 GB)

# 1. the first memory, from each camera's whole view
python examples/warehouse/detect_floor.py                  # Hall A: SAM 3.1 on each camera's whole view
python examples/factory/detect_factory.py                  # halls B and C
python examples/factory/ingest_factory.py                  # compile the four halls and put them into the memory

# 2. perception that holds up under density, supervised
python examples/factory/perceive_dense.py A                # Hall A in tiles at full resolution, and in one-minute windows
python examples/factory/name_machines.py --hall A          # Muse Spark names each machine from a close crop; SAM follows the names
python examples/factory/supervise_factory.py --hall A      # the camera supervisor: checks the first memory against what the
                                                           # cameras show, looks for itself, applies remedies
python examples/factory/ingest_factory.py                  # the memory again, rebuilt from the supervised perception

# 3. ask, decide, correct
python examples/factory/run_factory_qa.py                  # a director (Muse Wonder) and three managers (Muse Spark 1.3) answer
                                                           # from the memory; --provider baseten runs Muse Spark Open for every role;
                                                           # --voice recording.m4a asks one question aloud
python examples/factory/run_hive_factory.py runs/factory-qa/<id>/answers.json  # one decision through the hive
python examples/factory/run_hive_correction.py runs/supervise/<id> runs/hive-factory/<id> --answers runs/factory-qa/<id>/answers.json

python -m argus.console                                    # watch all of it: http://127.0.0.1:8765
```

SAM 3.1 is billed per frame; Hall A's 13 cameras in tiles and windows cost about $26 at list prices, and every result is
cached, so a rerun pays only for what is missing. The spend table in [`docs/RESULTS.md`](../../docs/RESULTS.md) has the rest.

## What it shows

- **Perception under density** ([`argus/perception/tiles.py`](../../argus/perception/tiles.py)). SAM follows at most 16
  objects a frame and at most 16 over a whole clip per request, and Hall A's cameras see up to 61 people in a frame. Looked at in
  tiles at full resolution, and again in one-minute windows where a request had followed 16, Hall A's cameras found 61% of the
  people in view instead of 35%, at 77% precision. 68 of the 73 people present on average were tracked.
- **Machines named, then followed** ([`naming.py`](../../argus/perception/naming.py)). Naming machines on a whole crowded
  frame failed (the transporter became a forklift, parked forklifts were given drivers); a close crop of each of SAM's
  proposals, with the site's own description of its machines, got every Hall A machine right against the scene's truth, and
  threw out 22 proposals that were not machines.
- **Supervisors** ([`argus/sites/factory/supervise.py`](../../argus/sites/factory/supervise.py), on the base class in
  [`argus/hive/supervise.py`](../../argus/hive/supervise.py)). The camera supervisor found the crowded views
  SAM had cut short and looked again in tiles. It found that a "moving" vehicle charged with 102 close calls was a forklift
  parked by a wall, looked at three frames of it, and corrected the memory.
- **Managers answering from the memory** ([`team.py`](../../argus/sites/factory/team.py)). A plant director, floor
  operations, safety and logistics, each answering the question its section would ask, with every number from an exact table
  plan and a what-if that replays a vehicle against the people as they moved. Seven questions, including one spoken.
- **A decision through the hive**, and **a correction reaching everyone** ([`run_hive_correction.py`](run_hive_correction.py)):
  the correction claims the hall's memory; safety's copy goes stale and safety withdraws its decision; logistics and floor
  operations re-read; safety asks the corrected memory again and finds the real top source of close calls, a robot in Hall D,
  asks logistics to stop it with the what-if as evidence; the request collides with logistics' use of the route; logistics
  checks and accepts; floor operations re-plans on a fresh copy.

Limits worth knowing: perception is good, not perfect (precision 77% at 61% recall; Hall A's close calls come to 92 against
110 in the truth); the what-if assumes people would have moved as they did, so it bounds what a change could avoid and does
not promise it; the footage is simulated. Results, method and limits: [`docs/RESULTS.md`](../../docs/RESULTS.md).
