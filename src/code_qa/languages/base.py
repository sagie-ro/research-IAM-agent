"""Language profile interface + parse-result data structures.

A profile turns one source file into a flat list of symbols and edges, in a
language-neutral shape. Adding a language = adding a profile (PLAN.md section 4).
Edge targets are raw names here; cross-file resolution happens in the indexer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PSymbol:
    kind: str            # class | interface | enum | record | function | method | constructor | entry
    name: str
    qualname: str        # dotted, within-file (e.g. "AuthenticodeFile.verify")
    start_line: int
    end_line: int
    is_entry: bool = False


@dataclass
class PEdge:
    src_qualname: str     # "" == file/module scope
    type: str             # calls | extends | implements | imports
    dst_name: str         # raw (simple) target name


@dataclass
class FileParse:
    language: str
    module: str | None = None
    symbols: list[PSymbol] = field(default_factory=list)
    edges: list[PEdge] = field(default_factory=list)
    parse_error: bool = False


class LanguageProfile:
    name: str = ""
    extensions: tuple[str, ...] = ()

    def parse(self, source: bytes, relpath: str) -> FileParse:  # pragma: no cover - interface
        raise NotImplementedError
