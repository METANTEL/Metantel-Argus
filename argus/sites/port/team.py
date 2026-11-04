# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The port as a hive: the channel, the anchorage, the arrivals watcher and the director, on every traffic slowdown.

- The **channel manager** owns the traffic plan for the slowdown (`plan:port/traffic/<event>`): the restriction now and
  when normal deep-draft traffic resumes. It re-plans as the slowdown goes on.
- The **arrivals watcher** publishes how fast ships are joining the queue and how fast the channel takes them in when
  open (`state:port/arrivals/<event>`), computed from the vessel events with no model.
- The **anchorage manager** holds copies of both. When the channel revises its plan, the copy goes stale and the
  anchorage re-plans the queue on the new one before anyone acts on the old one. What it needs from the channel it
  asks for by message; what the two cannot settle goes to people as a decision card.
- The **director** reads both plans and briefs the executive.

The same events are also planned by an anchorage manager working alone (the same memory and tools, no hive), as a
team would without a shared, current plan: it reviews its plan on a fixed schedule and estimates the reopening itself.
"""
from __future__ import annotations

import bisect
import json
import re
import statistics
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from ...agent import Agent, Episodes
from ...hive.link import Link
from ...hive.manager import Manager, facts_for
from ...hive.mind import Charter, Goal
from . import pack as S

KNOWN_AT = {"port/slowdowns.csv": "known_at"}
SITE_TAG = "site=port"
FMT = "%Y-%m-%d %H:%M"

CHARTER = Charter(
    site=S.SITE,
    purpose="Move deep-draft ships through the channel safely and on schedule, keep the offshore queue short, and keep "
            "every party (pilots, tugs, terminals, ships' agents) working from the same, current plan.",
    goals=[Goal("No deep-draft transit in conditions the pilots judge unsafe", "transits during a declared hold"),
           Goal("A fog backlog clears within 24 hours of the channel reopening",
                "hours from the reopening until the offshore queue is back to its size when the slowdown began"),
           Goal("Every section works from the current plan within minutes of a change",
                "hours a section's plan rests on a reopening time the channel no longer expects"),
           Goal("Forecasts people can plan on", "mean absolute error of duration and recovery forecasts, in hours")],
    sections={"port/channel": "traffic in the bay and the ship channel: holds, one-way traffic, when transits resume",
              "port/anchorage": "the offshore queue: who waits, the inbound order, when the queue clears",
              "port/arrivals": "ships approaching from the Gulf and how fast they join the queue",
              "port/weather": "the airport forecast and observations: when fog will lift",
              "port/director": "the port's priorities across sections, the executive picture, what goes to people"},
    authority={"channel manager": "declares and lifts traffic restrictions within the pilots' rules; a hold beyond 12 h or "
                                  "a full closure goes to the harbor master",
               "anchorage manager": "orders the inbound sequence and asks the channel for transit windows; cannot change "
                                    "traffic rules",
               "arrivals watcher": "reports arrivals and capacity; decides nothing",
               "weather watcher": "reports the airport forecast and observations; decides nothing",
               "director": "sets priorities between sections, briefs executives, sends what sections cannot settle to people",
               "people": "the harbor master and the pilots decide closures, exceptions and conflicts between sections"})

CHANNEL_JSON = ('"plan": {"state": "hold|one_way|restricted|normal", "expected_end": "YYYY-MM-DD HH:MM", "duration_hours": '
                'number, "why": "one line"}, where expected_end is when normal deep-draft traffic resumes (UTC) and '
                'duration_hours is the total length of this slowdown from its start')
ANCHOR_JSON = ('"plan": {"assumed_reopen": "YYYY-MM-DD HH:MM", "queue_peak": number, "recovery_hours": number, "clear_by": '
               '"YYYY-MM-DD HH:MM", "sequence": "one line", "ask_channel": "text or empty"}, where assumed_reopen is when '
               'you take deep-draft traffic to resume (UTC), queue_peak the ships waiting at the peak, recovery_hours the '
               'hours from the reopening until the offshore queue is back to its size when the slowdown began, sequence who '
               'goes in first and why, and ask_channel one specific thing you need the channel manager to do or change to '
               'meet the port\'s goals (empty if nothing)')


def event_id(start: str) -> str:
    return start.replace(" ", "T").replace(":", "")


def at(start: str, hours: float) -> str:
    return (datetime.strptime(start, FMT) + timedelta(hours=hours)).strftime(FMT)


def hours_between(a: str, b: str) -> float | None:
    try:
        return (datetime.strptime(str(b)[:16], FMT) - datetime.strptime(str(a)[:16], FMT)).total_seconds() / 3600
    except ValueError:
        return None


def num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class Arrivals:
    """The arrivals watcher's arithmetic, from the compiled feeds: no model, nothing the memory does not also hold."""

    def __init__(self, status: list[dict], events: list[dict]):
        self.status = {r["time"]: r for r in status}
        self.times = sorted(self.status)
        seen = [e for e in events if e["event"] == "seen" and e["zone"] in ("Gulf approach", "Offshore anchorage")]
        self.seen = sorted(e["time"] for e in seen)

    def at(self, now: str) -> dict:
        t = datetime.strptime(now, FMT)
        lo, hi = (t - timedelta(hours=24)).strftime(FMT), now
        arrived = bisect.bisect_left(self.seen, hi) - bisect.bisect_left(self.seen, lo)
        week = [self.status[x] for x in self.times[bisect.bisect_left(self.times, (t - timedelta(days=7)).strftime(FMT)):
                                                      bisect.bisect_left(self.times, now)]]
        inbound = sorted(r["inbound_transits"] for r in week)
        cap = inbound[int(len(inbound) * 0.75)] if inbound else None
        q_now = self.status.get((t - timedelta(hours=1)).strftime(FMT), {}).get("waiting_outside")
        q_before = self.status.get((t - timedelta(hours=3)).strftime(FMT), {}).get("waiting_outside")
        return {"at": now, "arrived_24h": arrived, "arrivals_per_hour": round(arrived / 24, 2), "queue_now": q_now,
                "queue_change_2h": (q_now - q_before) if q_now is not None and q_before is not None else None,
                "inbound_capacity_per_hour": cap,
                "inbound_per_hour_last_week_mean": round(statistics.fmean(inbound), 2) if inbound else None}

    @staticmethod
    def sentence(a: dict) -> str:
        return (f"At {a['at']} UTC: {a['arrived_24h']} deep-draft ships arrived from the Gulf in the last 24 h "
                f"({a['arrivals_per_hour']} an hour); {a['queue_now']} are waiting offshore"
                + (f" ({a['queue_change_2h']:+d} in the last 2 h)" if a["queue_change_2h"] is not None else "")
                + f". In the last week, a busy open hour took {a['inbound_capacity_per_hour']} deep-draft ships inbound through "
                  f"Bolivar Roads (mean {a['inbound_per_hour_last_week_mean']} an hour).")


