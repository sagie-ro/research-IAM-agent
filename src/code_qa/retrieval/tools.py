"""Wrap Toolbox methods as LangChain tools for the retriever agent.

Descriptions are prescriptive about *when* to call each tool — recent models reach
for tools more deliberately, so the trigger condition belongs in the description.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from .toolbox import Toolbox

_DESCRIPTIONS = {
    "repo_overview": "Get a high-level overview of the repository (languages, entry points, README head). Call this first when you need orientation.",
    "get_symbol": "Find where a class/method/function is DEFINED, by name or qualified name. Use to locate a definition.",
    "find_callers": "List call sites that invoke a given symbol. Use to find who uses something.",
    "find_callees": "List symbols a given symbol calls. Use to step forward through a flow.",
    "get_references": "Find all usage sites of a name across the repo. Use for 'where is X used'.",
    "find_implementations": "Find classes that extend/implement a given type. Use for interfaces/abstract bases.",
    "get_call_path": "Show the precomputed call tree from an entry point (e.g. a CLI main). Use for 'what is the flow of X'.",
    "read_file": "Read a slice of a file with line numbers. Use to confirm a finding before citing it.",
    "search_lexical": "Regex/keyword search across source files. Use when you don't have a symbol name yet (e.g. 'auth', 'password').",
}


def make_tools(toolbox: Toolbox) -> list:
    methods = {
        "repo_overview": toolbox.repo_overview,
        "get_symbol": toolbox.get_symbol,
        "find_callers": toolbox.find_callers,
        "find_callees": toolbox.find_callees,
        "get_references": toolbox.get_references,
        "find_implementations": toolbox.find_implementations,
        "get_call_path": toolbox.get_call_path,
        "read_file": toolbox.read_file,
        "search_lexical": toolbox.search_lexical,
    }
    return [
        StructuredTool.from_function(fn, name=name, description=_DESCRIPTIONS[name])
        for name, fn in methods.items()
    ]
