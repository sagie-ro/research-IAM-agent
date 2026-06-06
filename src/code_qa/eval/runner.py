"""Run the eval seed: build index, ask via the graph, score retrieval recall.

Recall is a structural proxy (did the findings/answer surface the expected files and
symbols?). LLM-judge + groundedness scoring arrive at Inc 7. Running this needs an LLM
key (it exercises the full router->retriever flow).
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from ..config import Settings
from ..graph import build_graph
from ..index import service
from ..index.service import store_path_for
from ..llm import ModelFactory
from ..retrieval import IndexHandle, build_retrieval
from ..source import RepoSource
from .cases import CASES, EvalCase


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@")) or s.endswith(".git")


def score(findings: dict, expect_files: list[str], expect_symbols: list[str]) -> tuple[float, float]:
    items = findings.get("findings", [])
    files = " ".join(f.get("file", "") for f in items)
    syms = " ".join((f.get("symbol") or "") for f in items)
    blob = f"{files} {syms} {findings.get('summary', '')}".lower()
    fr = _hit_rate(expect_files, files.lower() + " " + blob)
    sr = _hit_rate(expect_symbols, syms.lower() + " " + blob)
    return fr, sr


def _hit_rate(expected: list[str], haystack: str) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for e in expected if e.lower() in haystack)
    return hits / len(expected)


def run(only: str | None = None) -> int:
    console = Console()
    settings = Settings()
    factory = ModelFactory(settings)

    table = Table(title="eval — retrieval recall (seed)")
    table.add_column("case")
    table.add_column("type")
    table.add_column("file recall", justify="right")
    table.add_column("symbol recall", justify="right")
    table.add_column("# findings", justify="right")

    cases = [c for c in CASES if not only or only in c.id]
    for case in cases:
        findings = _ask(case, settings, factory)
        fr, sr = score(findings, case.expect_files, case.expect_symbols)
        table.add_row(case.id, case.qtype, f"{fr:.0%}", f"{sr:.0%}", str(len(findings.get("findings", []))))
    console.print(table)
    return 0


def _ask(case: EvalCase, settings: Settings, factory: ModelFactory) -> dict:
    source = RepoSource.from_git(case.repo) if _looks_like_url(case.repo) else RepoSource.from_local(case.repo)
    path, _ = service.ensure_index(source)
    retrieval = build_retrieval(IndexHandle(repo_root=source.path, store_path=path))
    app = build_graph(settings, factory, retrieval)
    result = app.invoke({"question": case.question, "trace": []})
    return result.get("findings") or {"findings": [], "summary": result.get("answer", "")}
