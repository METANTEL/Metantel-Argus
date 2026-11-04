# Results

Measured on 2–3 November 2026 against Metantel's Managed Memory Harness, with Meta's models as served. Every gold answer was
computed by code from the data; no model wrote or graded a gold answer. Each section says what the number does not show.

## What it is worth to an operator

Each row is a question someone running the site asks, what they have today, what Argus gave, and what is at stake. The
"today" column is the fairest stand-in we could measure; where no fair comparison exists, it says so.

| The operator's question | Today, without Argus | With Argus | What is at stake |
|---|---|---|---|
| **Port:** "Fog just stopped the channel. When will it reopen?" | The National Weather Service's airport forecast for Galveston, which a dispatcher reads: off by **4.8 h** on average over 2024's 16 fog slowdowns. Rule of thumb (the median of earlier slowdowns): 7.5 h | The hive's channel manager, with the weather watcher's report beside the memory: on the 12 slowdowns where both versions gave a forecast, off by **3.9 h** against 6.9 h with the memory alone (43% less), level with the airport forecast on the same 12 (3.7 h). It does not beat the forecast | At a typical Gulf tanker demurrage of $35,000 a day, every hour of a 50-ship queue is about $73,000 of ship time; a reopening known three hours more precisely lets pilots, tugs and terminals be ready for it rather than for the wrong hour |
| **Port:** "Is every section working from the same plan?" | Each section estimates on its own. An anchorage planner working alone, with the same memory, planned on a reopening more than 2 h from the channel's current one at **36% and 53%** of fog checkpoints in two runs (12 of 33; 23 of 43), and 7% on the other 116 slowdowns | The hive's anchorage planned on the channel's current reopening at **every** checkpoint, fog or not (208 of 208 across three runs). Each of the channel's 43 plan revisions made the anchorage's copy stale in the same second, and it re-planned before acting | A queue sequenced for the wrong reopening sends pilots, tugs and terminals the wrong times; today the correction waits for the next call or shift |
| **Plant:** "Is this compressor about to fail, and when do we take the train out?" | Run to failure: the four air leaks kept the unit faulted 124 hours before repair | A warning 14 to 62 hours ahead of 3 of the 4 leaks. Maintenance and operations then **agreed an inspection before 2 of those 3 leaks** (17 April: 13 h before; 14 July), settling all 8 requests between themselves, none sent to people. Cost: 6 agreed inspections that came before no leak | 112 of the 124 faulted hours belonged to leaks that had a warning first |
| **Floor:** "Where do people and robots keep crossing paths?" | Only what people report; there is no measured baseline for unreported close calls | On the second half of the clip: four camera watchers alone, precision 0.67 and recall 0.81; the hive (people's setup notes, corroboration across cameras, review of weak flags) 0.74 and 0.77. All 13 cameras: alone 0.45 and 0.90; hive 0.52 and 0.82 | A medically consulted work injury costs about $43,000 (NSC, 2023) |
| **Anyone:** "What happened over the year?" (21 questions with computed answers) | Muse Spark with every daily report of 2024 pasted: **0 of 21** (it says the reports do not hold it). Muse Spark with its context window filled with the most recent raw vessel events (874K tokens): **1 of 21** | **18 of 21**, citing the exact table plan behind each number, about 20K tokens a question | The year's events are 231,417 rows, about 8.8M tokens as text: ten context windows |

How these comparisons fall short:
- **Port.** The airport forecast is for Galveston airport, not the channel; a slowdown also lasts while the backlog moves.
  Two of 2024's longest "low-visibility" slowdowns were storms (Tropical Storm Alberto, 19 June; Hurricane Beryl,
  8 July), which the visibility rule labels fog; they are left out of the fog figures and named below.
- **Plant.** The watcher's thresholds were tuned on this same data; the operations timetable (peaks, spares) is a stated
  assumption, not the operator's real one.
- **Floor.** One scene, five minutes; the setup knowledge people gave the reviewer was written after seeing its mistakes on
  the first run (below).