class Weather:
    """The weather watcher: the airport forecast (TAF) in force and what the airport is reporting now, side by side, so
    a forecast that missed the fog is visible as such."""

    def __init__(self, status: list[dict]):
        from . import taf
        self.taf, self.products = taf, taf.load()
        self.status = {r["time"]: r for r in status}

    def at(self, now: str) -> dict:
        p = self.taf.latest(self.products, now)
        t = datetime.strptime(now, FMT)
        obs = self.status.get((t - timedelta(hours=1)).strftime(FMT), {})
        if not p:
            return {"at": now, "issued": None}
        when, group, cur = self.taf.lift(p, now)
        return {"at": now, "issued": p["issued"], "now_group": cur, "lift_at": when, "lift_group": group,
                "observed_galveston_mi": obs.get("vis_galveston_mi"), "observed_baytown_mi": obs.get("vis_baytown_mi")}

    @staticmethod
    def sentence(w: dict) -> str:
        if not w.get("issued"):
            return f"At {w['at']} UTC no airport forecast is available."
        lifts = ("now" if w["lift_at"] == w["at"] else f"from {w['lift_at']} UTC ({w['lift_group']})")
        return (f"At {w['at']} UTC: the National Weather Service forecast for Galveston airport (issued {w['issued']} UTC) has "
                f"'{w['now_group']}' in force and puts prevailing visibility above 2 miles {lifts}. The airports reported "
                f"visibility {w['observed_galveston_mi'] or 'n/a'} mi at Galveston and {w['observed_baytown_mi'] or 'n/a'} mi at "
                "Baytown in the last hour: if they are far lower than the forecast, the forecast has missed the fog.")


