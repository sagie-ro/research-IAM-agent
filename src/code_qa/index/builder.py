"""Build the index from a RepoSource: inventory every file, parse source/docs,
resolve edges, precompute call-paths, chunk documentation for RAG.

Inventory covers the FULL tree (via RepoSource.tracked_paths) so binary/asset files
are recorded as metadata (path + type), even when their bytes were never downloaded.
Only source/doc files that are materialized on disk are read and parsed.

Parsing is per-file (`_parse_file`) and side-effect free; `_assemble` does the global,
cheap work (cross-file resolution + call-paths). Splitting it this way lets the delta
builder (service.py / Inc 6) reuse parsed results for unchanged files and only re-parse
what changed, then re-assemble. Resolution is hand-rolled and precision-first (Option A /
D2): a call/extends/implements edge is linked only when its simple target name resolves
unambiguously; ambiguous targets stay unlinked (false negatives, not false edges).
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from ..languages import profile_for
from ..source import BINARY_EXT, RepoSource
from . import store
from .model import CallPathRow, DocChunkRow, EdgeRow, FileRow, Index, SymbolRow

_DOC_SUFFIX = {".md", ".rst", ".txt", ".adoc"}
_NAME_INDEXED = {"function", "method", "class", "interface", "enum", "record", "constructor"}
_MAX_DEPTH = 8
_MAX_NODES = 200
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


@dataclass
class ParsedFile:
    """Per-file parse result (no cross-file links) — the reuse unit for delta builds."""

    file: FileRow
    symbols: list[SymbolRow]
    raw_edges: list[tuple[str, str, str]]  # (src_id, type, dst_name) — pre-resolution
    doc_chunks: list[DocChunkRow]


def build(source: RepoSource) -> Index:
    sys.setrecursionlimit(20000)
    parsed = [_parse_file(source.path, rel, source.materialized(rel)) for rel in source.tracked_paths()]
    return _assemble(source.path, source.sha, parsed)


def _parse_file(root: Path, rel: str, on_disk: bool) -> ParsedFile:
    profile = profile_for(rel)
    doc = _is_doc(rel)

    if profile is not None and on_disk:
        try:
            data = (root / rel).read_bytes()
        except Exception:
            return ParsedFile(FileRow(rel, rel, "other", 0, doc, False, on_disk), [], [], [])
        parsed = profile.parse(data, rel)
        file = FileRow(rel, rel, parsed.language, data.count(b"\n") + 1, doc, parsed.parse_error, True, _sha(data))
        symbols: list[SymbolRow] = []
        raw_edges: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for ps in parsed.symbols:
            sid = f"{rel}::{ps.qualname}"
            if sid in seen:
                sid = f"{sid}@{ps.start_line}"
            seen.add(sid)
            symbols.append(
                SymbolRow(sid, rel, ps.kind, ps.name, ps.qualname, None, ps.start_line, ps.end_line, ps.is_entry)
            )
        for e in parsed.edges:
            src_id = rel if not e.src_qualname else f"{rel}::{e.src_qualname}"
            raw_edges.append((src_id, e.type, e.dst_name))
        return ParsedFile(file, symbols, raw_edges, [])

    if doc and on_disk:
        try:
            data = (root / rel).read_bytes()
        except Exception:
            return ParsedFile(FileRow(rel, rel, "doc", 0, True, False, True), [], [], [])
        text = data.decode("utf-8", "replace")
        file = FileRow(rel, rel, "doc", text.count("\n") + 1, True, False, True, _sha(data))
        return ParsedFile(file, [], [], _chunk_doc(rel, text))

    # Inventory-only: binary/asset, or a source/doc file not materialized (sparse).
    language = "binary" if Path(rel).suffix.lower() in BINARY_EXT else ("doc" if doc else "other")
    return ParsedFile(FileRow(rel, rel, language, 0, doc, False, on_disk), [], [], [])


def _assemble(root: Path, sha: str | None, parsed: list[ParsedFile]) -> Index:
    files = [pf.file for pf in parsed]
    symbols = [s for pf in parsed for s in pf.symbols]
    raw_edges = [e for pf in parsed for e in pf.raw_edges]
    doc_chunks = [c for pf in parsed for c in pf.doc_chunks]
    parse_errors = sum(1 for f in files if f.parse_error)

    sym_ids = {s.id for s in symbols}
    by_name: dict[str, list[str]] = defaultdict(list)
    for s in symbols:
        if "." in s.qualname:
            pid = f"{s.file_id}::{s.qualname.rsplit('.', 1)[0]}"
            s.parent_id = pid if pid in sym_ids else s.file_id
        else:
            s.parent_id = s.file_id
        if s.kind in _NAME_INDEXED:
            by_name[s.name].append(s.id)

    edges: list[EdgeRow] = []
    adj: dict[str, set[str]] = defaultdict(set)
    for src_id, typ, dst_name in raw_edges:
        dst_id = None
        if typ in ("calls", "extends", "implements"):
            cands = by_name.get(dst_name, [])
            if len(cands) == 1:
                dst_id = cands[0]
            elif len(cands) > 1:
                src_file = src_id.split("::", 1)[0]
                same = [c for c in cands if c.split("::", 1)[0] == src_file]
                if len(same) == 1:
                    dst_id = same[0]
            if dst_id and typ == "calls":
                adj[src_id].add(dst_id)
        edges.append(EdgeRow(src_id, typ, dst_id, dst_name))

    call_paths: list[CallPathRow] = []
    entries = [s.id for s in symbols if s.is_entry]
    for eid in entries:
        visited = {eid}
        queue = deque([(eid, 0)])
        emitted = 0
        while queue and emitted < _MAX_NODES:
            cur, depth = queue.popleft()
            if depth >= _MAX_DEPTH:
                continue
            for nxt in sorted(adj.get(cur, ())):
                call_paths.append(CallPathRow(eid, cur, nxt, depth + 1))
                emitted += 1
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append((nxt, depth + 1))
                if emitted >= _MAX_NODES:
                    break

    meta = {
        "repo_path": str(root),
        "sha": sha or "",
        "schema_version": str(store.SCHEMA_VERSION),
        "parse_errors": str(parse_errors),
        "n_entries": str(len(entries)),
        "doc_chunks": str(len(doc_chunks)),
    }
    return Index(str(root), sha, files, symbols, edges, call_paths, doc_chunks, meta)


def _chunk_doc(rel: str, text: str, source: str = "repo", max_chunks: int = 80, max_chars: int = 1600) -> list[DocChunkRow]:
    """Split a doc file into heading-delimited sections (the doc-RAG unit). Falls back to
    fixed line windows when there are no markdown headings."""
    lines = text.splitlines()
    heads = [(i, m.group(2).strip()) for i, ln in enumerate(lines) if (m := _HEADING.match(ln))]
    if heads:
        bounds: list[tuple[int, int, str]] = []
        if heads[0][0] > 0:
            bounds.append((0, heads[0][0], "(intro)"))
        for k, (i, title) in enumerate(heads):
            end = heads[k + 1][0] if k + 1 < len(heads) else len(lines)
            bounds.append((i, end, title))
    else:
        bounds = [(i, min(i + 50, len(lines)), Path(rel).name) for i in range(0, len(lines), 50)]

    chunks: list[DocChunkRow] = []
    for start, end, title in bounds:
        body = "\n".join(lines[start:end]).strip()
        if not body:
            continue
        chunks.append(DocChunkRow(rel, title[:160], start + 1, end, source, body[:max_chars]))
        if len(chunks) >= max_chunks:
            break
    return chunks


def _sha(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _is_doc(relpath: str) -> bool:
    low = relpath.lower()
    name = Path(low).name
    return (
        Path(low).suffix in _DOC_SUFFIX
        or name.startswith("readme")
        or low.startswith("docs/")
        or "/docs/" in low
    )