## Scale: what a context window does not hold

The figures behind "billions of tokens", with their arithmetic. Each is one measurement multiplied out, not the log of a
live site.

| | Measured | Multiplied out |
|---|---|---|
| Video from Hall A's 13 cameras | 13 files of 1920×1080 at 30 frames a second, 2.69 GB for the five minutes the scene covers | about 260 GB for an eight-hour shift |
| The same video, read by a model as images | one 1920×1080 frame is 2,693 prompt tokens on Muse Spark 1.3 (3 November, and again on 4 November: 2,708 with a 15-token instruction) | 13 cameras × 2 frames a second × 28,800 s × 2,693 = 2.0 billion tokens a shift; at the cameras' own 30 frames a second, 30 billion |
| A year of ship positions (207,098,304 rows in the Houston box) | 24.8 tokens a position written compactly (2 November); 38.7 tokens as a plain CSV row of MMSI, time, latitude, longitude, speed and course (4 November, 400 sampled rows) | 5.1 to 8.0 billion tokens as text |
| What a model reads to answer from the memory | the port's year questions: about 20K tokens each; the factory's seven questions: 177,477 prompt tokens in all (63,754 on Muse Wonder for the director's two answers, 113,723 on Muse Spark 1.3 for the managers' five), about 25K each | |

What this does not show: how much of the data a model needs. Reading every frame is not the aim; the memory exists so that a
model reads the few thousand rows an answer rests on. The rates come from one frame, one sample of positions and five
minutes of a simulated scene, and a shift is five minutes multiplied by 96.

## The hive: agents with one purpose and one memory

How it works: [`HIVE.md`](HIVE.md). Every agent carries the site's charter, reads and writes the shared memory, keeps
working copies of what it relies on (made stale when another agent changes them), says what it intends before it acts,
messages other agents and hands what they cannot settle to people. All of it runs through the memory.

### Port: the channel, the anchorage, the arrivals and weather watchers, the director

On each of 2024's 18 low-visibility slowdowns, at 2 h and again at 5 h and 8 h while it lasted (46 checkpoints), with the
whole year in memory and every agent's tools kept at its moment:

| | Hive | Anchorage working alone (same memory, same tools, no hive) |
|---|---|---|
| Checkpoints where the anchorage's assumed reopening was more than 2 h from the channel's current plan | **0 of 41** | 12 of 33 (36%) |
| Median gap between the two | **0 h** | 1.0 h |
| Plans with an unusable reopening date | 1 | 6 |
| Queue recovery forecast, first plan, mean absolute error (14 slowdowns with a measured recovery) | 19.6 h | 20.5 h |

