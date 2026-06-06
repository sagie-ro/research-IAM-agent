"""Row types for the persisted index."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileRow:
    id: str
    relpath: str
    language: str
    n_lines: int
    is_doc: bool
    parse_error: bool


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
    meta: dict[str, str]
