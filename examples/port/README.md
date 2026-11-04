# Port of Houston: a year of ship positions

The scale test. The site is the Houston Ship Channel, Galveston Bay and the Bolivar Roads entrance, for all of 2024: 207
million ship positions, which as text are 5 to 8 billion model tokens. The harness compiles them into 8,755 hourly rows of
traffic, 231,417 vessel events and 135 slowdowns with how each played out, and a team of agents plans on them.

**Data (public).**

- NOAA Office for Coastal Management, *Nationwide Automatic Identification System 2024* (CC0 1.0), from U.S. Coast Guard data.
- Iowa Environmental Mesonet: airport observations (ASOS) and forecasts (TAF) for Galveston and Baytown.

## Run

```sh
python examples/port/fetch_weather.py 2024-01-01 2025-01-01
python examples/port/fetch_ais.py --workers 3                        # NOAA's daily files (about 80 GB to download), keeping
                                                                     # the bay and the channel (2 GB)
python examples/port/compile_port.py                                 # a year into a database file, then the compiled rows
python examples/port/ingest_port_year.py                             # the whole year into the memory at once, each item stamped
                                                                     # with when it became known
mkdir -p data/weather && curl -o data/weather/taf_KGLS_2024.csv \
  "https://mesonet.agron.iastate.edu/cgi-bin/request/taf.py?station=KGLS&sts=2023-12-31T00:00Z&ets=2025-01-02T00:00Z&fmt=csv"
                                                                     # the airport's own forecasts, for the weather watcher
python examples/port/run_hive_port.py --weather                      # every fog slowdown: the hive against a lone planner
python examples/port/eval_year.py                                    # 21 questions about the year, three ways
python examples/ask.py port "How long did the last fog slowdown last?" --now "2024-03-31 23:00" --audience operator
```

`run_port.py` is the simpler replay: the days go into the memory in time order and Argus warns as slowdowns begin.
`hive_teach.py` and `run_hive_review.py` are people teaching the hive and management steering it; `eval_taf.py` and
`eval_analog_year.py` are the baselines (the weather service's own forecast; the analog rule with no model).

## What it shows

- **A year does not fit in a window; a memory does.** 21 questions about 2024: 18 answered from the memory (about 20K tokens a
  question), 0 when the same model was handed every daily report, 1 when its window was filled with the latest 874 thousand
  tokens of raw events. The year's events alone are about 8.8 million tokens as text.
- **Forecasts from similar past slowdowns** ([`argus/agent.py`](../../argus/agent.py), `Episodes.similar`), with their spread.
- **A hive of sections on one plan** ([`team.py`](../../argus/sites/port/team.py)): the channel manager owns the traffic plan;
  the arrivals and weather watchers publish what they see; the anchorage manager plans on copies of all three. When the
  channel revises its plan, the anchorage's copy goes stale and it re-plans before anyone acts on the old one. Across the
  year's fog slowdowns the anchorage planned on the channel's current reopening at 208 of 208 checkpoints; working alone it
  was more than two hours off at 36 to 53% of them. With the weather watcher beside the memory, the channel manager's
  fog-duration forecast two hours in was 3.9 h off, against 6.9 h from memory alone and 3.7 h from the airport's own forecast.

Results and limits: [`docs/RESULTS.md`](../../docs/RESULTS.md).
