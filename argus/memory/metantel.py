# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""The client of Metantel's Managed Memory Harness, over its public API.

Two keys per space: the ingest key for what feeds the memory, the serve key for the agents that read from it.
"""
from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Any

import httpx

from ..config import Keys, keys as load_keys


class EdipError(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status, self.body = status, body
        super().__init__(f"{status}: {str(body)[:300]}")


class Edip:
    def __init__(self, k: Keys | None = None, timeout: float = 180.0):
        self.k = k or load_keys()
        self.base = f"{self.k.metantel_api}/api/{self.k.space}"
        self.http = httpx.Client(timeout=timeout)
        self.calls = 0

    # -- plumbing ---------------------------------------------------------------------------------------------------
    def _call(self, method: str, path: str, key: str, body: Any = None, params: dict | None = None) -> Any:
        for wait in (1, 2, 4, 8, 0):
            try:
                r = self.http.request(method, f"{self.base}{path}", headers={"Authorization": f"Bearer {key}"},
                                      json=body, params=params)
            except httpx.TransportError:
                if not wait:
                    raise
                time.sleep(wait)
                continue
            self.calls += 1
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", wait or 2)))
                continue
            if r.status_code >= 500 and wait:
                time.sleep(wait)
                continue
            try:
                data = r.json()
            except ValueError:
                data = r.text
            if r.status_code >= 400:
                raise EdipError(r.status_code, data)
            return data
        raise EdipError(599, f"{path}: still failing")

    def _read(self, method: str, path: str, body: Any = None, params: dict | None = None) -> Any:
        return self._call(method, path, self.k.serve_key, body, params)

    def _write(self, method: str, path: str, body: Any = None) -> Any:
        return self._call(method, path, self.k.ingest_key, body)

    # -- serving ----------------------------------------------------------------------------------------------------
    def search(self, query: str, limit: int = 10, codes: list[str] | None = None, passages: bool = False) -> dict:
        body: dict[str, Any] = {"query": query, "limit": limit}
        if codes:
            body["codes"] = codes
        if passages:
            body["passages"] = True
        return self._read("POST", "/search", body)

    def items(self, limit: int = 100, codes: list[str] | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if codes:
            params["codes"] = ",".join(codes)
        return self._read("GET", "/items", params=params)

    def tables(self) -> dict:
        return self._read("GET", "/tables")

    def query(self, plan: dict | None = None, question: str | None = None, table: str | None = None,
              budget: int = 6000) -> dict:
        body: dict[str, Any] = {"budget": budget}
        if plan is not None:
            body["plan"] = plan
        if question is not None:
            body["question"] = question
        if table:
            body["table"] = table
        return self._read("POST", "/tables/query", body)

    def flow(self, stages: list[dict], inputs: dict | None = None, description: str = "") -> dict:
        cfg: dict[str, Any] = {"stages": stages}
        if description:
            cfg["description"] = description
        return self._read("POST", "/flows/run", {"config": cfg, "inputs": inputs or {}})

    def flow_graph(self, board: dict, inputs: dict | None = None) -> dict:
        """Run a board (a graph of parts) without saving it."""
        return self._read("POST", "/flows/run", {"config": {**board, "kind": "graph"}, "inputs": inputs or {}})

    def workflow(self, slug: str, inputs: dict | None = None) -> dict:
        return self._read("POST", f"/workflows/{slug}/run", {"inputs": inputs or {}})

    def classify(self, state: str, questions: dict) -> dict:
        return self._read("POST", "/classify", {"state": state, "questions": questions})

    def usage(self) -> dict:
        return self._read("GET", "/usage")

    # -- ingestion --------------------------------------------------------------------------------------------------
    def ingest(self, name: str, text: str, kind: str = "document", tags: list | None = None) -> dict:
        body: dict[str, Any] = {"name": name, "text": text, "kind": kind}
        if tags:
            body["tags"] = tags
        return self._write("POST", "/ingest", body)

    def ingest_table(self, name: str, header: list[str], rows: list[list[Any]], tags: list | None = None) -> dict:
        """Create (or replace) a table from rows; a table larger than one ingest goes through append."""
        n = 20000
        while True:                      # an ingest takes at most 2,000,000 characters: wide rows go in a smaller first part
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(header)
            first = rows[:n]
            w.writerows(first)
            if len(buf.getvalue()) < 1_900_000 or n <= 500:
                break
            n //= 2
        out = self.ingest(name, buf.getvalue(), kind="table", tags=tags)
        for i in range(len(first), len(rows), 20000):
            self.append(name, rows[i:i + 20000])
        return out

    def append(self, artifact: str, rows: list[list[Any]]) -> dict:
        return self._write("POST", "/tables/append", {"artifact": artifact, "rows": [[_cell(v) for v in r] for r in rows]})

    def upload_file(self, path: Path, name: str, mime: str) -> dict:
        size = path.stat().st_size
        got = self._write("POST", "/uploads", {"files": [{"name": name, "size": size, "type": mime}]})
        f = (got.get("files") or got.get("uploads") or [got])[0]
        data = path.read_bytes()
        r = self.http.put(f["uploadUrl"], content=data, headers={"Content-Type": mime})
        if r.status_code >= 400:
            raise EdipError(r.status_code, r.text[:300])
        return self._write("POST", f"/uploads/{f['id']}/done", {})


def _cell(v: Any) -> str:
    return "" if v is None else str(v)


class DryEdip(Edip):
    """Records what would be sent and answers reads with nothing, for testing a pipeline without touching a space."""

    def __init__(self):  # noqa: D107 - no keys, no network
        self.calls, self.sent = 0, {"ingest": 0, "append": 0, "rows": 0}

    def _call(self, method: str, path: str, key: str, body: Any = None, params: dict | None = None) -> Any:
        self.calls += 1
        if path == "/ingest":
            self.sent["ingest"] += 1
            return {"ok": True}
        if path == "/tables/append":
            self.sent["append"] += 1
            self.sent["rows"] += len(body["rows"])
            return {"appended": len(body["rows"])}
        if path == "/tables/query":
            return {"text": "", "result": {"columns": [], "rows": []}}
        return {}

    @property
    def k(self):  # type: ignore[override]
        from ..config import Keys
        return Keys("dry", "dry", "", "", "", "", "", "")
