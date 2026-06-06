"""SQLite persistence for the index (one file per repo+SHA; vectors land here in Inc 2)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .model import Index

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (
    id TEXT PRIMARY KEY, relpath TEXT, language TEXT,
    n_lines INTEGER, is_doc INTEGER, parse_error INTEGER, on_disk INTEGER
);
CREATE TABLE symbols (
    id TEXT PRIMARY KEY, file_id TEXT, kind TEXT, name TEXT, qualname TEXT,
    parent_id TEXT, start_line INTEGER, end_line INTEGER, is_entry INTEGER
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id TEXT, type TEXT, dst_id TEXT, dst_name TEXT
);
CREATE TABLE call_paths (entry_id TEXT, from_id TEXT, to_id TEXT, depth INTEGER);
CREATE INDEX idx_sym_name ON symbols(name);
CREATE INDEX idx_sym_file ON symbols(file_id);
CREATE INDEX idx_edge_src ON edges(src_id);
CREATE INDEX idx_edge_dst ON edges(dst_id);
CREATE INDEX idx_cp_entry ON call_paths(entry_id);
CREATE INDEX idx_files_path ON files(relpath);
"""


def write(index: Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO files VALUES (?,?,?,?,?,?,?)",
            [(f.id, f.relpath, f.language, f.n_lines, int(f.is_doc), int(f.parse_error), int(f.on_disk)) for f in index.files],
        )
        con.executemany(
            "INSERT INTO symbols VALUES (?,?,?,?,?,?,?,?,?)",
            [(s.id, s.file_id, s.kind, s.name, s.qualname, s.parent_id, s.start_line, s.end_line, int(s.is_entry)) for s in index.symbols],
        )
        con.executemany(
            "INSERT INTO edges (src_id, type, dst_id, dst_name) VALUES (?,?,?,?)",
            [(e.src_id, e.type, e.dst_id, e.dst_name) for e in index.edges],
        )
        con.executemany(
            "INSERT INTO call_paths VALUES (?,?,?,?)",
            [(c.entry_id, c.from_id, c.to_id, c.depth) for c in index.call_paths],
        )
        con.executemany("INSERT INTO meta VALUES (?,?)", list(index.meta.items()))
        con.commit()
    finally:
        con.close()


def read_stats(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        scalar = lambda q: con.execute(q).fetchone()[0]  # noqa: E731
        return {
            "meta": dict(con.execute("SELECT key, value FROM meta").fetchall()),
            "files_total": scalar("SELECT COUNT(*) FROM files"),
            "files_by_lang": dict(
                con.execute("SELECT language, COUNT(*) FROM files GROUP BY language ORDER BY 2 DESC").fetchall()
            ),
            "doc_files": scalar("SELECT COUNT(*) FROM files WHERE is_doc=1"),
            "assets": scalar("SELECT COUNT(*) FROM files WHERE language IN ('binary','other')"),
            "not_downloaded": scalar("SELECT COUNT(*) FROM files WHERE on_disk=0"),
            "parse_errors": scalar("SELECT COUNT(*) FROM files WHERE parse_error=1"),
            "symbols_total": scalar("SELECT COUNT(*) FROM symbols"),
            "symbols_by_kind": dict(
                con.execute("SELECT kind, COUNT(*) FROM symbols GROUP BY kind ORDER BY 2 DESC").fetchall()
            ),
            "edges_by_type": dict(
                con.execute("SELECT type, COUNT(*) FROM edges GROUP BY type ORDER BY 2 DESC").fetchall()
            ),
            "calls_total": scalar("SELECT COUNT(*) FROM edges WHERE type='calls'"),
            "calls_resolved": scalar("SELECT COUNT(*) FROM edges WHERE type='calls' AND dst_id IS NOT NULL"),
            "entries_total": scalar("SELECT COUNT(*) FROM symbols WHERE is_entry=1"),
            "entries": con.execute(
                "SELECT qualname, file_id FROM symbols WHERE is_entry=1 ORDER BY file_id LIMIT 12"
            ).fetchall(),
            "call_path_edges": scalar("SELECT COUNT(*) FROM call_paths"),
            "entries_with_paths": scalar("SELECT COUNT(DISTINCT entry_id) FROM call_paths"),
            "max_call_depth": scalar("SELECT COALESCE(MAX(depth), 0) FROM call_paths"),
        }
    finally:
        con.close()
