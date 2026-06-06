"""tree-sitter helpers shared by language profiles."""

from __future__ import annotations

from tree_sitter import Language, Parser


def make_parser(language_capsule) -> Parser:
    """Build a Parser for a grammar capsule, tolerant of tree-sitter API versions."""
    lang = Language(language_capsule)
    try:
        return Parser(lang)  # tree-sitter >= 0.22
    except TypeError:
        parser = Parser()
        try:
            parser.language = lang
        except Exception:  # pragma: no cover - very old API
            parser.set_language(lang)
        return parser


def node_text(node, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")
