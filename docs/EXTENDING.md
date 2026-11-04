# Extending Argus

The harness has four seams. Each is a small interface with a reference implementation in this repository.

| You bring | Through | Reference |
|---|---|---|
| your feeds | [`Replay`](../argus/replay.py) and a site's `feed.py` | the four packages in [`argus/sites/`](../argus/sites) |
| your memory | the [`Memory` and `Coordination` protocols](../argus/memory/__init__.py) | the Managed Memory Harness client ([`MEMORY.md`](MEMORY.md)) |
| your agents | [`Charter`, `Member`, `Manager`, `Supervisor`](../argus/hive) | the teams in each site package |
| your models | [`Models`](../argus/models.py) | Meta's models; Muse Spark Open on one OpenAI-compatible endpoint; a third provider is an adapter in the same file |

The snippets below share this setup (keys come from the environment, see [`argus/config.py`](../argus/config.py)):

```python
from pathlib import Path
from argus.memory import Edip
from argus.models import Models

memory, models = Edip(), Models()
```

## A site

A site is a package under `argus/sites/` and a folder under `examples/`:

```
argus/sites/mysite/
  feed.py    raw data to rows: deterministic, so it can be tested without a model or a memory
  pack.py    where the memory holds documents: table names, the episode features and outcomes, daily notes
  team.py    the charter and the agents: make(link, memory, models, ...) returns the members by role
examples/mysite/
  README.md  where the data comes from and how to run each step
```

The compressor ([`argus/sites/plant/`](../argus/sites/plant)) is the smallest complete one: about 150 lines of feed, 100 of
pack and 60 of team. The warehouse has only a team: its feed is [`argus/perception/floor.py`](../argus/perception/floor.py).

## Feeds into the memory

`Replay` feeds the memory in time order, as if the site were live: before anything happens at time T, every row up to T has
been appended, so whatever is asked at T sees the past and nothing after.

```python
from argus.replay import Replay

rows = [{"time": "2026-01-02 06:00", "unit": "u1", "pressure_bar": 8.1}]          # your compiled rows
note = "Unit u1 held 8.1 bar through the night shift."

replay = Replay(memory, Path("runs/mysite/replay.jsonl"))

# a table: rows are appended as the replay's clock passes their time
replay.stream("mysite/readings_5min.csv", ["time", "unit", "pressure_bar"], rows, time_key="time", tags=["site=mysite"])

# a document, known from the moment it is written (the t= tag is what keeps a bounded agent from reading it early)
replay.doc("2026-01-02 06:00", "mysite/daily/2026-01-02.md", note, kind="note", tags=["site=mysite", "t=2026-01-02T06:00"])

# a moment at which something acts: a watcher fires, an agent is asked
replay.checkpoint("2026-01-02 06:05", "the watcher fires", lambda now: print("the watcher fires at", now))

replay.run()
```

Compile first, remember second: put into the memory what an agent reasons with (five-minute health, not ten-second readings;
hourly traffic and vessel events, not positions), and keep the raw data local.

## The reasoning agent

```python
from argus.agent import Agent, Episodes

episodes = Episodes(memory, {"failure": "mysite/episodes.csv"}, {"failure": ["peak_duty_pct", "hours"]},
                    {"failure": ["failure_within_72h"]})
agent = Agent("a compressed-air plant", memory, models, episodes, bounded=True,
              known_at={"mysite/episodes.csv": "known_at"}, site_tag="site=mysite")
res = agent.run("warn", "the compressor has loaded 100% for forty minutes", "2026-01-02 06:05", audience="operator")
res.answer          # level, headline, body, actions, forecasts, confidence, citations
res.trace           # every call to the memory, in order
```

`bounded=True` keeps the agent at its moment. `Episodes.similar()` gives forecasts from similar past episodes, with their
spread, so the model explains a number instead of inventing one. A site can add tools the harness computes itself
(`extra={"whatif": (schema, fn)}`), as the factory does for its what-if over recorded tracks.

## A team

