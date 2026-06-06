"""Index lifecycle: cache location (keyed by repo+SHA), build-or-reuse, stats."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ..source import RepoSource
from . import store
from .builder import build, build_delta
from .store import SCHEMA_VERSION


def cache_root() -> Path:
    return Path.home() / ".cache" / "code-qa"


def store_path_for(source: RepoSource) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", source.path.name)[:40]
    digest = hashlib.sha1(str(source.path).encode()).hexdigest()[:10]
    sha = source.sha or "live"
    # Schema version in the path so a schema bump invalidates old caches.
    return cache_root() / f"{slug}-{digest}" / sha / f"index-v{SCHEMA_VERSION}.sqlite"


def _find_base_index(source: RepoSource, target: Path) -> Path | None:
    """A prior same-schema index to delta from: the live index for non-git trees, else the
    most recent sibling SHA's index for the same repo."""
    name = f"index-v{SCHEMA_VERSION}.sqlite"
    if source.sha is None:
        return target if target.exists() else None
    repo_dir = target.parent.parent  # {slug-digest}/{sha}/index... -> {slug-digest}
    if not repo_dir.is_dir():
        return None
    cands = [p for p in repo_dir.glob(f"*/{name}") if p != target and p.exists()]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def ensure_index(source: RepoSource, rebuild: bool = False) -> tuple[Path, bool]:
    """Return (store_path, built_now). Exact (repo, SHA) hits reuse the cache; otherwise build —
    incrementally against a prior index when one exists (re-parse only changed files)."""
    path = store_path_for(source)
    if not rebuild and source.sha is not None and path.exists():
        return path, False  # exact-SHA cache hit
    base = None if rebuild else _find_base_index(source, path)
    if base is not None:
        try:
            index = build_delta(source, store.read_index(base))
        except Exception:
            index = build(source)  # any delta hiccup -> safe full rebuild
    else:
        index = build(source)
    store.write(index, path)
    return path, True


def stats(path: Path) -> dict:
    return store.read_stats(path)