Coordination on those 18 slowdowns: 20 revisions of a channel plan published (each made the anchorage's copy stale), 39
requests from the anchorage to the channel, 2 sent on to people as decision cards. Model spend $3.08 (Muse Spark Open on
Baseten, 528 calls).

What it shows: the hive removes the gap between sections; it does not by itself make the queue forecast better. The
queue's recovery depends on arrivals and berth capacity the memory does not hold.

**With a weather watcher** publishing the airport forecast and what the airports report (a second run on the same 18
slowdowns; the agents could also look up the shared facts, including the harbor master's corrections below):

| | Hive | Anchorage working alone |
|---|---|---|
| Checkpoints with the anchorage more than 2 h from the channel's current plan | **0 of 45** | 23 of 43 (53%) |
| Median gap | **0 h** | 3.0 h |
| Queue recovery forecast, first plan (14) | 19.6 h | 22.8 h |
| Channel's fog duration forecast (16 fog slowdowns, storms left out) | **4.9 h** (15 with a usable plan; 3.9 h on the 12 paired with the first run, against 6.9 h there) | — |

12 channel revisions published, 31 requests to the channel, 1 card to people; $2.77 on Baseten.

**The other 116 slowdowns of 2024** (normal visibility: night lulls and causes the data does not name; 133 checkpoints,
the same hive with the weather watcher):

| | Hive | Anchorage working alone |
|---|---|---|
| Checkpoints with the anchorage more than 2 h from the channel's current plan | **0 of 122** | 8 of 113 (7%) |
| Queue recovery forecast, first plan | 8.4 h | 9.0 h (102 paired) |
| Channel's duration forecast, first plan | 1.8 h | — |

126 requests to the channel, none sent to people. Short slowdowns are easy to read, so a planner alone usually guesses
the same reopening; the gap opens on the long, uncertain ones (fog), where it matters.

**Queue recovery, all paired slowdowns (116):** the hive's anchorage was closer than the lone planner on 44, the lone
planner on 30; mean error 9.8 h against 10.7 h, but the 95% interval on the difference (−0.4 to +2.2 h) includes none.
Sharing the current plan keeps the sections aligned; it has not been shown to make the queue forecast better.

**Fog duration, two hours in**, mean absolute error over the 16 fog slowdowns (storms left out):

| Forecast | All 16 | The 12 where both channel runs gave a forecast |
|---|---|---|
| The airport forecast (TAF), latest issued before the moment: when prevailing visibility rises above 2 miles | **4.8 h** | **3.7 h** |
| **The hive's channel manager with the weather watcher** | 4.9 h (15 with a usable plan) | **3.9 h** |
| The hive's channel manager, memory only | 6.6 h (13) | 6.9 h |
| Similar past slowdowns from the memory (median of the five nearest) | 7.0 h | |
| Median of all earlier slowdowns | 7.5 h | |

With the weather watcher the channel manager mostly takes the forecast's lift time; twice it did better than the forecast
where the forecast had missed the fog (23 February, 18 December), and twice it distrusted a forecast that was right
(3 March, 28 December).

The airport forecast is right when it forecasts fog and wrong when it misses it (5 of 16: it said visibility was
already above 2 miles while the channel was stopped). The airports' own reports show when it has missed, which is
what the weather watcher hands the channel manager.

### Plant: maintenance and operations

For each of the compressor watcher's 13 firings in 2020: maintenance planned from the memory (Muse Spark Open, with the
five-minute health table, daily notes and similar past episodes); an inspection it wanted was an intent to change the
unit, which collided with operations' standing intent to use it; operations answered within its authority; an
agreement became a claim on the unit.

| | |
|---|---|
| Plans: inspect now / inspect off-peak / watch / no plan | 1 / 7 / 4 / 1 |
| Requests that collided with the timetable | 8 |
| Settled between the two agents / sent to people | 8 / 0 |
| Warned leaks with an inspection agreed before the leak began | 2 of 3 (17 April, 14 July; on 2 June maintenance chose to watch) |
| Agreed inspections followed by no leak within 72 h | 6 |
| Model spend | $0.35 |

**The sensor supervisor** (`examples/plant/supervise_plant.py`, run `202611040404`, the same supervisor class and checks as the
factory's camera supervisor) found six stretches of 6 to 42 hours in which the compressor's pressure, motor current and
oil temperature repeated one value exactly while its duty signal went on reporting loading of 7–36%: a logger stalled on
its analog channels ("physically impossible", in its words: a loading compressor draws current). It told the hive those
readings are not measurements. The 17 April warning fired inside one of them: the watcher's "pressure holding at 8.25 bar"
was a frozen reading, while the duty signal it also cited was real. The inspection agreed that morning still came 13
hours before the leak; what the supervisor changes is that no agent may take a stuck reading for reassurance again.

### Floor: camera watchers and a floor-safety manager

Four camera watchers (SAM 3.1 detections on the floor plan, at 2 frames a second) and a floor-safety manager who reviews
each flagged close call on two frames, with what the memory says about the place, and writes a lesson when the place
will mislead again. Writing a lesson makes every watcher's copy stale; they re-read it before the next frame. The first
150 s are the shift the hive learns from; the last 150 s are scored against the scene's 3D ground truth (a person within
2 m of the transporter or the NovaCarter robot; 52 close calls).

| Second half of the clip | Found | Precision | Recall |
|---|---|---|---|
| Four camera watchers alone (parked-vehicle rule from the first half) | 54 | 0.67 | 0.81 |
| Last night's pipeline (motion filter; parked rule from the whole clip) | 37 | 0.76 | 0.65 |
| Watchers with the first half's lessons, no review | 50 | 0.68 | 0.75 |
| Hive, reviewer without the floor's setup notes, reviewing every flag (Muse Spark Open) | 15 | 0.60 | 0.33 |
| Hive, with the setup notes, reviewing every flag (Muse Spark 1.3) | 24 | 0.67 | 0.44 |
| **Hive, with the setup notes, corroboration first** (Muse Spark Open; 44 reviews of 89 flags) | 38 | **0.74** | **0.77** |
| All 13 camera watchers alone | 97 | 0.45 | 0.90 |
| **Hive on all 13 cameras, corroboration first** (Muse Spark 1.3; 68 reviews of 179 flags) | 79 | **0.52** | **0.82** |

"Corroboration first": a close call seen by two cameras, or for a second or more, stands; the manager reviews only the
weaker ones. That rule was set after the run that reviewed every flag, on the same scene, so the four-camera row is not
held out; nine of the 13 cameras are new to it. With 13 overlapping cameras, many phantom detections are seen by two
cameras, so corroboration passes more of them. The hive buys a few points of precision for a few of recall here; it is
not a large effect.

The first review run failed in a way worth showing. The reviewer had never been told what this floor's robots look
like: it rejected the NovaCarter robot (a small, low, white box on wheels) as "not a vehicle", rejected people the
simulation draws semi-transparent as "ghosts", and wrote lessons that hid the robot's route from every camera. That is the
risk of perception that reads memory: a wrong lesson spreads. The guards in the design held part of it (a lesson about
a phantom needs two reviews to agree) but not all. The fix is what a site would do on day one: people tell the hive
what the floor looks like, as standing facts every agent reads (`argus/sites/warehouse/team.py`, `SETUP`).

### People teach the hive, and management steers it

**Corrections.** The visibility rule called two of 2024's longest slowdowns fog; they were storms (19 June, Tropical
Storm Alberto; 8 July, Hurricane Beryl, landfall on the Texas coast that day). The harbor master's corrections went
into the memory once, as standing facts dated when they became known (`examples/port/hive_teach.py`); every agent that looks
at the shared facts after those dates reads them, and the fog figures above leave both storms out.

