# Argus at the Meta Global AI Developer Hackathon

**Track:** Startup · **Theme:** Push the Frontier (physical operations: ports, plants, warehouse floors)

## One line

Argus is an open harness that lets teams of frontier-model agents reason and work on the physical world's data, at
volumes no context window holds: it turns a site's cameras, location tags, sensors, ship traffic and weather into one
memory with Meta's models, and runs the site as a hive of AI agents (watchers, section managers, a director) that share one
purpose and coordinate through that memory, handing people only the decisions that need them.

## What we built during the hackathon, and what it runs on

Everything in this repository was written during the hackathon: the folder was empty on 1 November 2026, and its git
history runs from 3 November, 01:36 IST (2 November, 20:06 UTC) onward. Argus runs on Metantel's Managed Memory Harness,
our company's memory layer, which existed before the event. We added to it during the event only what Argus needed, listed
below with dates. The demo video shows only the new work; where the existing Managed Memory Harness appears on screen, we say so. The video is edited from
this repository's own console and runs; its production source is not part of the repository.

| Built during the hackathon (2–4 Nov 2026) | Where |
|---|---|
| The whole Argus harness: feeds that compile ship positions, compressor sensors, warehouse video and location tags into memory; the Meta model clients; the reasoning agent with time-bounded tools; the hive (charter, members, working copies, intents, messages, decision cards, shared facts); the factory, port, plant and floor teams; the what-if; the director's monthly review; the console; the evaluations | This repository (all commits) |
| New for client agents: handing work to a client's own agent, and agents coordinating through the memory (documented in its public API reference) | Managed Memory Harness, 3 Nov |
| Two fixes found while running Argus: tracing an entity by a numeric id (a ship's MMSI), and agents staying reachable through a server restart | Managed Memory Harness, 3 Nov |
| Two Breadboard parts in Artel, *Table rows* and *Agent*, and three starting boards | Artel, 3 Nov |

| Existed before the hackathon (used, not submitted) |
|---|
| Metantel's Managed Memory Harness |
| Artel, the web console (Breadboard boards, spaces, keys) |

## The problem

Perception models see the present; a frontier model's context window holds a few weeks of a busy site's record at best.
The people who run a port or a plant decide on the past (*the last time fog closed the channel, how long did it last?*)
and they decide as a team. Each section is capable; the slow part is between them. The channel changes its plan, and
the anchorage learns at the next call or the next shift; meanwhile pilots, tugs and terminals are given the old times.

## What we built

- **A factory of four halls, each seen through what it has.** Thirteen cameras in one; twelve cameras and humanoid
  robots in another; vehicle tags and six of 25 cameras in a third; location badges worn by 70% of the people, and no
  cameras, in the fourth. SAM 3.1 and the tags become one memory of who is where, every vehicle's state and every close
  call, with how far each hall's sources can be trusted, so every answer can say so. A plant director, floor operations,
  safety and logistics answer from it; a what-if replays a vehicle against the people as they moved; and a decision
  goes through the hive: safety's change collides with logistics' route, they negotiate, every other copy of the route
  goes stale, and floor operations re-plans the walkways.
- **Supervisors keep the models honest.** A model is blind to the site: SAM 3.1 follows sixteen objects a request and
  cannot tell a forklift being driven from one parked while people walk past. A supervisor (a Muse Spark agent in the
  hive; two ship, for cameras and for a sensor logger) holds a system's output to four invariants (at its limit,
  contradicted by an independent look, physically implausible, missing what the site knows exists), looks for itself only
  where a check fires, and chooses a remedy:
  ask again in smaller parts, ask in other words, re-derive, correct the memory, or ask people. A correction claims the
  memory it changes, so every agent that relied on it is told its copy is stale. On the factory's own footage the camera
  supervisor found the crowded views SAM had cut short and the "moving" vehicle that was a parked forklift; the safety
  manager withdrew the decision built on it, logistics and floor operations re-read, and the hive re-planned around the
  vehicle that really moves. The same class supervises the compressor's sensor log: it found six stretches where the
  pressure, motor current and oil temperature froze while the duty signal went on reporting, one of them under a warning
  that had read the frozen pressure as reassurance.
- **A console that ships with the harness.** The site live, each hall on its floor plan, each camera with what perception
  followed and every moving machine's danger zone drawn on the floor, questions answered as they are asked, the hive's
  coordination, and the supervisors' findings (`python -m argus.console`). The demo's product shots are this console,
  recorded frame by frame.
- **Pre-processing on Meta models, into memory.** SAM 3.1 finds people and vehicles on 13 warehouse cameras, frame by
  frame; each camera's calibration puts them on the floor plan. A year of the Port of Houston (207 million ship positions)
  becomes 8,755 hourly rows and 231,417 vessel events; seven months of a compressor's sensors become five-minute health
  and daily notes. Muse Spark Open writes up every slowdown; Muse Voice Transcribe takes an operator's spoken question.
  None of the raw data enters the memory.
