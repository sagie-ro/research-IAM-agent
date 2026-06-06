"""Java language profile (tree-sitter, manual AST walk)."""

from __future__ import annotations

import tree_sitter_java as tsjava

from ._ts import make_parser, node_text
from .base import FileParse, LanguageProfile, PEdge, PSymbol

_TYPE_DECLS = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
}


class JavaProfile(LanguageProfile):
    name = "java"
    extensions = (".java",)

    def __init__(self) -> None:
        self._parser = make_parser(tsjava.language())

    def parse(self, source: bytes, relpath: str) -> FileParse:
        fp = FileParse(language=self.name)
        try:
            tree = self._parser.parse(source)
            fp.module = self._package(tree.root_node, source)
            self._visit(tree.root_node, source, fp, [], None)
        except Exception:
            fp.parse_error = True
        return fp

    def _package(self, root, src):
        for c in root.named_children:
            if c.type == "package_declaration" and c.named_children:
                return node_text(c.named_children[-1], src)
        return None

    def _visit(self, node, src, fp, type_stack, cur_method):
        t = node.type
        if t in _TYPE_DECLS:
            name = self._name(node, src)
            qual = ".".join(type_stack + [name]) if type_stack else name
            fp.symbols.append(
                PSymbol(_TYPE_DECLS[t], name, qual, node.start_point[0] + 1, node.end_point[0] + 1)
            )
            sc = node.child_by_field_name("superclass")
            if sc is not None:
                for bn in self._type_names(sc, src):
                    fp.edges.append(PEdge(qual, "extends", bn))
            intf = node.child_by_field_name("interfaces")
            if intf is not None:
                for bn in self._type_names(intf, src):
                    fp.edges.append(PEdge(qual, "implements", bn))
            body = node.child_by_field_name("body")
            if body is not None:
                for c in body.named_children:
                    self._visit(c, src, fp, type_stack + [name], None)
            return
        if t in ("method_declaration", "constructor_declaration"):
            name = self._name(node, src)
            qual = ".".join(type_stack + [name]) if type_stack else name
            is_entry = t == "method_declaration" and name == "main" and self._has_static(node, src)
            kind = "method" if t == "method_declaration" else "constructor"
            fp.symbols.append(
                PSymbol(kind, name, qual, node.start_point[0] + 1, node.end_point[0] + 1, is_entry)
            )
            body = node.child_by_field_name("body")
            if body is not None:
                for c in body.named_children:
                    self._visit(c, src, fp, type_stack, qual)
            return
        if t == "import_declaration":
            names = [n for n in node.named_children if n.type in ("scoped_identifier", "identifier")]
            if names:
                fp.edges.append(PEdge("", "imports", node_text(names[-1], src)))
            return
        if t == "method_invocation":
            n = node.child_by_field_name("name")
            if n is not None:
                fp.edges.append(PEdge(cur_method or "", "calls", node_text(n, src)))
            for c in node.named_children:
                self._visit(c, src, fp, type_stack, cur_method)
            return
        if t == "object_creation_expression":
            ty = node.child_by_field_name("type")
            if ty is not None:
                for bn in self._type_names(ty, src):
                    fp.edges.append(PEdge(cur_method or "", "calls", bn))
                    break
            for c in node.named_children:
                self._visit(c, src, fp, type_stack, cur_method)
            return
        for c in node.named_children:
            self._visit(c, src, fp, type_stack, cur_method)

    def _name(self, node, src) -> str:
        n = node.child_by_field_name("name")
        return node_text(n, src) if n is not None else "?"

    def _has_static(self, node, src) -> bool:
        for c in node.named_children:
            if c.type == "modifiers" and "static" in node_text(c, src):
                return True
        return False

    def _type_names(self, node, src) -> list[str]:
        out: list[str] = []

        def walk(n):
            if n.type == "type_identifier":
                out.append(node_text(n, src))
            elif n.type == "scoped_type_identifier":
                ids = [x for x in n.named_children if x.type in ("type_identifier", "identifier")]
                if ids:
                    out.append(node_text(ids[-1], src))
            elif n.type == "generic_type":
                for x in n.named_children:
                    if x.type in ("type_identifier", "scoped_type_identifier"):
                        walk(x)
                        break
            else:
                for x in n.named_children:
                    walk(x)

        walk(node)
        seen: set[str] = set()
        result: list[str] = []
        for x in out:
            if x not in seen:
                seen.add(x)
                result.append(x)
        return result