```python
from argus.hive.link import Link
from argus.hive.manager import Manager
from argus.hive.mind import Charter, Goal

charter = Charter(site="a compressed-air plant", purpose="Keep the compressor available without unplanned stops",
                  goals=[Goal("No air leak goes unwarned", measure="leaks warned 12 h or more ahead")],
                  sections={"maintenance": "inspections and repairs", "operations": "the train timetable"},
                  authority={"maintenance": "may schedule an inspection in a spare window", "operations": "may release a spare"})
link = Link(memory, Path("runs/mysite/hive.jsonl"))       # the Managed Memory Harness implementation of Coordination

maintenance = Manager(link, charter, "plant/maintenance", "maintenance manager", "plant/maintenance",
                      "Inspect before a leak, in a window operations can spare", models=models, provider="baseten")
operations = Manager(link, charter, "plant/operations", "operations manager", "plant/operations",
                     "Keep the timetable", models=models, provider="baseten")
for m in (maintenance, operations):
    m.brain = agent               # a manager thinks with a reasoning agent (the one built above), under the charter
    m.announce()

plan = {"action": "inspect_off_peak", "window_start": "2026-01-03 01:00"}
maintenance.hold("plan:plant/inspection", "v1", plan)     # a working copy of what it relies on
operations.change("plan:plant/inspection", "v2", "the spare moves to the night")    # intends first, then owns it
maintenance.stale()                                       # ['plan:plant/inspection']: re-read it before acting
```

`Member` is the base: the charter in every prompt, working copies (`hold`, `stale`), intents (`change`, `done`) and
`ask_json`. Messages and decision cards are on the link (`link.send`, `link.card`). Members and managers take the
`Coordination` protocol, so they are not tied to `Link`. [`HIVE.md`](HIVE.md) explains the model.

## A supervisor

A supervisor wraps one model or system. The invariants (`at_limit`, `disagrees`, `implausible`, `missing`) are plain
functions that return an `Issue` or `None`; the supervisor's judgement is spent only on an issue.

```python
from argus.hive.supervise import Supervisor, at_limit

sup = Supervisor(link, charter, "mysite/cameras", "camera supervisor", "mysite/perception",
                 "Nothing in memory that the cameras did not really see", models=models, provider="baseten",
                 watches="SAM 3.1 on the hall's cameras", out_dir=Path("runs/supervise/mysite"))
sup.announce()


def look_again_in_tiles(camera):                                       # what each remedy does is the site's to write
    return {"camera": camera, "tiles": 4}


issue = at_limit({0: 16, 1: 16, 2: 9}, 16, "Camera_01")                # followed 16 of 16 in most frames: at SAM's cap
if issue:
    issue.images = ["runs/supervise/mysite/Camera_01_60s.jpg"]         # the frame it looks at, with SAM's boxes drawn on it
    verdict = sup.judge(issue, "the frame, with what SAM boxed drawn on it",
                        ["SAM 3.1 follows at most 16 objects per request"], ["split", "reprompt", "ask_people"])
    sup.remedies = {"split": lambda i: look_again_in_tiles(i.subject)}
    sup.apply(issue, verdict["remedy"])
sup.save()                                                             # supervision.json: every issue, judgement and remedy
```

A `correct` remedy claims the memory it changes: `sup.change(resource, version, why)` takes the claim, so every other holder's
copy goes stale, and `sup.done(resource)` lets it go; `sup.correct_memory(resource, version, why)` does both and returns the
agents that were told. The sensor supervisor ([`SensorSupervisor`](../argus/hive/supervise.py)) is the same class applied to a
logger's channels, and the camera supervisor ([`sites/factory/supervise.py`](../argus/sites/factory/supervise.py)) is the one
for SAM 3.1.

## A memory

Implement the protocols in [`argus/memory/`](../argus/memory/__init__.py); see [`MEMORY.md`](MEMORY.md).

## Models

```python
m = Models()
m.chat([{"role": "user", "content": "…"}], provider="meta")        # Muse Spark; model= picks another; tools=, json_mode=, effort=
m.chat([{"role": "user", "content": "…"}], provider="baseten")     # Muse Spark Open on an OpenAI-compatible endpoint
m.segment("person", video_file_id=m.upload(Path("clip.mp4")), frames=600)     # SAM 3.1, a noun phrase, boxes per frame
m.transcribe(Path("question.wav"), seconds=6.0)                    # Muse Voice Transcribe
```

Every call is metered into `argus.models.ledger` at list prices. `ARGUS_CHAT_MODEL` picks the default chat model;
`ARGUS_BASETEN_URL`, `ARGUS_BASETEN_KEY` and `ARGUS_BASETEN_MODEL` point the second provider at any OpenAI-compatible
endpoint. A third provider is an adapter in `models.py`, not a setting.