class Router:
    """Messages for several events at once: one inbox per agent, sorted to the event named at the start of each text."""

    def __init__(self, link: Link):
        self.link, self.lock, self.box = link, threading.Lock(), defaultdict(list)

    def take(self, agent: str, ev: str) -> list[dict]:
        with self.lock:
            for m in self.link.inbox(agent):
                tag = re.match(r"\[([^\]]+)\]", m["text"])
                self.box[(agent, tag.group(1) if tag else "")].append(m)
            return self.box.pop((agent, ev), [])


def situation(r: dict, now: str, status: dict) -> str:
    """What the traffic watcher knows when it fires, in the words run_port.py uses."""
    t = datetime.strptime(now, FMT)
    last = status.get((t - timedelta(hours=1)).strftime(FMT), {})
    vis = [v for v in (last.get("vis_galveston_mi"), last.get("vis_baytown_mi")) if v not in (None, "")]
    return (f"At {now} UTC deep-draft traffic in the channels has been low since {r['start']} UTC "
            f"(in the first two hours, {int(float(r['min_traffic_ratio_so_far']) * 100) if r['min_traffic_ratio_so_far'] != '' else '?'}% "
            f"of normal). In the last hour: {last.get('moving_total', '?')} deep-draft ships moving in the channels, "
            f"{last.get('waiting_outside', '?')} waiting offshore, visibility "
            f"{', '.join(f'{v} mi' for v in vis) or 'not reported'} (Galveston, Baytown). Ships waiting offshore when it "
            f"began: {r['queue_start']}.")


def plan_of(out: dict) -> dict:
    p = (out.get("answer") or {}).get("plan")
    return p if isinstance(p, dict) else {}


def make(link: Link, edip, models, provider: str = "baseten", run: str = "") -> dict[str, Manager]:
    episodes = Episodes(edip, {"slowdown": "port/slowdowns.csv"}, {"slowdown": S.EPISODE_FEATURES},
                        {"slowdown": S.EPISODE_OUTCOMES})

    def brain(shared: bool = True) -> Agent:
        return Agent(S.SITE, edip, models, episodes, provider=provider, bounded=True, known_at=KNOWN_AT, site_tag=SITE_TAG,
                     max_calls=7, facts=facts_for(link, run) if run and shared else None)
    spec = {"channel": ("port/channel", "channel manager", "port/channel",
                        "Keep deep-draft traffic moving whenever it is safe, and say early and exactly when it will move again"),
            "anchorage": ("port/anchorage", "anchorage manager", "port/anchorage",
                          "Keep the offshore queue short and clear any backlog within 24 h of the channel reopening"),
            "arrivals": ("port/arrivals", "arrivals watcher", "port/arrivals",
                         "Tell the hive how fast ships are joining the queue and how fast the channel takes them in"),
            "weather": ("port/weather", "weather watcher", "port/weather",
                        "Tell the hive what the airport forecast says about fog lifting, and when it is missing what the "
                        "airports report"),
            "director": ("port/director", "director", "port/director",
                         "Keep the whole port meeting its goals, and bring people in only for what agents cannot settle"),
            "anchorage_alone": ("port/anchorage-alone", "anchorage manager (working alone)", "port/anchorage-alone",
                                "Keep the offshore queue short and clear any backlog within 24 h of the channel reopening")}
    out = {}
    for k, (agent, role, section, goal) in spec.items():
        m = Manager(link, CHARTER, agent, role, section, goal, models=models, provider=provider)
        m.brain = brain(shared=k != "anchorage_alone")      # the comparison arm works alone: no shared facts
        m.tables_prefix = "port/"
        out[k] = m
    return out


def summarise(plan: dict, who: str, version: int, now: str) -> str:
    return f"{who} plan v{version} at {now} UTC: " + json.dumps({k: v for k, v in plan.items() if v not in (None, "")})[:900]
