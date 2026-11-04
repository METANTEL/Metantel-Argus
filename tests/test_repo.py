# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The repository holds together: every import in the examples resolves (they are read, never run: several would call a
live service), and every link in the documents lands."""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_import_in_the_examples_resolves():
    bad = []
    for path in sorted((ROOT / "examples").rglob("*.py")):
        src = path.read_text()
        for node in ast.walk(ast.parse(src, str(path))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "argus":
                stmt = ast.get_source_segment(src, node)
                try:
                    exec(compile(stmt, str(path), "exec"), {})
                except Exception as e:  # noqa: BLE001 - the list of what broke is the assertion
                    bad.append((str(path.relative_to(ROOT)), stmt, repr(e)[:120]))
    assert not bad


def test_every_relative_link_in_the_documents_lands():
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), *sorted((ROOT / "examples").rglob("*.md"))]
    bad = []
    for doc in docs:
        for m in re.finditer(r"\]\(([^)\s]+)\)", doc.read_text()):
            target = m.group(1).split("#")[0]
            if target and not target.startswith(("http://", "https://", "mailto:")) and not (doc.parent / target).exists():
                bad.append((str(doc.relative_to(ROOT)), m.group(1)))
    assert not bad


def test_the_console_says_what_it_needs_when_the_factory_is_not_built(tmp_path):
    import os
    import subprocess
    import sys
    env = {**os.environ, "ARGUS_DATA": str(tmp_path)}
    done = subprocess.run([sys.executable, "-m", "argus.console", "--port", "0"], env=env, capture_output=True, text=True,
                          timeout=60, cwd=ROOT)
    assert done.returncode != 0 and "examples/factory/README.md" in done.stderr
