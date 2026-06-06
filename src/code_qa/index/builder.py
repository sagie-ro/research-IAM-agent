"""Build the index from a RepoSource: inventory every file, parse source/docs,
resolve edges, precompute call-paths.

Inventory covers the FULL tree (via RepoSource.tracked_paths) so binary/asset files
are recorded as metadata (path + type), even when their bytes were never downloaded.
Only source/doc files that are materialized on disk are read and parsed.

Resolution is hand-rolled and precision-first (Option A / D2): a call/extends/implements
edge is linked only when its simple target name resolves unambiguously. Ambiguous
targets stay unlinked (false negatives, not false edges); the agentic layer bridges them.
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from pathlib import Path

from ..languages import profile_for
from ..source import BINARY_EXT, RepoSource
from . import store
from .model import CallPathRow, EdgeRow, FileRow, Index, SymbolRow

_DOC_SUFFIX = {".md", ".rst", ".txt", ".adoc"}
_NAME_INDEXED = {"function", "method", "class", "interface", "enum", "record", "constructor"}
_MAX_DEPTH = 8
_MAX_NODES = 200


def build(source: RepoSource) -> Index:
    sys.setrecursionlimit(20000)
    root = source.path

    files: list[FileRow] = []
    symbols: list[SymbolRow] = []
    raw_edges: list[tuple[str, str, str]] = []
    by_name: dict[str, list[str]] = defaultdict(list)
    parse_errors = 0

    for rel in source.tracked_paths():
        on_disk = source.materialized(rel)
        profile = profile_for(rel)
        doc = _is_doc(rel)

        if profile is not None and on_disk:
            try:
                data = (root / rel).read_bytes()
            except Exception:
                files.append(FileRow(rel, rel, "other", 0, doc, False, on_disk))
                continue
            parsed = profile.parse(data, rel)
            files.append(FileRow(rel, rel, parsed.language, data.count(b"\n") + 1, doc, parsed.parse_error, True))
            if parsed.parse_error:
                parse_errors += 1
            seen: set[str] = set()
            for ps in parsed.symbols:
                sid = f"{rel}::{ps.qualname}"
                if sid in seen:
                    sid = f"{sid}@{ps.start_line}"
                seen.add(sid)
                symbols.append(
                    SymbolRow(sid, rel, ps.kind, ps.name, ps.qualname, None,
                              ps.start_line, ps.end_line, ps.is_entry)
                )
                if ps.kind in _NAME_INDEXED:
                    by_name[ps.name].append(sid)
            for e in parsed.edges:
                src_id = rel if not e.src_qualname else f"{rel}::{e.src_qualname}"
                raw_edges.append((src_id, e.type, e.dst_name))
        elif doc and on_disk:
            files.append(FileRow(rel, rel, "doc", _count_lines(root / rel), True, False, True))
        else:
            # Inventory-only: binary/asset, or a source/doc file not materialized (sparse).
            language = "binary" if Path(rel).suffix.lower() in BINARY_EXT else ("doc" if doc else "other")
            files.append(FileRow(rel, rel, language, 0, doc, False, on_disk))

    sym_ids = {s.id for s in symbols}

    for s in symbols:
        if "." in s.qualname:
            pid = f"{s.file_id}::{s.qualname.rsplit('.', 1)[0]}"
            s.parent_id = pid if pid in sym_ids else s.file_id
        else:
            s.parent_id = s.file_id

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
        "sha": source.sha or "",
        "schema_version": str(store.SCHEMA_VERSION),
        "parse_errors": str(parse_errors),
        "n_entries": str(len(entries)),
    }
    return Index(str(root), source.sha, files, symbols, edges, call_paths, meta)


def _is_doc(relpath: str) -> bool:
    low = relpath.lower()
    name = Path(low).name
    return (
        Path(low).suffix in _DOC_SUFFIX
        or name.startswith("readme")
        or low.startswith("docs/")
        or "/docs/" in low
    )


def _count_lines(path: Path) -> int:
    try:
        return path.read_bytes().count(b"\n") + 1
    except Exception:
        return 0
