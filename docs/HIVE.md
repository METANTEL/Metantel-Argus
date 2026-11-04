# The Argus hive

People run a port or a plant as a team: watchers who see, section managers who plan, a director who sets priorities,
and people who decide what the team cannot settle alone. Each is capable. Coordinating them is slow, because
everything passes through people: a plan changes, and the next section learns at the next call or the next shift.

Argus runs the same team as AI agents that share **one purpose** and **one memory**, and coordinate in the memory
itself, at machine speed. No agent is a stateless function: the watchers that pre-process camera frames and sensor
streams read the same memory the managers write, so what the site has learned steers what they look for.

## What every agent has

| | What it is | Where it lives |
|---|---|---|
| **Charter** | The site's purpose, its goals in management's words (with how each is measured), its sections, and who may decide what. It is in every agent's prompt. | `argus/hive/mind.py` (`Charter`) and each site's `CHARTER` |
| **Shared memory** | The site's compiled record, plus facts in sentences that any agent can add or correct. A correction is a new dated fact; the old one is kept and marked replaced, and every agent sees the correction from then on. | The Managed Memory Harness (`argus/hive/link.py`) |
| **Working copies** | What an agent relies on, held as a copy of a named resource (`plan:port/traffic/<event>`, `memory:plant/floor/false-spots`). When another agent changes the resource, every copy goes **stale** at once, and the holder re-reads before it acts. | The Managed Memory Harness |
| **Intents** | Before acting, an agent says what it will change and why. A collision with another agent's intent comes back in the same answer. | The Managed Memory Harness |
| **Messages** | A direct line between agents (one agent, or a whole section), with read receipts. | The Managed Memory Harness |
| **Decisions for people** | What agents cannot settle, sent to people as a card with each agent's position and the options. A person decides in the console; the agents see the choice. | The Managed Memory Harness |

The coordination works like the caches of a processor: many readers may hold a copy; whoever changes a thing owns it
for the change, and every other copy is invalidated rather than left to drift. The difference from a processor is
that each agent is also told *why* (the intent) and can ask, refuse and escalate.

## Roles

| Role | Sees | Writes | Example |
|---|---|---|---|
| **Watcher** (perceptor) | One feed: a camera, a radio channel, a forecast, the vessel stream | Observations with what it expected kept apart from what it saw; its copy of the lessons tells it what to ignore | A camera's watcher drops detections at a place the floor's memory says is a parked forklift |
| **Section manager** | Its section's state and history, and copies of the plans it depends on | Plans, forecasts, briefings; lessons for the watchers; asks to other sections | The anchorage manager re-plans the queue the moment the channel moves its reopening time |
| **Director** | Every section's plan and the charter's goals | Briefings for executives; what goes to people | "Fog hold since 03:00; 33 ships waiting; no decision needed unless the hold passes 12 h" |
| **People** | The console | Decisions on the cards; corrections to the memory | The harbor master grants or refuses an anchorage's request the channel declined |

## Three sites, measured

**Warehouse floor** (`examples/warehouse/run_hive_floor.py`). Four camera watchers (SAM 3.1 detections on the floor plan) and a
floor-safety manager. Each flagged close call goes to the manager, who looks at the frames (Muse Spark vision) with
what the memory says about the place, confirms or rejects it, and writes a lesson when a place will mislead again
(a parked forklift, a fixture the detector reads as a vehicle). Writing the lesson makes every watcher's copy stale;
they re-read it before the next frame. A lesson that a place shows a "vehicle" that is not there is acted on only
when two reviews agree, so one wrong review cannot blind every camera to part of the floor. The first half of the
clip is the shift the hive learns from; the second half is scored.

**Port** (`examples/port/run_hive_port.py`). The channel manager owns the traffic plan for each slowdown; the arrivals
watcher publishes how fast ships join the queue; the weather watcher publishes the airport forecast next to what the
airports report; the anchorage manager plans the queue on its copies of all three and asks the channel for what it
needs; a refusal the anchorage cannot live with goes to people; the director briefs the executive. An anchorage
manager working alone, with the same memory and tools, plans the same events for comparison.

**Factory** (`examples/factory/run_hive_correction.py`). Floor operations, safety and logistics managers and a plant director
answer from a memory of four halls. The camera supervisor found that a "moving" vehicle charged with 102 close calls was a
forklift parked by a wall, and corrected the memory. Its correction claimed the hall's memory, so safety's copy went stale
and safety withdrew the decision it had built on it; safety's route claim made logistics' and floor operations' copies stale
and both re-read. Safety then asked the corrected memory again: the real top source of close calls was a robot in another
hall. It asked logistics to stop it, with the what-if (the same robot replayed earlier and later against the people as they
moved) as evidence; the request collided with logistics' use of the route; logistics checked the what-if and accepted; floor
operations re-planned its walkways on a fresh copy. Nobody called a meeting.

Results are in [`RESULTS.md`](RESULTS.md).

## Running it

```sh
python examples/warehouse/run_hive_floor.py          # the floor: watchers, safety manager, lessons
python examples/port/run_hive_port.py --weather      # the port: every fog slowdown of 2024
python examples/factory/supervise_factory.py --hall A    # the factory: the camera supervisor's checks and corrections
python examples/factory/run_hive_correction.py ...   # a correction reaching everyone who relied on the old picture
python -m argus.console                              # watch the site and the hive, decide its cards
```

The console (`argus/console/`) is a local page: the site live, each hall's floor and cameras, questions answered as they
are asked, the hive's coordination (intents, collisions, messages, stale copies, decisions) with the decisions waiting
for people, and the supervisors' findings. Keys stay in the harness.

## Supervisors

A supervisor is a member like the others whose section is one model or system (`argus/hive/supervise.py`). It holds the
system's output to four invariants (at the system's limit; an independent look disagrees; physically implausible; missing
what the site's knowledge says exists), looks for itself, with the site's charter and facts and the evidence, only where a
check fires, and chooses a remedy (split the work and ask again, ask in other words, re-derive, correct the memory, ask
people, or accept). A correction claims the memory it changes, so every member holding a copy of it is told the copy is
stale: the agent whose decision rested on the old picture is the one that revisits it.

Two supervisors ship. The camera supervisor ([`argus/sites/factory/supervise.py`](../argus/sites/factory/supervise.py)) watches
SAM 3.1 on a hall's cameras: it runs `at_limit` per frame and per request, and `implausible` on a "moving" vehicle that
never leaves a small circle, and the factory example adds `missing` for machines the people say run there. The sensor
supervisor watches a logger's channels and runs `implausible` on stretches where they froze. `disagrees` (an independent
look differs) is written and tested but no shipped supervisor calls it yet.
