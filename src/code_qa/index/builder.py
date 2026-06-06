"""Build the index from a RepoSource: parse files, resolve edges, precompute call-paths.

Resolution is hand-rolled and precision-first (Option A / D2): a call/extends/implements
edge is linked only when its simple target name resolves unambiguously (one candidate, or
one same-file candidate). Ambiguous targets are kept as names with no link, so we accrue
false negatives rather than false edges. The agentic layer bridges the gaps later.
"""

from __future__ import annotations

import sys
from collections import defaultdict, deque
from pathlib import Path

from ..languages import profile_for
from ..source import RepoSource
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

    for path in source.list_files():
        rel = str(path.relative_to(root)).replace("\\", "/")
        doc = _is_doc(rel)
        profile = profile_for(rel)
        if profile is None:
            if doc:
                files.append(FileRow(rel, rel, "doc", _count_lines(path), True, False))
            continue
        try:
            data = path.read_bytes()
        except Exception:
            continue
        parsed = profile.parse(data, rel)
        files.append(FileRow(rel, rel, parsed.language, data.count(b"\n") + 1, doc, parsed.parse_error))
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

    sym_ids = {s.id for s in symbols}

    # parent links from qualname nesting
    for s in symbols:
        if "." in s.qualname:
            pid = f"{s.file_id}::{s.qualname.rsplit('.', 1)[0]}"
            s.parent_id = pid if pid in sym_ids else s.file_id
        else:
            s.parent_id = s.file_id

    # resolution + call adjacency
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

    # precomputed call-paths (bounded BFS tree from each entry)
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
        "schema_version": "1",
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
