# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The seams of the harness: the memory it is written against, the managers built on it, and a package whose every module
imports. Nothing here calls a model or a memory."""
from __future__ import annotations

import importlib
import pkgutil
from types import SimpleNamespace

import argus
from argus.hive.link import Link
from argus.hive.manager import Manager, tables_note
from argus.hive.mind import Charter, Goal
from argus.memory import Coordination, DryEdip, Edip, Memory

CHARTER = Charter("a test site", "to test", [Goal("pass")], {"s": "a section"}, {"manager": "decides small things"})


def test_the_metantel_client_is_a_memory_and_the_hive_link_is_the_coordination():
    assert isinstance(DryEdip(), Memory) and issubclass(Edip, Memory)
    assert isinstance(Link(DryEdip()), Coordination)


def test_a_memory_behind_the_protocol_is_enough_for_the_replay(tmp_path):
    from argus.replay import Replay

    class Notebook:                       # a memory that keeps rows in a dict: no network, no keys
        def __init__(self):
            self.tables, self.items = {}, {}

        def ingest(self, name, text, kind="document", tags=None):
            if kind == "table":
                self.tables[name] = [line.split(",") for line in text.strip().splitlines()]
            else:
                self.items[name] = text

        def append(self, name, rows):
            self.tables[name] += [[str(v) for v in r] for r in rows]

    m = Notebook()
    rp = Replay(m, tmp_path / "log.jsonl")
    rp.stream("t.csv", ["time", "v"], [{"time": "2024-01-01 01:00", "v": 1}, {"time": "2024-01-02 01:00", "v": 2}], "time")
    rp.doc("2024-01-01 12:00", "note.md", "day one")
    rp.run()
    assert m.tables["t.csv"] == [["time", "v"], ["2024-01-01 01:00", "1"], ["2024-01-02 01:00", "2"]]
    assert m.items == {"note.md": "day one"}


def test_a_manager_lists_the_tables_of_its_section_only_when_told_to():
    class Notebook:
        def tables(self):
            return {"tables": [{"artifact": "port/slowdowns.csv", "rows": 3, "columns": [{"name": "start"}, {"name": "hours"}]},
                               {"artifact": "plant/apu.csv", "rows": 9, "columns": [{"name": "time"}]}]}

    class Brain:
        edip = Notebook()

        def run(self, mode, text, now, audience, context="", preamble="", extra_json=""):
            self.context = context
            return SimpleNamespace(answer={"ok": True}, usd=0.0, seconds=0.0, trace=[])

    m = Manager(None, CHARTER, "port/channel", "channel manager", "port/channel", "keep it moving")
    m.brain = Brain()
    m.think("answer", "?", "2024-01-01 00:00", "manager", "", "")
    assert m.brain.context == ""                                          # no prefix: no table list
    m.tables_prefix = "port/"
    m.think("answer", "?", "2024-01-01 00:00", "manager", "", "")
    assert "port/slowdowns.csv (3 rows): start, hours" in m.brain.context and "plant/" not in m.brain.context
    assert tables_note(Notebook(), "port/").startswith("TABLES (no need to list them again):")


def test_every_module_of_the_package_imports():
    failed = []
    for mod in pkgutil.walk_packages(argus.__path__, "argus."):
        try:
            importlib.import_module(mod.name)
        except Exception as e:  # noqa: BLE001 - the list of what broke is the assertion
            failed.append((mod.name, repr(e)[:160]))
    assert not failed


def test_keys_come_from_plainly_named_environment_variables_and_are_never_shown(monkeypatch, tmp_path):
    from argus import config
    monkeypatch.setenv("ARGUS_EDIP_ENV", str(tmp_path / "none.env"))          # not the project's own key files
    monkeypatch.setenv("ARGUS_META_ENV", str(tmp_path / "none.env"))
    for name, value in {"ARGUS_SPACE": "0123456789abcdef", "ARGUS_INGEST_KEY": "ingest-secret", "ARGUS_SERVE_KEY": "serve-secret",
                        "ARGUS_META_KEY": "meta-secret", "ARGUS_BASETEN_KEY": "baseten-secret"}.items():
        monkeypatch.setenv(name, value)
    k = config.keys()
    assert (k.space, k.ingest_key, k.serve_key, k.meta_key, k.baseten_key) == (
        "0123456789abcdef", "ingest-secret", "serve-secret", "meta-secret", "baseten-secret")
    assert k.baseten_model == "meta-models/muse-spark-open-1026" and k.metantel_api == "https://api.metantel.com"
    assert "secret" not in repr(k)


def test_the_hive_does_not_import_a_site():
    """The base classes of the hive (members, managers, supervisors, the link) are the harness: no site pack loads with them."""
    import subprocess
    import sys
    code = ("import sys, argus.hive.mind, argus.hive.link, argus.hive.manager, argus.hive.supervise, argus.agent, argus.replay\n"
            "loaded = sorted(m for m in sys.modules if m.startswith('argus.sites') or m == 'argus.perception.tiles')\n"
            "assert not loaded, loaded")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-400:]