- **Reasoning on the memory.** Muse Spark answers, warns, plans and briefs with the memory as tools: every number comes
  from an exact table query, every forecast from similar past episodes with their spread, every claim cites its source.
  The same moment is written for an operator, a manager and an executive. Asked at a given moment, an agent's tools keep
  it there: nothing after that moment exists for it.
- **The hive.** Every agent carries the site's charter (its purpose, its goals in management's words, who may decide
  what) and reads and writes the same memory. An agent keeps working copies of what it relies on; when another agent
  changes that thing, every copy goes stale at once and is re-read before anyone acts on it, the way a processor keeps
  its caches coherent. Agents say what they intend before they act, so collisions surface before they happen; they ask
  each other for what they need; what they cannot settle goes to people as a decision card, decided in a console. People
  correct the memory once, and every agent sees it. The watchers that pre-process the feeds are members too: what the
  site has learned steers what they look for.
- **Workflows anyone can build.** In Artel's Breadboard a board can start from a table and end with an agent part that
  Argus collects and answers on the customer's own model account.

## Meta models used

| Model | Where |
|---|---|
| `sam-3.1` (video) | people, humanoid robots and vehicles on 31 cameras across three factory halls, 2 frames a second; crowded views looked at in tiles at full resolution |
| `muse-spark-1.3` / `-contributor` | the reasoning agent, the factory's floor, safety and logistics managers, the floor-safety manager's vision review, keyframe descriptions, board drafting |
| `muse-wonder-1.0` | the factory's plant director (site brief, next shift's plan) and the port director's monthly reviews |
| `meta-models/muse-spark-open-1026` (Baseten) | the hive's section managers and director, the supervisors, the factory's corrected answers, slowdown write-ups, the year's long-context comparison (874K-token prompts) |
| `muse-voice-transcribe-1.0` | spoken questions from operators |

## Results (details and limits in `docs/RESULTS.md`)

- **The hive catches its own mistake.** The factory's first memory charged a parked forklift with 102 close calls, and
  safety and logistics agreed a decision on it. The camera supervisor flagged it (90% of its positions within 2.8 m of
  one spot), looked for itself ("a yellow forklift parked unoccupied in the same spot in all three frames"), corrected
  the memory, and the correction reached everyone who relied on it: safety withdrew its decision, logistics and floor
  operations re-read, and safety's answer on the corrected memory (Hall D's robot, the site's real top source of close
  calls) went through the hive instead: logistics agreed to stop it for the shift. Looked at in tiles and one-minute
  windows, Hall A's 13 cameras found 61% of the people in view instead of 35%, and the hall's close calls came to 92
  against 110 in the scene's ground truth. Muse Spark names each machine SAM proposes from a close crop, and the names
  are right for every Hall A machine.
- **A year does not fit in a context window; a memory does.** 21 questions about all of 2024 at the port: Argus 18;
  Muse Spark with every daily report pasted 0; Muse Spark with its window filled with the most recent 874K tokens of raw
  vessel events 1. Inside its own window it could not count one tug's 40 bay entries in December. On Meta's Muse Spark
  1.3 the memory arm scored 17, and the full window counted the tug's entries as 25.
- **Sections on the same plan.** On all of 2024's slowdowns, the hive's anchorage manager planned on the channel's
  current reopening time at every checkpoint (208 of 208); an anchorage manager working alone, with the same memory and
  tools, was more than two hours off at 36% and 53% of fog checkpoints (two runs) and 7% of the others. Its queue forecast
  was closer on 44 slowdowns and the lone planner's on 30, not yet a proven improvement.
- **What another section knows makes a better forecast.** With a weather watcher sharing the airport forecast and what
  the airports report, the channel manager's fog-duration forecast error fell from 6.9 h to 3.9 h (12 fog slowdowns),
  level with the National Weather Service's own airport forecast (3.7 h); a long record alone (similar past slowdowns) stays near 7 h.
- **Two sections settle it themselves.** On the compressor's 13 warnings, maintenance's inspection requests collided with
  operations' timetable 8 times; all 8 were settled between the two agents, and inspections were agreed before 2 of the 3
  leaks that had a warning (one 13 hours before).
- **Perception that learns, and its risk.** On the warehouse floor, the camera watchers and the safety manager raised
  precision from 0.67 to 0.74 at a recall of 0.77 (four cameras), and from 0.45 to 0.52 on all 13 cameras. The first version
  showed the risk of perception that reads memory: a reviewer that had not been told what the site's robot looks like
  rejected it and wrote lessons that hid its route from every camera. People's setup notes and corroboration across
  cameras fixed it; the failure and the fix are both in the results.
- **Spend:** about $52 of Meta API credit at list prices for the runs behind these results (the account's total is a little
  higher, with development runs and discarded tile layouts), and $24–46 of Baseten credit. The per-model breakdown is at the
  end of `docs/RESULTS.md`.

## What's next

- A self-hosted mode: Muse Spark Open and SAM 3.1 on the customer's own GPUs, for sites that cannot send data out.
- Live feeds instead of replays (AIS streams, MQTT, RTSP cameras) on the same pipeline.
- Arrivals and berth schedules in the memory, so the queue forecast improves the way the fog forecast did.
