"""SQLite persistence for the index (one file per repo+SHA).

Holds the symbol graph, precomputed call-paths, and documentation chunks (doc RAG).
`read_index` reconstructs the full Index (with raw, pre-resolution edges) so the delta
builder can reuse parsed results for unchanged files (Inc 6).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .model import CallPathRow, DocChunkRow, EdgeRow, FileRow, Index, SymbolRow

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE files (
    id TEXT PRIMARY KEY, relpath TEXT, language TEXT,
    n_lines INTEGER, is_doc INTEGER, parse_error INTEGER, on_disk INTEGER, content_hash TEXT
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
CREATE TABLE doc_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT, heading TEXT, start_line INTEGER, end_line INTEGER, source TEXT, text TEXT
);
CREATE INDEX idx_sym_name ON symbols(name);
CREATE INDEX idx_sym_file ON symbols(file_id);
CREATE INDEX idx_edge_src ON edges(src_id);
CREATE INDEX idx_edge_dst ON edges(dst_id);
CREATE INDEX idx_cp_entry ON call_paths(entry_id);
CREATE INDEX idx_files_path ON files(relpath);
CREATE INDEX idx_doc_file ON doc_chunks(file_id);
"""


def write(index: Index, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(_SCHEMA)
        con.executemany(
            "INSERT INTO files VALUES (?,?,?,?,?,?,?,?)",
            [(f.id, f.relpath, f.language, f.n_lines, int(f.is_doc), int(f.parse_error),
              int(f.on_disk), f.content_hash) for f in index.files],
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
        con.executemany(
            "INSERT INTO doc_chunks (file_id, heading, start_line, end_line, source, text) VALUES (?,?,?,?,?,?)",
            [(d.file_id, d.heading, d.start_line, d.end_line, d.source, d.text) for d in index.doc_chunks],
        )
        con.executemany("INSERT INTO meta VALUES (?,?)", list(index.meta.items()))
        con.commit()
    finally:
        con.close()


def read_index(path: Path) -> Index:
    """Reconstruct the full Index. Edges come back as raw triples (dst_id dropped) so the
    delta builder can re-resolve them globally after splicing in re-parsed files."""
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        files = [
            FileRow(r["id"], r["relpath"], r["language"], r["n_lines"], bool(r["is_doc"]),
                    bool(r["parse_error"]), bool(r["on_disk"]), r["content_hash"] or "")
            for r in con.execute("SELECT * FROM files")
        ]
        symbols = [
            SymbolRow(r["id"], r["file_id"], r["kind"], r["name"], r["qualname"], r["parent_id"],
                      r["start_line"], r["end_line"], bool(r["is_entry"]))
            for r in con.execute("SELECT * FROM symbols")
        ]
        edges = [
            EdgeRow(r["src_id"], r["type"], None, r["dst_name"])
            for r in con.execute("SELECT src_id, type, dst_name FROM edges")
        ]
        doc_chunks = [
            DocChunkRow(r["file_id"], r["heading"], r["start_line"], r["end_line"], r["source"], r["text"])
            for r in con.execute("SELECT file_id, heading, start_line, end_line, source, text FROM doc_chunks")
        ]
    finally:
        con.close()
    return Index(meta.get("repo_path", ""), meta.get("sha") or None, files, symbols, edges, [], doc_chunks, meta)


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
            "doc_chunks": scalar("SELECT COUNT(*) FROM doc_chunks"),
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