**The director's monthly review** (`examples/port/run_hive_review.py`, Muse Wonder, $0.95 for five months). At the end of each
month with fog, the director measured the charter's goals from the memory (the slowdowns table, hourly traffic) and from
what the hive planned that month, then set at most three priorities, each for one section, as facts dated the first of
the next month:

| Month | The director's finding |
|---|---|
| January | The 24-hour backlog goal was missed: recoveries of 9, 67, 29 and 51 h, one of four within a day. The anchorage's recovery forecasts were far too short (11 h forecast against 51 h). Priorities: the anchorage publishes ranges, not single clear-by times; the channel re-issues its plan within the hour whenever the reopening moves; the weather watcher flags when the airports report far worse than the forecast |
| February | Backlog goal partly met (one of two fog backlogs over 24 h) |
| March | Missed: one dense-fog backlog took 59 h |
| July | Backlogs cleared within 24 h and plans stayed in step, but the two long closures (the storms) were forecast far too short |
| December | Missed again; the proven problem is forecast error, not safety |

Every month the director marked the safety goal ("no deep-draft transit in conditions the pilots judge unsafe")
*unknown*: the memory does not record transits during a declared hold. That is a true gap, not a pass.

## The factory: four halls, each seen through what it has (3–4 November)

Four scenes of NVIDIA's PhysicalAI-SmartSpaces shown as the four halls of one site, on one shift clock (08:00–08:05 on
4 November 2026, a shared clock; the scenes are simulated and unrelated). Each hall is seen through different, incomplete
sources, and the memory says how far each can be trusted (`factory/sources.csv`):

