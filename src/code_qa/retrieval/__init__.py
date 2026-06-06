"""Retrieval subsystem: toolbox over the index + a retriever worker."""

from __future__ import annotations

from dataclasses import dataclass

from .retriever import Finding, Findings, run_retriever
from .tools import make_tools
from .toolbox import IndexHandle, Toolbox

__all__ = [
    "Retrieval", "build_retrieval", "IndexHandle", "Toolbox",
    "make_tools", "run_retriever", "Finding", "Findings",
]


@dataclass
class Retrieval:
    tools: list
    overview: str
    toolbox: Toolbox


def build_retrieval(handle: IndexHandle) -> Retrieval:
    toolbox = Toolbox(handle)
    return Retrieval(tools=make_tools(toolbox), overview=toolbox.repo_overview(), toolbox=toolbox)
