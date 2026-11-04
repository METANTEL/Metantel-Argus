# Plant: a compressor

The smallest complete deployment. The site is the air-production unit of a metro train (APU-1), logging 15 signals every 10
seconds. The harness compiles the log into five-minute health, finds abnormal episodes, replays them into the memory in time
order, and lets agents warn, plan and supervise.

**Data.** MetroPT-3 (Davari, Veloso, Ribeiro, Gama; UCI Machine Learning Repository; CC BY 4.0): February to September 2020,
with the operator's four air-leak reports. About 220 MB.

```sh
mkdir -p data/metropt && curl -sL -o data/metropt/metropt3.zip "https://archive.ics.uci.edu/static/public/791/metropt+3+dataset.zip"
unzip -qo data/metropt/metropt3.zip -d data/metropt     # MetroPT3(AirCompressor).csv
```

## Run

```sh
python examples/plant/run_equipment.py             # replay the record into the memory; at the first hour of every severe
                                                   # episode the watcher fires and Argus warns, seeing only what was known then
python examples/plant/stamp_plant_docs.py          # file the daily notes and work orders with `t=` stamps (for bounded agents)
python examples/plant/run_hive_plant.py            # maintenance and operations on every 2020 warning, through the hive
python examples/plant/supervise_plant.py           # the sensor supervisor on the log: stretches where the channels froze
python examples/ask.py plant "Is the compressor behaving as it did before the April leak?" --now "2020-04-17 12:00"
```

Each run writes to `runs/` and every model call is metered; the run prints what it spent.

## What it shows

- **A feed, compiled with no model** ([`argus/sites/plant/feed.py`](../../argus/sites/plant/feed.py)): 10-second signals to
  five-minute health, daily notes and abnormal episodes judged against the trailing week.
- **Forecasts from memory** ([`pack.py`](../../argus/sites/plant/pack.py)): each episode is appended once its outcome is
  known, and the agent's risk estimate is the spread of the most similar past episodes, never a guess.
- **Two agents that agree** ([`team.py`](../../argus/sites/plant/team.py)): maintenance asks for an inspection, operations
  holds the timetable; their intents collide; they settle it by message. On the 13 warnings of 2020, all 8 scheduling
  requests were settled between the agents, and an inspection was agreed before 2 of the 3 leaks that had a warning, one 13
  hours ahead.
- **A supervisor on a different system**: the same class as the camera supervisor, here on a sensor logger. It found six
  stretches where pressure, motor current and oil temperature were frozen while the duty signal went on reporting, one of
  them under a warning that had read the frozen pressure as reassurance.

Results and limits: [`docs/RESULTS.md`](../../docs/RESULTS.md) (the compressor's watcher was tuned on the same data, and the
operations timetable is a stated assumption).
