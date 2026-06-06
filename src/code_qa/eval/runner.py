"""Eval runner: build index, answer via the graph, score each case.

Metrics:
- recall      : did the surfaced evidence (findings/report/answer) include the expected
                files and symbols? (deterministic)
- groundedness: fraction of cited `file:line` locations that point to real indexed files
                (deterministic — catches hallucinated citations)
- judge       : 1-5 rubric-based answer quality from an LLM judge (researcher tier)
- boundary    : pass/fail must_include / must_not_include checks (negative cases)

Running this needs an LLM key (it exercises the full router -> worker flow + the judge).
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from ..config import Settings
from ..graph import build_graph
from ..index import service
from ..llm import ModelFactory
from ..retrieval import IndexHandle, build_retrieval
from ..source import RepoSource
from .cases import CASES, EvalCase

_CITE = re.compile(r"([\w./\-]+\.(?:py|java)):(\d+)")

JUDGE_SYSTEM = """You are a strict evaluator of an AI assistant's answer about a code repository.
Given the question, a rubric of what a correct answer must satisfy, and the answer, rate it 1-5:
5 = fully correct, complete, and grounded in real code; 3 = partially correct or missing key parts;
1 = wrong, vague, or hallucinated. Penalize invented files/classes/behavior heavily.
Return a score and a one-sentence justification."""


class _Judge(BaseModel):
    score: int = Field(ge=1, le=5)
    justification: str = ""


@dataclass
class CaseResult:
    id: str
    qtype: str
    recall_files: float
    recall_symbols: float
    groundedness: float | None
    judge: int | None
    boundary_ok: bool | None
    judge_note: str = ""
    error: str = ""


def _looks_like_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "git@")) or s.endswith(".git")


# --- deterministic metrics (pure, unit-tested) -------------------------------------

def _evidence(result: dict) -> tuple[str, str]:
    """Return (files_blob, text_blob) lower-cased."""
    files = []
    texts = [result.get("answer", "")]
    for f in (result.get("findings") or {}).get("findings", []):
        files.append(f.get("file", ""))
        texts.append(f"{f.get('symbol', '')} {f.get('note', '')}")
    report = result.get("report") or {}
    texts.append(report.get("summary", ""))
    for st in report.get("steps", []):
        files.append(st.get("location", ""))
        texts.append(f"{st.get('symbol', '')} {' '.join(st.get('calls', []))}")
    texts.extend(report.get("boundary_notes", []))
    return " ".join(files).lower(), " ".join(t for t in texts if t).lower()


def _hit_rate(expected: list[str], haystack: str) -> float:
    if not expected:
        return 1.0
    return sum(1 for e in expected if e.lower() in haystack) / len(expected)


def recall(result: dict, case: EvalCase) -> tuple[float, float]:
    files_blob, text_blob = _evidence(result)
    return (
        _hit_rate(case.expect_files, files_blob + " " + text_blob),
        _hit_rate(case.expect_symbols, text_blob),
    )


def _indexed_files(handle: IndexHandle) -> set[str]:
    con = sqlite3.connect(handle.store_path)
    try:
        return {r[0] for r in con.execute("SELECT relpath FROM files")}
    finally:
        con.close()


def groundedness(result: dict, handle: IndexHandle) -> float | None:
    files = _indexed_files(handle)
    cites: list[str] = [m[0] for m in _CITE.findall(result.get("answer", ""))]
    for f in (result.get("findings") or {}).get("findings", []):
        if f.get("file"):
            cites.append(f["file"])
    for st in (result.get("report") or {}).get("steps", []):
        loc = st.get("location", "")
        if ":" in loc:
            cites.append(loc.rsplit(":", 1)[0])
        elif loc:
            cites.append(loc)
    if not cites:
        return None
    grounded = sum(1 for p in cites if _is_grounded(p.strip(), files))
    return grounded / len(cites)


def _is_grounded(path: str, files: set[str]) -> bool:
    return any(rel == path or rel.endswith("/" + path) or rel.endswith(path) for rel in files)


def boundary(answer: str, case: EvalCase) -> bool | None:
    if not case.must_include and not case.must_not_include:
        return None
    a = answer.lower()
    return all(t.lower() in a for t in case.must_include) and not any(
        t.lower() in a for t in case.must_not_include
    )


# --- LLM judge + driver ------------------------------------------------------------

def _judge(model, case: EvalCase, answer: str):
    if not case.rubric or not answer:
        return None, ""
    try:
        verdict = model.with_structured_output(_Judge).invoke([
            SystemMessage(content=JUDGE_SYSTEM),
            HumanMessage(content=f"Question: {case.question}\n\nRubric:\n{case.rubric}\n\nAnswer:\n{answer}"),
        ])
        return verdict.score, verdict.justification
    except Exception as exc:
        return None, f"judge error: {exc}"


def _ask(case: EvalCase, settings: Settings, factory: ModelFactory) -> tuple[dict, IndexHandle]:
    source = RepoSource.from_git(case.repo) if _looks_like_url(case.repo) else RepoSource.from_local(case.repo)
    path, _ = service.ensure_index(source)
    handle = IndexHandle(repo_root=source.path, store_path=path)
    app = build_graph(settings, factory, build_retrieval(handle))
    result = app.invoke({"question": case.question, "history": [], "trace": []})
    return result, handle


def run(only: str | None = None, save: str | None = "eval_results.json") -> int:
    console = Console()
    settings = Settings()
    factory = ModelFactory(settings)
    judge_model = factory.get("researcher")  # judge with the strongest tier

    results: list[CaseResult] = []
    for case in [c for c in CASES if not only or only in c.id]:
        console.print(f"[dim]running {case.id} ({case.qtype}) …[/]")
        try:
            result, handle = _ask(case, settings, factory)
            rf, rs = recall(result, case)
            g = groundedness(result, handle)
            score, note = _judge(judge_model, case, result.get("answer", ""))
            results.append(CaseResult(case.id, case.qtype, rf, rs, g, score,
                                      boundary(result.get("answer", ""), case), note))
        except Exception as exc:
            results.append(CaseResult(case.id, case.qtype, 0.0, 0.0, None, None, None, error=str(exc)))

    _render(console, results)
    if save:
        Path(save).write_text(json.dumps({"cases": [asdict(r) for r in results],
                                          "averages": _averages(results)}, indent=2))
        console.print(f"[dim]saved -> {save}[/]")
    return 0


def _averages(results: list[CaseResult]) -> dict:
    def mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    bounds = [r.boundary_ok for r in results if r.boundary_ok is not None]
    return {
        "recall_files": mean([r.recall_files for r in results]),
        "recall_symbols": mean([r.recall_symbols for r in results]),
        "groundedness": mean([r.groundedness for r in results]),
        "judge": mean([r.judge for r in results]),
        "boundary_pass_rate": round(sum(bounds) / len(bounds), 3) if bounds else None,
    }


def _render(console: Console, results: list[CaseResult]) -> None:
    table = Table(title="eval — metrics")
    for col in ("case", "type", "recall-f", "recall-s", "grounded", "judge", "boundary"):
        table.add_column(col, justify="left" if col in ("case", "type") else "right")
    for r in results:
        if r.error:
            table.add_row(r.id, r.qtype, "[red]error[/]", "", "", "", r.error[:30])
            continue
        table.add_row(
            r.id, r.qtype, f"{r.recall_files:.0%}", f"{r.recall_symbols:.0%}",
            "-" if r.groundedness is None else f"{r.groundedness:.0%}",
            "-" if r.judge is None else f"{r.judge}/5",
            "-" if r.boundary_ok is None else ("pass" if r.boundary_ok else "[red]FAIL[/]"),
        )
    console.print(table)
    avg = _averages(results)
    console.print(
        f"[bold]averages[/] — recall(f/s): {_pct(avg['recall_files'])}/{_pct(avg['recall_symbols'])}  "
        f"grounded: {_pct(avg['groundedness'])}  judge: {avg['judge'] or '-'}/5  "
        f"boundary: {_pct(avg['boundary_pass_rate'])}"
    )


def _pct(v) -> str:
    return "-" if v is None else f"{v:.0%}"


# Back-compat: simple findings-only recall used by older tests/integrations.
def score(findings: dict, expect_files: list[str], expect_symbols: list[str]) -> tuple[float, float]:
    return recall({"findings": findings}, EvalCase("_", "_", "_", expect_files, expect_symbols))
