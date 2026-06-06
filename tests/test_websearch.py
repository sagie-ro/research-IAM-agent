"""Budgeted web search: provider gating, result formatting (stubbed), and per-trace budget."""

from __future__ import annotations

import json
import types

from code_qa import websearch
from code_qa.config import Settings
from code_qa.retrieval.researcher import TraceReport, run_researcher
from code_qa.retrieval.retriever import Findings


class _Resp:
    """Minimal stand-in for an urlopen context manager returning a JSON body."""

    def __init__(self, payload):
        self._p = payload

    def read(self):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_build_web_search_gated_by_config():
    assert websearch.build_web_search(Settings(web_search_provider="none")) is None
    # default is keyless DuckDuckGo -> callable with no key/config
    assert callable(websearch.build_web_search(Settings()))
    assert callable(websearch.build_web_search(Settings(web_search_provider="duckduckgo")))
    # tavily still needs a key
    assert websearch.build_web_search(Settings(web_search_provider="tavily", tavily_api_key=None)) is None
    assert callable(websearch.build_web_search(Settings(web_search_provider="tavily", tavily_api_key="k")))


def test_duckduckgo_formats_results(monkeypatch):
    payload = {
        "Heading": "RFC 3161",
        "AbstractText": "Time-Stamp Protocol over HTTP.",
        "AbstractSource": "Wikipedia",
        "AbstractURL": "https://en.wikipedia.org/wiki/Time_stamp_protocol",
        "RelatedTopics": [{"Text": "Timestamping authority", "FirstURL": "https://example/tsa"}],
    }
    monkeypatch.setattr(websearch.urllib.request, "urlopen", lambda req, timeout=20: _Resp(payload))
    out = websearch._duckduckgo("rfc 3161", 5)
    assert "RFC 3161" in out and "Time-Stamp Protocol" in out
    assert "example/tsa" in out and "never overrides repo code" in out


def test_duckduckgo_empty_and_errors(monkeypatch):
    monkeypatch.setattr(websearch.urllib.request, "urlopen", lambda req, timeout=20: _Resp({}))
    assert "no web results" in websearch._duckduckgo("asdfqwer", 5)

    def boom(req, timeout=20):
        raise OSError("network blocked")

    monkeypatch.setattr(websearch.urllib.request, "urlopen", boom)
    assert "web search error" in websearch._duckduckgo("q", 5)


def test_tavily_formats_results(monkeypatch):
    payload = {"answer": "Use RFC 3161.", "results": [
        {"title": "RFC 3161", "url": "https://example/rfc", "content": "timestamping protocol"},
    ]}
    monkeypatch.setattr(websearch.urllib.request, "urlopen", lambda req, timeout=20: _Resp(payload))
    out = websearch._tavily("timestamping", "key", 5)
    assert "RFC 3161" in out and "https://example/rfc" in out and "never overrides repo code" in out


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
