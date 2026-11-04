# Reference sites

Four complete deployments of the harness on public data. Each one has its feeds (raw data into compact tables), a team of
agents, and the runs that measured it. They are examples of how to deploy Argus on a site, in the order a client would meet
the problems:

| Folder | Site | Start here to see |
|---|---|---|
| [`plant/`](plant) | a compressor's sensor log (MetroPT-3) | the smallest deployment: a feed, a replay into the memory, an agent that warns, two agents that agree an inspection, a supervisor on a sensor log |
| [`port/`](port) | the Port of Houston, a year of ship positions | scale: 207 million positions in a memory a model can use; forecasts from similar past episodes; sections on one plan |
| [`warehouse/`](warehouse) | one warehouse floor, 13 cameras | perception: SAM 3.1 on video, floor positions, close calls, watchers steered by what the site learned |
| [`factory/`](factory) | four halls, each seen through what it has | everything together: perception in tiles, machines named, supervisors, managers answering from the memory, a decision through the hive, a correction reaching everyone |

Every script runs from the repository root, with the package installed (`pip install -e .`) and the keys set
([`argus/config.py`](../argus/config.py)). Data goes under `data/` and each run under `runs/`, both outside version control.

Two scripts work across sites (each knows the port and the compressor):

- [`ask.py`](ask.py) (`port` or `plant`): ask Argus a question about a site's memory, typed or spoken (a WAV file,
  transcribed by Muse Voice Transcribe), at a moment of the replay and for an audience.
- [`eval_qa.py`](eval_qa.py) (`port` or `equipment`): ask a site's questions with the memory, with a window of recent
  reports and with nothing, and score them against answers computed by code.

[`results/`](results) collects the runs into the CSV files behind [`docs/RESULTS.md`](../docs/RESULTS.md).

A new site is a package under [`argus/sites/`](../argus/sites) and a folder here; see [`docs/EXTENDING.md`](../docs/EXTENDING.md).
