"""External professional-corpus RAG (Inc 5, A4).

A user-supplied directory of reference material (standards, design docs, domain knowledge)
that grounds the agents' reasoning but is NOT part of the target repo. It's optional and
empty by default. Chunked and embedded with the same machinery as repo docs, but kept in a
SEPARATE store (its own lifecycle: keyed by directory + content hash, not repo SHA), and
queried through a distinct `search_corpus` tool so provenance stays explicit — corpus is
general reference, never an override of the repo's actual code.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from pathlib import Path

from .index.builder import _chunk_doc, _sha
from .index.service import cache_root

_CORPUS_SCHEMA_VERSION = 1
_DOC_EXT = {".md", ".rst", ".txt", ".adoc"}
_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE doc_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT, heading TEXT, start_line INTEGER, end_line INTEGER, source TEXT, text TEXT
);
CREATE TABLE doc_vectors (
    chunk_id INTEGER, model TEXT, dim INTEGER, vec BLOB, PRIMARY KEY(chunk_id, model)
);
"""


def corpus_store_path(corpus_dir: Path) -> Path:
    slug = re.sub(r"[^A-Za-z0-9_.-]", "_", corpus_dir.name)[:40]
    digest = hashlib.sha1(str(corpus_dir).encode()).hexdigest()[:10]
    return cache_root() / f"corpus-{slug}-{digest}" / f"corpus-v{_CORPUS_SCHEMA_VERSION}.sqlite"


def ensure_corpus(corpus_dir: str | os.PathLike, embedder=None) -> Path | None:
    """Build/refresh the corpus store for a directory and return its path, or None if the
    directory is missing or contains no documents. Rebuilds when content changed; embeds
    incrementally when an embedder is given."""
    dirp = Path(corpus_dir).expanduser().resolve()
    if not dirp.is_dir():
        return None
    files = _corpus_files(dirp)
    if not files:
        return None

    agg = _aggregate_hash(dirp, files)
    path = corpus_store_path(dirp)
    if not _is_current(path, agg):
        _build(dirp, files, agg, path)
    if embedder is not None:
        from .embeddings import index_doc_vectors

        index_doc_vectors(path, embedder)
    return path


def _corpus_files(dirp: Path) -> list[str]:
    out: list[str] = []
    for root, dirs, names in os.walk(dirp):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS]
        for name in names:
            if Path(name).suffix.lower() in _DOC_EXT:
                out.append(str((Path(root) / name).relative_to(dirp)).replace("\\", "/"))
    return sorted(out)


def _aggregate_hash(dirp: Path, files: list[str]) -> str:
    h = hashlib.sha1()
    for rel in files:
        try:
            h.update(rel.encode())
            h.update(_sha((dirp / rel).read_bytes()).encode())
        except Exception:
            continue
    return h.hexdigest()


def _is_current(path: Path, agg: str) -> bool:
    if not path.exists():
        return False
    try:
        con = sqlite3.connect(path)
        row = con.execute("SELECT value FROM meta WHERE key='hash'").fetchone()
        con.close()
        return bool(row) and row[0] == agg
    except Exception:
        return False


def _build(dirp: Path, files: list[str], agg: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    rows = []
    for rel in files:
        try:
            text = (dirp / rel).read_text("utf-8", "replace")
        except Exception:
            continue
        for c in _chunk_doc(rel, text, source="corpus"):
            rows.append((c.file_id, c.heading, c.start_line, c.end_line, c.source, c.text))
    con = sqlite3.connect(path)
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO doc_chunks (file_id, heading, start_line, end_line, source, text) VALUES (?,?,?,?,?,?)",
            rows,
        )
        con.executemany("INSERT INTO meta VALUES (?,?)", [("hash", agg), ("n_chunks", str(len(rows))), ("dir", str(dirp))])
        con.commit()
    finally:
        con.close()
