"""Python language profile (tree-sitter, manual AST walk for version-robustness)."""

from __future__ import annotations

import tree_sitter_python as tspython

from ._ts import make_parser, node_text
from .base import FileParse, LanguageProfile, PEdge, PSymbol


def _module_name(relpath: str) -> str:
    p = relpath[:-3] if relpath.endswith(".py") else relpath
    p = p.replace("\\", "/")
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    return p.strip("/").replace("/", ".")


class PythonProfile(LanguageProfile):
    name = "python"
    extensions = (".py",)

    def __init__(self) -> None:
        self._parser = make_parser(tspython.language())

    def parse(self, source: bytes, relpath: str) -> FileParse:
        fp = FileParse(language=self.name, module=_module_name(relpath))
        try:
            tree = self._parser.parse(source)
            self._visit(tree.root_node, source, fp, [], None)
        except Exception:
            fp.parse_error = True
        return fp

    def _visit(self, node, src, fp, class_stack, cur_func):
        t = node.type
        if t == "decorated_definition":
            inner = node.child_by_field_name("definition")
            if inner is None and node.named_children:
                inner = node.named_children[-1]
            if inner is not None:
                self._visit(inner, src, fp, class_stack, cur_func)
            return
        if t == "class_definition":
            name = self._name(node, src)
            qual = ".".join(class_stack + [name]) if class_stack else name
            fp.symbols.append(
                PSymbol("class", name, qual, node.start_point[0] + 1, node.end_point[0] + 1)
            )
            supers = node.child_by_field_name("superclasses")
            if supers is not None:
                for ch in supers.named_children:
                    bn = self._base_name(ch, src)
                    if bn:
                        fp.edges.append(PEdge(qual, "extends", bn))
            body = node.child_by_field_name("body")
            if body is not None:
                for c in body.named_children:
                    self._visit(c, src, fp, class_stack + [name], None)
            return
        if t == "function_definition":
            name = self._name(node, src)
            qual = ".".join(class_stack + [name]) if class_stack else name
            kind = "method" if class_stack else "function"
            is_entry = not class_stack and name == "main"
            fp.symbols.append(
                PSymbol(kind, name, qual, node.start_point[0] + 1, node.end_point[0] + 1, is_entry)
            )
            body = node.child_by_field_name("body")
            if body is not None:
                for c in body.named_children:
                    self._visit(c, src, fp, class_stack, qual)
            return
        if t in ("import_statement", "import_from_statement"):
            self._imports(node, src, fp, t == "import_from_statement")
            return
        if t == "call":
            callee = self._call_name(node, src)
            if callee:
                fp.edges.append(PEdge(cur_func or "", "calls", callee))
            for c in node.named_children:
                self._visit(c, src, fp, class_stack, cur_func)
            return
        if t == "if_statement" and not class_stack and cur_func is None and self._is_main(node, src):
            ln = node.start_point[0] + 1
            qual = f"__main__@{ln}"
            fp.symbols.append(
                PSymbol("entry", "__main__", qual, ln, node.end_point[0] + 1, is_entry=True)
            )
            for c in node.named_children:
                self._visit(c, src, fp, class_stack, qual)
            return
        for c in node.named_children:
            self._visit(c, src, fp, class_stack, cur_func)

    def _name(self, node, src) -> str:
        n = node.child_by_field_name("name")
        return node_text(n, src) if n is not None else "?"

    def _base_name(self, node, src):
        if node.type == "identifier":
            return node_text(node, src)
        if node.type == "attribute":
            a = node.child_by_field_name("attribute")
            return node_text(a, src) if a is not None else None
        return None

    def _call_name(self, node, src):
        fn = node.child_by_field_name("function")
        if fn is None:
            return None
        if fn.type == "identifier":
            return node_text(fn, src)
        if fn.type == "attribute":
            a = fn.child_by_field_name("attribute")
            return node_text(a, src) if a is not None else None
        return None

    def _imports(self, node, src, fp, from_import) -> None:
        if from_import:
            mod = node.child_by_field_name("module_name")
            if mod is not None:
                fp.edges.append(PEdge("", "imports", node_text(mod, src)))
            return
        for ch in node.named_children:
            target = ch.child_by_field_name("name") if ch.type == "aliased_import" else ch
            if target is not None and target.type in ("dotted_name", "identifier"):
                fp.edges.append(PEdge("", "imports", node_text(target, src)))

    def _is_main(self, node, src) -> bool:
        cond = node.child_by_field_name("condition")
        if cond is None:
            return False
        txt = node_text(cond, src)
        return "__name__" in txt and "__main__" in txt
