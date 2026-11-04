# SPDX-FileCopyrightText: 2026 JMV Metantel Private Limited
# SPDX-License-Identifier: AGPL-3.0-only
"""Where Argus finds its keys and its data.

Keys are read from the environment, or from env files, and never printed:

    ARGUS_SPACE, ARGUS_INGEST_KEY, ARGUS_SERVE_KEY   a Managed Memory Harness space and its keys (METANTEL_API: its address)
    ARGUS_META_KEY                                     the Meta Model API (SAM 3.1, Muse Spark, Muse Voice Transcribe)
    ARGUS_BASETEN_KEY, ARGUS_BASETEN_URL, ARGUS_BASETEN_MODEL   Muse Spark Open served by Baseten (optional)

Two env files are also looked for in the repository folder (both are git-ignored), with the names this project's own
setup uses:
`EDIP-Keys/api-keys.env` (SANDBOX_SPACE, SANDBOX_INGEST, SANDBOX_SERVE) and `Meta-Keys/api-keys.env` (MetaAIKey,
BasetenURL, BastenXMetaKey, BastenAllowedModelCode). Environment variables win over the files.
"""
from __future__ import annotations

import os
import pickle
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("ARGUS_DATA", ROOT / "data"))
RUNS = Path(os.environ.get("ARGUS_RUNS", ROOT / "runs"))


# Modules the package kept its classes in before it was laid out by capability: compiled caches written then still load.
_MOVED = {"argus.feeds.factory": "argus.sites.factory.feed", "argus.feeds.floor": "argus.perception.floor",
          "argus.feeds.port": "argus.sites.port.feed", "argus.feeds.equipment": "argus.sites.plant.feed"}


class _CacheUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        return super().find_class(_MOVED.get(module, module), name)


def load_cache(path: Path):
    """A compiled cache this harness wrote earlier (a pickle of its own dataclasses: not for files from anywhere else)."""
    with path.open("rb") as f:
        return _CacheUnpickler(f).load()


def _load(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _env() -> dict[str, str]:
    merged: dict[str, str] = {}
    merged.update(_load(Path(os.environ.get("ARGUS_EDIP_ENV", ROOT / "EDIP-Keys" / "api-keys.env"))))
    merged.update(_load(Path(os.environ.get("ARGUS_META_ENV", ROOT / "Meta-Keys" / "api-keys.env"))))
    merged.update({k: v for k, v in os.environ.items() if k in merged or k.startswith(("METANTEL_", "ARGUS_"))})
    return merged


@dataclass(frozen=True)
class Keys:
    metantel_api: str
    space: str
    ingest_key: str
    serve_key: str
    meta_key: str
    baseten_url: str
    baseten_key: str
    baseten_model: str

    def __repr__(self) -> str:  # never show a secret, even in a traceback
        return f"Keys(api={self.metantel_api!r}, space={self.space[:6]}…)"


def keys() -> Keys:
    e = _env()
    return Keys(
        metantel_api=e.get("METANTEL_API", "https://api.metantel.com").rstrip("/"),
        space=e.get("ARGUS_SPACE") or e.get("SANDBOX_SPACE", ""),
        ingest_key=e.get("ARGUS_INGEST_KEY") or e.get("SANDBOX_INGEST", ""),
        serve_key=e.get("ARGUS_SERVE_KEY") or e.get("SANDBOX_SERVE", ""),
        meta_key=e.get("ARGUS_META_KEY") or e.get("MetaAIKey", ""),
        baseten_url=(e.get("ARGUS_BASETEN_URL") or e.get("BasetenURL") or "https://inference.baseten.co/v1").rstrip("/"),
        baseten_key=e.get("ARGUS_BASETEN_KEY") or e.get("BastenXMetaKey", ""),
        baseten_model=e.get("ARGUS_BASETEN_MODEL") or e.get("BastenAllowedModelCode") or "meta-models/muse-spark-open-1026",
    )
