# Warehouse floor: 13 cameras

The perception deployment. The site is one warehouse floor seen by 13 calibrated cameras for five minutes: people on foot,
forklifts, an autonomous transporter and a mobile robot. SAM 3.1 finds the people and vehicles in each camera; each
camera's calibration puts them on the floor plan; a near miss is a person within 1.5 m of a moving vehicle.

**Data.** NVIDIA PhysicalAI-SmartSpaces, MTMC_Tracking_2025, scene Warehouse_015 (CC BY 4.0): 13 cameras, 30 fps, with the
scene's 3D ground truth, which is used only to score the pipeline, never as an input. About 4 GB.

```sh
examples/factory/get_factory_halls.sh        # Warehouse_015 is Hall A of the factory; the script fetches all four scenes (about 6 GB)
```

## Run

```sh
python examples/warehouse/detect_floor.py            # SAM 3.1 on every camera, 2 frames a second, cached per camera
python examples/warehouse/run_floor.py               # four cameras into the memory: events, counts, described keyframes,
                                                     # and the near-miss detector scored against the scene's ground truth
python examples/warehouse/run_hive_floor.py          # the same cameras as a hive: camera watchers and a floor-safety manager
python examples/warehouse/rescore_floor.py runs/hive-floor/<run>      # score a finished run again, with no model
```

## What it shows

- **Perception turned into positions** ([`argus/perception/floor.py`](../../argus/perception/floor.py)): ffmpeg cuts each video
  to 2 frames a second so SAM is billed for 600 frames, not 9,000; detections go through the homography onto the floor plan
  and are merged across cameras.
- **Watchers that learn** ([`team.py`](../../argus/sites/warehouse/team.py)): each camera is a watcher that reads the lessons
  the floor-safety manager writes into the memory (a place that shows a "vehicle" that is not there; parked equipment) and
  ignores what it has been told is false. Writing a lesson makes every watcher's copy of the lessons stale, so each re-reads
  before its next frame. A lesson that a place shows a phantom is acted on only when two reviews agree, so one wrong review
  cannot blind every camera to part of the floor.
- **The risk of perception that reads memory.** The first version showed it: a reviewer that had not been told what the
  site's robot looks like rejected it and wrote lessons that hid the robot's route from every camera. People's setup notes and
  corroboration across cameras fixed it; the failure and the fix are both in the results.

Scored against the ground truth on the second half of the clip (the first half is the shift the hive learns from): four
cameras, the watchers alone precision 0.67 and recall 0.81, the hive 0.74 and 0.77; all 13 cameras, alone 0.45 and 0.90, the
hive 0.52 and 0.82. One scene, five minutes. Method and limits: [`docs/RESULTS.md`](../../docs/RESULTS.md).
