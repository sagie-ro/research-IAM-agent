"""Row types for the persisted index."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileRow:
    id: str
    relpath: str
    language: str  # python | java | doc | binary | other
    n_lines: int
    is_doc: bool
    parse_error: bool
    on_disk: bool = True
    content_hash: str = ""  # sha1 of bytes for materialized source/doc; "" for inventory-only (delta key)


@dataclass
class DocChunkRow:
    """A heading-delimited section of a documentation file — the unit of doc RAG."""

    file_id: str
    heading: str
    start_line: int
    end_line: int
    source: str  # 'repo' (the repo's own docs) | 'corpus' (external, future)
    text: str


@dataclass
class SymbolRow:
    id: str
    file_id: str
    kind: str
    name: str
    qualname: str
    parent_id: str | None
    start_line: int
    end_line: int
    is_entry: bool


@dataclass
class EdgeRow:
    src_id: str
    type: str
    dst_id: str | None
    dst_name: str


@dataclass
class CallPathRow:
    entry_id: str
    from_id: str
    to_id: str
    depth: int


@dataclass
class Index:
    repo_path: str
    sha: str | None
    files: list[FileRow]
    symbols: list[SymbolRow]
    edges: list[EdgeRow]
    call_paths: list[CallPathRow]
    doc_chunks: list[DocChunkRow]
    meta: dict[str, str]
