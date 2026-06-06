"""Budgeted web search: provider gating, Tavily formatting (stubbed), and per-trace budget."""

from __future__ import annotations

import types

from code_qa.config import Settings
from code_qa import websearch
from code_qa.retrieval.researcher import TraceReport, run_researcher
from code_qa.retrieval.retriever import Findings


def test_build_web_search_gated_by_config():
    assert websearch.build_web_search(Settings(web_search_provider="none")) is None
    assert websearch.build_web_search(Settings(web_search_provider="tavily", tavily_api_key=None)) is None
    fn = websearch.build_web_search(Settings(web_search_provider="tavily", tavily_api_key="k"))
    assert callable(fn)


def test_tavily_formats_results(monkeypatch):
    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            import json
            return json.dumps(self._p).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = {"answer": "Use RFC 3161.", "results": [
        {"title": "RFC 3161", "url": "https://example/rfc", "content": "timestamping protocol"},
    ]}
    monkeypatch.setattr(websearch.urllib.request, "urlopen", lambda req, timeout=20: _Resp(payload))
    out = websearch._tavily("timestamping", "key", 5)
    assert "RFC 3161" in out and "https://example/rfc" in out and "never overrides repo code" in out


def test_tavily_handles_errors(monkeypatch):
    def boom(req, timeout=20):
        raise OSError("network blocked")

    monkeypatch.setattr(websearch.urllib.request, "urlopen", boom)
    assert "web search error" in websearch._tavily("q", "key", 3)


def test_web_search_is_budgeted(make_stub_model):
    calls = {"n": 0}

    def web(query):
        calls["n"] += 1
        return f"result for {query}"

    def researcher_keeps_searching():
        return [{"name": "web_search", "args": {"query": "x"}, "id": f"w{calls['n']}"}]

    researcher = make_stub_model(researcher_keeps_searching, TraceReport(summary="done"))
    retriever = make_stub_model(lambda: [], Findings(summary="", findings=[]))
    retrieval = types.SimpleNamespace(tools=[], overview="ov")
    trace: list = []

    run_researcher(researcher, retriever, retrieval, "q", trace,
                   max_steps=8, web_search=web, web_search_max=2)

    assert calls["n"] == 2  # actual web calls capped at the budget despite 8 attempts
    assert len([e for e in trace if e.get("event") == "web_search"]) == 2
