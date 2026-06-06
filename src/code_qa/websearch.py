"""Budgeted web search for the researcher (Inc 5).

An optional, pluggable backend that lets the researcher pull in EXTERNAL background — standards,
library docs, domain knowledge — when the repo and its docs aren't enough. Off by default; the
only backend wired is Tavily, called over stdlib urllib (no extra dependency) so it's available
when a TAVILY_API_KEY is set and the network policy allows it. `build_web_search` returns None
when unconfigured, and the researcher budgets the number of calls per question. External knowledge
never overrides the repo's actual code (it's cited as web).
"""

from __future__ import annotations

import json
import urllib.request

from .config import Settings

_TAVILY_URL = "https://api.tavily.com/search"


def build_web_search(settings: Settings):
    """Return a `search(query) -> str` callable, or None when web search isn't configured."""
    provider = (settings.web_search_provider or "none").lower()
    if provider in ("none", ""):
        return None
    if provider == "tavily":
        key = settings.tavily_api_key
        if not key:
            return None
        k = settings.web_search_results

        def search(query: str) -> str:
            return _tavily(query, key, k)

        return search
    return None


def _tavily(query: str, api_key: str, k: int) -> str:
    payload = json.dumps(
        {"api_key": api_key, "query": query, "max_results": k, "search_depth": "basic", "include_answer": True}
    ).encode()
    req = urllib.request.Request(_TAVILY_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return f"web search error: {exc}"

    results = (data.get("results") or [])[:k]
    if not results:
        return f"no web results for '{query}'"
    out = [f"web results for '{query}' (external background — cite as web; never overrides repo code):"]
    if data.get("answer"):
        out.append(f"  summary: {data['answer'][:400]}")
    for r in results:
        snippet = " ".join((r.get("content") or "").split())[:300]
        out.append(f"  - {r.get('title', '')} ({r.get('url', '')})\n    {snippet}")
    return "\n".join(out)
