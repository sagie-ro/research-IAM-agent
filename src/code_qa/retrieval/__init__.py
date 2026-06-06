"""Retrieval subsystem: toolbox over the index + a retriever worker."""

from __future__ import annotations

from dataclasses import dataclass

from .researcher import FlowStep, TraceReport, run_researcher
from .retriever import Finding, Findings, run_retriever
from .tools import make_tools
from .toolbox import IndexHandle, Toolbox

__all__ = [
    "Retrieval", "build_retrieval", "IndexHandle", "Toolbox",
    "make_tools", "run_retriever", "Finding", "Findings",
    "run_researcher", "TraceReport", "FlowStep",
]


@dataclass
class Retrieval:
    tools: list
    overview: str
    toolbox: Toolbox


def build_retrieval(handle: IndexHandle, embedder=None, corpus_path=None) -> Retrieval:
    toolbox = Toolbox(handle, embedder=embedder, corpus_path=corpus_path)
    return Retrieval(tools=make_tools(toolbox), overview=toolbox.repo_overview(), toolbox=toolbox)