| Hall | People from | Vehicles and robots from | People tracked against present |
|---|---|---|---|
| A (Warehouse_015) | 13 cameras, SAM 3.1, looked at in tiles and one-minute windows (below) | the same cameras, fused on the floor | 68 of 73 (94%) |
| B (Warehouse_016) | 12 cameras, SAM 3.1, humanoid robots told apart from people | the same cameras | 2 of 5 (44%) |
| C (Warehouse_000) | 6 of its 25 cameras | location tags on every forklift, robot and the transporter | 35 of 50 (70%) |
| D (Warehouse_010) | location badges, worn by 70% of the people | location tags | 28 of 40 (70%) |

Tags are the scene's recorded positions twice a second, thinned to the people who wear badges; real tags would add
their own noise. Compiled with no model into occupancy by 5 m zone every 10 s, every vehicle and robot every 5 s, close
calls (a person within 1.5 m of a moving vehicle or robot: 411 in the five minutes), each hall minute by minute, the
sources table and a note per hall.

### The first picture was wrong, and the supervisor caught it

The first factory memory (3 November, evening) rested on SAM 3.1 asked about each camera's whole view. Two things were
wrong with it, and every answer built on it inherited them:

- **People.** SAM 3.1 returns at most 16 objects in a frame and follows at most 16 objects in one request across the
  whole clip. Hall A's cameras see up to 61 people a frame (Camera_10, measured against the scene's ground truth), and
  every one of the 13 followed exactly 16 people over the five minutes: most people were never boxed.
- **A parked forklift counted as traffic.** Its camera position jumps when people walk in front of it; the tracker read
  that as motion 35% of the shift and charged it with 102 close calls. The safety manager's answer ("stop A-vehicle-c15's
  route through K9 and K10") and the decision safety and logistics then agreed both rested on it. The real movers, the
  autonomous transporter (85 m in the clip) and the mobile robot (75 m), were followed for 31 s and not at all.

Hall A's **camera supervisor** (`argus/sites/factory/supervise.py`, `examples/factory/supervise_factory.py`) holds SAM's
output and the memory built from it to four invariants (an output at its limit, an independent look that disagrees, physics
that is implausible, something the site's knowledge says exists that is missing; the checks it runs are `at_limit`,
`implausible` and, in the example, `missing`), and spends Muse Spark's judgement only on what a check flags. Two runs (Muse Spark Open for its judgements):

| Issue its checks raised | What it saw for itself | Remedy it chose | What changed |
|---|---|---|---|
| All 13 cameras at SAM's limit: each followed exactly 16 people over the clip; Camera_03 also full in 319 of 600 frames | Camera_03: "about 30–34 people in the frame … only 10 have cyan boxes"; Camera_10: "about 58–62 people … only 9 cyan boxes" | split | every view looked at again in tiles at full resolution, and where a tile had followed its 16 people, a minute at a time: people boxed a frame 14 → 41.5 on Camera_03, 12 → 63 on Camera_10, 13 → 53 on Camera_12 (runs `202611040324`, `202611041206`; Meta's API was on a billing hold between them) |
| A-vehicle-c15 "moving 35% of the shift" yet 90% of its positions within 2.8 m of one spot | "a yellow forklift parked unoccupied in the same spot in all three frames while different people walk past" | correct | re-derived from every camera at once: two parked forklifts, the transporter and the robot moving; the correction written to the shared memory |

