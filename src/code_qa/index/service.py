"""Index lifecycle: cache location (keyed by repo+SHA), build-or-reuse, stats."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..source import RepoSource
from . import store
from .builder import build


def cache_root() -> Path:
    return Path.home() / ".cache" / "code-qa"


def store_path_for(source: RepoSource) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", source.path.name)[:40]
    digest = hashlib.sha1(str(source.path).encode()).hexdigest()[:10]
    sha = source.sha or "live"
    return cache_root() / f"{slug}-{digest}" / sha / "index.sqlite"


def ensure_index(source: RepoSource, rebuild: bool = False) -> tuple[Path, bool]:
    """Return (store_path, built_now). Non-git trees (no SHA) are always rebuilt."""
    path = store_path_for(source)
    if rebuild or source.sha is None or not path.exists():
        index = build(source)
        store.write(index, path)
        return path, True
    return path, False


def stats(path: Path) -> dict:
    return store.read_stats(path)
