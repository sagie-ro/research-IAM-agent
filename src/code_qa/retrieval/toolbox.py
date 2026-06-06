"""Toolbox — read-only queries over the structural index + lexical search.

Each public method returns a compact, citation-friendly string (file:line) suitable
both for an LLM tool observation and for a human. Everything here is deterministic
and key-free; the retriever agent (retriever.py) drives these tools.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..embeddings import cosine
from ..index.store import unpack_vector

_README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")
_SRC_GLOBS = ("*.py", "*.java")


@dataclass
class IndexHandle:
    repo_root: Path
    store_path: Path


def _hybrid_rank(rows, query, vectors, embedder, limit):
    """Rank doc/corpus chunks by normalized semantic (cosine) ⊕ keyword overlap. Returns
    (top_rows, mode) where mode is 'semantic+keyword' or 'keyword'. Pure + store-agnostic."""
    terms = {t for t in re.findall(r"\w+", query.lower()) if len(t) > 2}
    keyword = {
        r["id"]: sum((r["text"] or "").lower().count(t) for t in terms)
        + 3 * sum(1 for t in terms if t in (r["heading"] or "").lower())
        for r in rows
    }
    semantic: dict[int, float] = {}
    if vectors and embedder is not None:
        try:
            qv = embedder.embed_query(query)
            semantic = {r["id"]: max(0.0, cosine(qv, vectors[r["id"]])) for r in rows if r["id"] in vectors}
        except Exception:
            semantic = {}

    def _norm(scores):
        top = max(scores.values(), default=0.0) or 1.0
        return {k: v / top for k, v in scores.items()}

    nk, ns = _norm(keyword), _norm(semantic)
    combined = {r["id"]: nk.get(r["id"], 0.0) + ns.get(r["id"], 0.0) for r in rows}
    ranked = sorted(rows, key=lambda r: combined[r["id"]], reverse=True)
    top = [r for r in ranked if combined[r["id"]] > 0][:limit]
    return top, ("semantic+keyword" if semantic else "keyword")


class Toolbox:
    def __init__(self, handle: IndexHandle, embedder=None, corpus_path=None) -> None:
        self.h = handle
        self._embedder = embedder  # optional; enables semantic doc/corpus search when present
        self._corpus_path = corpus_path  # optional external professional-corpus store

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.h.store_path)
        con.row_factory = sqlite3.Row
        return con

    def _label(self, con: sqlite3.Connection, sid: str) -> str:
        row = con.execute(
            "SELECT qualname, file_id, start_line FROM symbols WHERE id=?", (sid,)
        ).fetchone()
        if row:
            return f"{row['qualname']} ({row['file_id']}:{row['start_line']})"
        return sid  # file-scope source

    def _symbol_ids(self, con: sqlite3.Connection, name: str) -> list[str]:
        return [r["id"] for r in con.execute(
            "SELECT id FROM symbols WHERE name=? OR qualname=?", (name, name)
        )]

    # --- tools ---

    def repo_overview(self) -> str:
        con = self._con()
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            langs = con.execute(
                "SELECT language, COUNT(*) FROM files GROUP BY language ORDER BY 2 DESC"
            ).fetchall()
            n_sym = con.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            assets = con.execute(
                "SELECT COUNT(*) FROM files WHERE language IN ('binary','other')"
            ).fetchone()[0]
            entries = con.execute(
                "SELECT qualname, file_id FROM symbols WHERE is_entry=1 ORDER BY file_id LIMIT 12"
            ).fetchall()
        finally:
            con.close()
        out = [
            f"repo: {Path(meta.get('repo_path', '')).name} @ {(meta.get('sha') or 'live')[:8]}",
            "languages: " + ", ".join(f"{lang}:{c}" for lang, c in langs),
            f"symbols: {n_sym}   assets (inventory only, not parsed): {assets}",
            "entry points:",
        ]
        out += [f"  - {r['file_id']} :: {r['qualname']}" for r in entries] or ["  (none detected)"]
        readme = self._read_readme()
        if readme:
            out += ["", "README (head):", readme]
        return "\n".join(out)

    def structure_digest(self, max_modules: int = 14, max_per_module: int = 5) -> str:
        """Structure-first digest of the WHOLE repo for overview/summary questions:
        languages, README head, a module map (per top-level package: source files,
        symbols, key types), and entry points with what they first call."""
        from collections import defaultdict

        con = self._con()
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
            files = con.execute("SELECT relpath, language FROM files").fetchall()
            syms = con.execute(
                "SELECT name, kind, file_id, is_entry, start_line, end_line FROM symbols"
            ).fetchall()
            entries = con.execute(
                "SELECT id, qualname, file_id FROM symbols WHERE is_entry=1 ORDER BY file_id LIMIT 15"
            ).fetchall()
            callees = {}
            for e in entries:
                rows = con.execute(
                    "SELECT s.qualname FROM call_paths cp JOIN symbols s ON s.id=cp.to_id "
                    "WHERE cp.entry_id=? AND cp.depth=1 LIMIT 6",
                    (e["id"],),
                ).fetchall()
                callees[e["id"]] = [r["qualname"] for r in rows]
        finally:
            con.close()

        def top(path: str) -> str:
            i = path.find("/")
            return path[:i] if i > 0 else "(root)"

        src_files: dict[str, int] = defaultdict(int)
        n_syms: dict[str, int] = defaultdict(int)
        classes: dict[str, list] = defaultdict(list)
        n_entry: dict[str, int] = defaultdict(int)
        langs: dict[str, int] = defaultdict(int)
        for f in files:
            langs[f["language"]] += 1
            if f["language"] in ("python", "java"):
                src_files[top(f["relpath"])] += 1
        for s in syms:
            m = top(s["file_id"])
            n_syms[m] += 1
            if s["kind"] in ("class", "interface", "enum", "record"):
                classes[m].append((s["end_line"] - s["start_line"], s["name"]))
            if s["is_entry"]:
                n_entry[m] += 1

        out = [
            f"repo: {Path(meta.get('repo_path', '')).name} @ {(meta.get('sha') or 'live')[:8]}",
            "languages: " + ", ".join(f"{k}:{v}" for k, v in sorted(langs.items(), key=lambda x: -x[1])),
        ]
        readme = self._read_readme()
        if readme:
            out += ["", "README (head):", readme]
        out += ["", "module map (top packages by source files):"]
        for m in sorted(src_files, key=lambda x: -src_files[x])[:max_modules]:
            key_types = [n for _, n in sorted(classes[m], reverse=True)[:max_per_module]]
            note = f"{src_files[m]} src files, {n_syms[m]} symbols"
            if n_entry[m]:
                note += f", {n_entry[m]} entry pt(s)"
            line = f"  {m}/  — {note}"
            if key_types:
                line += "  · key types: " + ", ".join(key_types)
            out.append(line)
        out += ["", "entry points → first calls:"]
        for e in entries[:10]:
            cs = callees.get(e["id"], [])
            out.append(f"  {e['file_id']} :: {e['qualname']}" + (f"  → {', '.join(cs)}" if cs else ""))
        return "\n".join(out)[:6000]

    def get_symbol(self, name: str) -> str:
        """Find symbol definitions (class/method/function) by name or qualified name."""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT kind, qualname, file_id, start_line, end_line FROM symbols "
                "WHERE name=? OR qualname=? ORDER BY (name=?) DESC LIMIT 25",
                (name, name, name),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return f"no symbol named '{name}'"
        return "\n".join(
            f"{r['kind']} {r['qualname']} — {r['file_id']}:{r['start_line']}-{r['end_line']}"
            for r in rows
        )

    def find_callers(self, name: str) -> str:
        """List call sites that invoke the given symbol (resolved calls only)."""
        con = self._con()
        try:
            ids = self._symbol_ids(con, name)
            if not ids:
                return f"no symbol named '{name}'"
            ph = ",".join("?" * len(ids))
            rows = con.execute(
                f"SELECT DISTINCT src_id FROM edges WHERE type='calls' AND dst_id IN ({ph}) LIMIT 40",
                ids,
            ).fetchall()
            labels = [self._label(con, r["src_id"]) for r in rows]
        finally:
            con.close()
        return ("callers of '%s':\n" % name + "\n".join(f"  {x}" for x in labels)) if labels else f"no resolved callers of '{name}'"

    def find_callees(self, name: str) -> str:
        """List symbols called by the given symbol (resolved calls only)."""
        con = self._con()
        try:
            ids = self._symbol_ids(con, name)
            if not ids:
                return f"no symbol named '{name}'"
            ph = ",".join("?" * len(ids))
            rows = con.execute(
                f"SELECT DISTINCT dst_id FROM edges WHERE type='calls' AND src_id IN ({ph}) "
                f"AND dst_id IS NOT NULL LIMIT 40",
                ids,
            ).fetchall()
            labels = [self._label(con, r["dst_id"]) for r in rows]
        finally:
            con.close()
        return ("callees of '%s':\n" % name + "\n".join(f"  {x}" for x in labels)) if labels else f"no resolved callees of '{name}'"

    def get_references(self, name: str) -> str:
        """Find usage sites of a name across the repo (any edge referencing it)."""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT src_id, type, dst_id FROM edges WHERE dst_name=? LIMIT 50", (name,)
            ).fetchall()
            items = [f"  [{r['type']}{'*' if r['dst_id'] else ''}] {self._label(con, r['src_id'])}" for r in rows]
        finally:
            con.close()
        if not items:
            return f"no references to '{name}' in the symbol graph (try search_lexical)"
        return f"references to '{name}' (* = resolved):\n" + "\n".join(items)

    def find_implementations(self, name: str) -> str:
        """Find types that extend/implement the given class or interface name."""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT src_id, type FROM edges WHERE dst_name=? AND type IN ('extends','implements') LIMIT 40",
                (name,),
            ).fetchall()
            items = [f"  [{r['type']}] {self._label(con, r['src_id'])}" for r in rows]
        finally:
            con.close()
        return (f"subtypes of '{name}':\n" + "\n".join(items)) if items else f"no extends/implements of '{name}'"

    def get_call_path(self, name: str) -> str:
        """Show the precomputed call-path (call tree) from an entry point by name."""
        con = self._con()
        try:
            ent = con.execute(
                "SELECT id, qualname FROM symbols WHERE (name=? OR qualname=?) AND is_entry=1 LIMIT 1",
                (name, name),
            ).fetchone()
            if ent is None:
                return f"'{name}' is not a detected entry point. Use find_callees to walk calls."
            rows = con.execute(
                "SELECT to_id, depth FROM call_paths WHERE entry_id=? ORDER BY depth, to_id LIMIT 60",
                (ent["id"],),
            ).fetchall()
            lines = [f"  depth {r['depth']}: {self._label(con, r['to_id'])}" for r in rows]
        finally:
            con.close()
        head = f"call-path from entry {ent['qualname']}:"
        return head + "\n" + ("\n".join(lines) if lines else "  (no outgoing resolved calls)")

    def find_files(self, pattern: str) -> str:
        """List repository files whose path contains a substring, including binary/asset
        files indexed as inventory but not parsed."""
        con = self._con()
        try:
            rows = con.execute(
                "SELECT relpath, language, on_disk FROM files WHERE relpath LIKE ? "
                "ORDER BY relpath LIMIT 60",
                (f"%{pattern}%",),
            ).fetchall()
        finally:
            con.close()
        if not rows:
            return f"no files matching '{pattern}'"
        return f"files matching '{pattern}':\n" + "\n".join(
            f"  {r['relpath']}  [{r['language']}{'' if r['on_disk'] else ', not-downloaded'}]"
            for r in rows
        )

    def read_file(self, path: str, start_line: int = 1, end_line: int = 200) -> str:
        """Read a slice of a repo file with line numbers (read-only)."""
        root = self.h.repo_root.resolve()
        target = (root / path).resolve()
        if not str(target).startswith(str(root)):
            return "refused: path outside the repository"
        if not target.is_file():
            return f"not a file: {path}"
        start = max(1, start_line)
        end = max(start, min(end_line, start + 400))
        out = []
        try:
            with target.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if i < start:
                        continue
                    if i > end:
                        break
                    out.append(f"{i:5d}  {line.rstrip()}")
        except Exception as exc:
            return f"read error: {exc}"
        return f"{path}:{start}-{end}\n" + "\n".join(out)

    def _doc_search(self, con, query: str, header: str, limit: int) -> str | None:
        """Shared hybrid search over a doc_chunks/doc_vectors store (repo index or corpus)."""
        try:
            rows = con.execute(
                "SELECT id, file_id, heading, start_line, end_line, source, text FROM doc_chunks"
            ).fetchall()
            vectors: dict[int, list[float]] = {}
            if self._embedder is not None:
                try:
                    vrows = con.execute(
                        "SELECT chunk_id, vec FROM doc_vectors WHERE model=?", (self._embedder.model,)
                    ).fetchall()
                    vectors = {r["chunk_id"]: unpack_vector(r["vec"]) for r in vrows}
                except sqlite3.OperationalError:
                    vectors = {}
        except sqlite3.OperationalError:
            return None
        if not rows:
            return None
        top, mode = _hybrid_rank(rows, query, vectors, self._embedder, limit)
        if not top:
            return f"no matches for '{query}'"
        out = [header.format(mode=mode)]
        for r in top:
            tag = "doc" if r["source"] == "repo" else r["source"]
            snippet = " ".join((r["text"] or "").split())[:300]
            out.append(f"  [{tag}] {r['file_id']}:{r['start_line']}-{r['end_line']} · {r['heading']}\n    {snippet}")
        return "\n".join(out)

    def search_docs(self, query: str, limit: int = 5) -> str:
        """Search the repository's DOCUMENTATION (README / markdown / docs) for relevant prose.
        Hybrid: semantic (embeddings) when available, blended with keyword overlap; keyword-only
        otherwise. Docs explain intent and design but can drift from the implementation — treat the
        CODE as authoritative when they disagree, and confirm behavioral claims against code."""
        con = self._con()
        try:
            res = self._doc_search(
                con, query,
                "documentation matches ({mode}; intent/design — verify against code; code is authoritative):",
                limit,
            )
        finally:
            con.close()
        return res or "no documentation indexed for this repository"

    def search_corpus(self, query: str, limit: int = 5) -> str:
        """Search the external professional CORPUS the user supplied (standards, design references,
        domain docs). This is GENERAL reference knowledge, NOT specific to this repo — use it to
        bring in standards/best-practices/background. It NEVER overrides the repo's actual code."""
        if not self._corpus_path:
            return "no professional corpus is configured"
        con = sqlite3.connect(self._corpus_path)
        con.row_factory = sqlite3.Row
        try:
            res = self._doc_search(
                con, query,
                "corpus matches ({mode}; external reference, general knowledge — NOT specific to this "
                "repo and never overrides the actual code):",
                limit,
            )
        finally:
            con.close()
        return res or "the professional corpus has no matching reference"

    def search_lexical(self, pattern: str) -> str:
        """Regex/keyword search across source files (ripgrep, with a Python fallback)."""
        root = self.h.repo_root
        rg = shutil.which("rg")
        if rg:
            try:
                proc = subprocess.run(
                    [rg, "--line-number", "--no-heading", "--color", "never",
                     "--max-count", "5", "-e", pattern, str(root)],
                    capture_output=True, text=True, timeout=20,
                )
                lines = proc.stdout.splitlines()[:40]
                rel = [ln.replace(str(root) + "/", "") for ln in lines]
                return ("matches:\n" + "\n".join(rel)) if rel else f"no matches for '{pattern}'"
            except Exception:
                pass
        return self._python_grep(pattern)

    # --- helpers ---

    def _python_grep(self, pattern: str) -> str:
        import re
        try:
            rx = re.compile(pattern)
        except re.error:
            rx = re.compile(re.escape(pattern))
        root = self.h.repo_root
        hits: list[str] = []
        for glob in _SRC_GLOBS:
            for path in root.rglob(glob):
                try:
                    for i, line in enumerate(path.read_text("utf-8", "replace").splitlines(), 1):
                        if rx.search(line):
                            hits.append(f"{path.relative_to(root)}:{i}:{line.strip()[:160]}")
                            if len(hits) >= 40:
                                return "matches:\n" + "\n".join(hits)
                except Exception:
                    continue
        return ("matches:\n" + "\n".join(hits)) if hits else f"no matches for '{pattern}'"

    def _read_readme(self) -> str | None:
        for child in self.h.repo_root.iterdir():
            if child.is_file() and child.name.lower() in _README_NAMES:
                try:
                    text = child.read_text("utf-8", "replace")
                except Exception:
                    return None
                lines = [ln for ln in text.splitlines()][:30]
                return "\n".join(lines)[:1500]
        return None