Person detection on all 13 of Hall A's cameras, against the ground truth's boxes (a box counts when it overlaps a true
one by at least 0.3; the truth's boxes include people almost hidden behind others). Boxes whose feet a tile cut off are
dropped, since they cannot be put on the floor:

| Camera | Found, whole view | Precision, whole view | Found, tiles and windows | Precision, tiles and windows |
|---|---|---|---|---|
| Camera | 47% | 90% | 61% | 74% |
| Camera_01 | 25% | 92% | 60% | 77% |
| Camera_02 | 51% | 90% | 57% | 69% |
| Camera_03 | 39% | 92% | 65% | 81% |
| Camera_04 | 67% | 88% | 59% | 73% |
| Camera_05 | 38% | 90% | 53% | 84% |
| Camera_06 | 67% | 90% | 68% | 86% |
| Camera_07 | 54% | 88% | 58% | 91% |
| Camera_08 | 31% | 85% | 63% | 78% |
| Camera_09 | 70% | 95% | 61% | 81% |
| Camera_10 | 23% | 91% | 65% | 77% |
| Camera_11 | 62% | 89% | 54% | 59% |
| Camera_12 | 26% | 89% | 61% | 76% |
| All 13, weighted by people in view | 35% | 90% | 61% | 77% |

**Machines named by Muse Spark, followed by SAM** (`argus/perception/naming.py`, `examples/factory/name_machines.py`, run
`202611041255`, about $3.5). SAM's "vehicle" boxes say nothing of what each machine is, and the first attempt to have
Muse Spark name them on whole frames called the transporter a forklift and gave parked forklifts drivers. Named from a
close crop of each proposal instead (Muse Spark 1.3), on the 11 cameras that see machines, it named forklifts, the
transporter and the mobile robot, and rejected 22 of SAM's proposals as no machine at all (a person in an orange vest,
people's legs). Each name went to SAM as a box prompt and was followed through the clip; where a named machine was lost
or a new one proposed, the supervisor had that moment named again (51 namings). The names, matched to the fused tracks,
are right against the scene's truth for every Hall A machine: A-transporter-1 (4–300 s) is the transporter, A-robot-1
to -3 the mobile robot, A-forklift-1 and -2 the two parked forklifts.

Tiles nearly double what the crowded cameras find, at some cost in precision; on the quieter cameras (04, 09, 11) the
whole view was already near its best and tiles cut a few people at their edges. Vehicles fused across cameras on the
floor plan, against the ground truth: both forklifts parked (their state agrees with the truth at every sample), the
transporter followed for 296 of 300 s (state agrees 94% of the time), the robot in four pieces. Hall A on the floor:
68 people tracked of 73 present; 92 close calls in memory against 110 in the truth. The old memory had 112, 102 of them
charged to the parked forklift.

### The hive corrects itself

`examples/factory/run_hive_correction.py` (run `202611041316`, Muse Spark Open, $0.02) carries the correction to everyone who
relied on the old picture, through the same stale-copy mechanism the hive uses for plans:

1. The supervisor takes Hall A's memory to change it (5.0 s): the copy the safety manager answered from goes stale.
2. Safety re-reads the finding and withdraws its 08:05 decision: "the 102-close-call basis is invalid". Taking the route
   to withdraw it (12.7 s) makes the copies logistics and floor operations hold stale; each re-reads and says what
   changes for its section ("cancel the stop/reroute … resume normal K-aisle routing"; "restore normal K-aisle
   walkway/staffing in K9/K10").
3. Safety's answer on the corrected memory names the site's real top source of close calls: Hall D's mobile robot
   (61 close calls). Its change collides with logistics' use of the robot's route; logistics accepts stopping it for the
   shift, having weighed the what-if itself ("time shifts still 36–55 close calls vs 61 as-run … re-route/re-time does
   not make it safe"); they agree (33.3 s), and floor operations, its copy stale, re-plans.

Nothing went to people. One run: it shows the mechanism, not how often agents agree.

### Questions from four roles

Seven questions (`examples/factory/run_factory_qa.py`, run `202611041310`, on the corrected memory: the director on Muse Wonder,
the managers on Muse Spark 1.3; the operator's question spoken and transcribed by Muse Voice Transcribe). Every number
comes from exact table queries; none is scored against a gold answer.

| Asked by | Question | Headline (verbatim) |
|---|---|---|
| plant director | Brief me on the whole site: the last five minutes across all four halls | 411 close calls in five minutes across all halls — stop the four worst vehicle routes now |
| floor operations | Where is the floor most crowded, and what should we change? | Most crowded: Hall A cluster K11/K12 — split flow there first |
| logistics | Are our vehicles and robots earning their keep? What would you reassign? | 5 forklifts at 0% moving earn nothing; C/D robots at 62-80% moving carry all the work |
| safety | What single change would remove the most close calls? Show me the evidence. | Stop D-robot-26 — 61 close calls in 5 min, the single biggest repeat source |
| plant director | Plan the next shift for all four halls | 411 close calls in 5 minutes — separate people from robot/transporter routes in the hot zones next shift, do not run it as-is |
| safety | Hall D has no cameras and 70% badges: how far can we trust its numbers? | Hall D safety count is a lower bound — 3 in 10 people are invisible |
| safety (spoken, by an operator) | Is it safe to send the transporter across Hall C right now? | Do not send transporter across Hall C - hold it outside |

The what-if (`argus/sites/factory/team.py`) replays one vehicle against the people as they actually moved, assuming they would
move the same way after a change; it bounds what a change could avoid.

## Memory at a year's scale

All of 2024 for the Houston Ship Channel and Galveston Bay: **207,098,304** AIS position reports (NOAA, 366 daily files,
downloaded and cut to the area in about 10 minutes on a cloud sandbox) compiled in 68 s into 8,755 hourly traffic rows,
231,417 vessel events, 4,737 ships and 135 slowdowns, plus 366 daily reports and 135 slowdown write-ups (Muse Spark Open,
$0.44). None of the positions went into the memory.

**21 questions about the year**, asked at its end, each answer computed from the data; scored on the one answer each arm
committed to (a final line), so a long answer that mentions many numbers is not right by accident:

| How Muse Spark Open got its information | Correct |
|---|---|
| **Argus: the memory as tools** (search, tables, exact plans), about 20K tokens a question | **18** |
| Every daily report of 2024 pasted (235K characters) | 0 (it said the reports do not hold it) |
| The context window filled with the most recent raw vessel events (23,000 events, 23 Nov to 31 Dec, 874K tokens) | 1 |

Seventeen questions reach back months (how often a ship entered the bay or anchored in the year, how many different
tankers entered in a month, visibility at an hour, the queue at an hour, a ship's last entry before a date); four are about
December, inside the long context's window. The long context answered six of the year questions with confident wrong
counts from the weeks it could see, and inside its own window it could not count one tug's 40 bay entries among 23,000
lines; Argus counted them with one table plan. Argus's misses: two monthly tanker counts off by 3%, and one answer with no
final figure. Both Muse Spark Open (Baseten) and Muse Spark 1.3 accepted 874K-token prompts.

The same questions on Meta's own **Muse Spark 1.3**: with the memory as tools, **17 of 21**. Its four misses were monthly
counts 12 to 14 too high, all for one reason: it ended each month at the next month's first day (`"to": "2024-03-01"`),
which the plan grammar reads as including that whole day. With its context window filled with the same 874K tokens of
raw events, asked only the four December questions inside that window: 1 of 4 (it counted the tug's 40 bay entries as
25), for $2.51.

**Forecasts over the whole year**, two hours into each slowdown with at least five earlier ones (129):

| Forecast | Duration error | Queue recovery error (120) |
|---|---|---|
| Similar past slowdowns (median of the five nearest) | 2.52 h | 7.76 h |
| Median of all earlier slowdowns | 2.62 h | 7.45 h |

Over four months (below) the similar-slowdown forecast beat the median clearly (2.56 against 3.01 h); over a year it
barely does, and it does worse on recovery. A long record alone does not make a better forecaster; what the other
sections know does (the airport forecast, above).

## Earlier results (2–3 November), as measured then

### Plant: compressor (MetroPT-3, February to September 2020)

Seven months were replayed into the memory in time order: 51,121 five-minute rows, 212 daily notes and four work orders
(each entered at the time its repair was done). A deterministic watcher fired whenever the compressor's first hour of
an abnormal episode looked severe; Argus then warned the shift supervisor using only what was known at that hour.

| Measure | Result |
|---|---|
| Watcher firings | 13 |
| Reported air leaks with a firing in the 72 hours before | 3 of 4 (14 h, 35.5 h and 62 h ahead) |
| Firings with no reported failure in the next 72 hours | 9 (1.3 a month) |
| Argus's own level on those firings | 7 "act now" (2 before a failure, 5 not); 6 "watch" |
| Model cost of the 13 warnings | $0.030 (Muse Spark 1.3 Contributor) |

Not shown: the watcher's thresholds were chosen after looking at this same data; there is no held-out period. The fourth
leak (29 May) gave no severe first hour within 72 hours. A random alarm at the same rate covers 3 of 4 only 2% of the time.

Thirteen questions about the compressor's history, the same model each way:

| How the model got its information | Correct (of 13) |
|---|---|
| **Argus: the memory as tools** | **13** |
| All 212 daily notes and the work orders pasted into the prompt (76,000 characters) | 9 (missed all three five-minute questions and one count) |
| The last 30 daily notes pasted in | 1 |
| Nothing | 0 |

### Floor (PhysicalAI-SmartSpaces Warehouse_015, four cameras, the whole five minutes)

SAM 3.1 found people and vehicles in every frame at 2 frames a second (2,400 frames per concept, $1.44 for four cameras
and two concepts). **Correction (3 Nov):** the ground truth we first scored against counted only the autonomous
transporter. The NovaCarter robot moves 77 m in the clip (the transporter 87 m; the forklifts never move), and SAM's
"vehicle" finds it in 86% of the frames where a chosen camera sees it (the transporter in 77%). Our first write-up said
the robot was never found; that was wrong, and its true close calls had been scored as false alarms. Against the
corrected truth (121 close calls):

| Pipeline | Precision | Recall |
|---|---|---|
| Last night's, with the motion filter (tuned against the transporter-only truth) | 0.85 | 0.53 |
| Without the motion filter | 0.75 | 0.73 |

### Port, four months (Q1 and December 2024)

122 days replayed in time order: 52 slowdowns. Two hours in, mean absolute error against what happened: total duration,
similar past slowdowns 2.56 h, Argus's stated forecast 2.85 h, median of earlier 3.01 h (49); in fog 5.69 / 6.08 / 7.04 h
(13); queue recovery 12.8 / 14.4 / 12.4 h. Ten questions about the port's history: Argus 8, all daily reports pasted
(100,658 characters) 9, the last 30 reports 0, nothing 0. The same moment written for three readers, a spoken question
through Muse Voice Transcribe, and boards that hand work to Argus all worked (see `docs/ARCHITECTURE.md`).

## Spend

| Where | 2–3 Nov (overnight build) | 3 Nov (the hive, the year) | 3–4 Nov (the factory) |
|---|---|---|---|
| SAM 3.1 | $1.48 | $2.16 (nine more cameras, 10,800 frames) | $5.04 (halls B and C, 25,200 frames); about $26 to $28 (Hall A's 13 cameras in tiles and one-minute windows: 622 requests, about 138,000 frames, including tile layouts later superseded) |
| Muse Spark 1.3 / Contributor | about $0.45 | about $11 (the year questions with an 874K-token window, about $1.09 each; the floor reviews $1.04; probes $0.12) | $0.22 (five questions, the repeat, the decision, a token count of one frame); about $3.5 more to name Hall A's machines from close crops |
| Muse Wonder | — | $0.95 (the director's five monthly reviews) | $0.39 (the director's two questions) |
| Muse Spark Open on Baseten | about $0.25 | about $23 at list prices with the cached-prompt discount Baseten reports (the year test repeated one 874K-token record 21 times); up to about $45 if cached input is billed in full | about $0.5 (the camera supervisor, the hive's correction, five questions asked again) |
| Muse Voice Transcribe | under $0.01 | — | under $0.01 |

Meta's prompt filter refused some harmless requests on every Spark tier, Standard included; those went to Muse Spark Open
on Baseten. Cloud sandbox for the AIS downloads: about one hour of an 8-vCPU sandbox (about $0.55).
