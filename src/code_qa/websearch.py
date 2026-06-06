"""Budgeted web search for the researcher (Inc 5).

An optional, pluggable backend that lets the researcher pull in EXTERNAL background — standards,
library docs, domain knowledge — when the repo and its docs aren't enough. The default is
**keyless DuckDuckGo** (the official Instant Answer API over stdlib urllib — no dependency, no
key): great for concepts/standards, sparser for general queries. Tavily is an optional keyed
upgrade with richer results. `WEB_SEARCH_PROVIDER=none` disables web egress entirely. The
researcher budgets the number of calls per question, and external knowledge never overrides the
repo's actual code (it's cited as web).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .config import Settings

_TAVILY_URL = "https://api.tavily.com/search"
_DDG_URL = "https://api.duckduckgo.com/"


def build_web_search(settings: Settings):
    """Return a `search(query) -> str` callable, or None when web search is disabled."""
    provider = (settings.web_search_provider or "none").lower()
    if provider in ("none", ""):
        return None
    k = settings.web_search_results
    if provider in ("duckduckgo", "ddg"):
        return lambda query: _duckduckgo(query, k)
    if provider == "tavily":
        key = settings.tavily_api_key
        if not key:
            return None
        return lambda query: _tavily(query, key, k)
    return None


def _duckduckgo(query: str, k: int) -> str:
    """Keyless DuckDuckGo Instant Answer API (concepts/standards/definitions)."""
    params = urllib.parse.urlencode({"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"})
    req = urllib.request.Request(f"{_DDG_URL}?{params}", headers={"User-Agent": "code-qa"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        return f"web search error: {exc}"

    lines: list[str] = []
    abstract = data.get("AbstractText") or data.get("Abstract") or ""
    if abstract:
        head = data.get("Heading") or query
        tail = " ".join(x for x in (data.get("AbstractSource"), data.get("AbstractURL")) if x)
        lines.append(f"  {head}: {abstract[:400]}" + (f" [{tail}]" if tail else ""))
    if data.get("Definition"):
        lines.append(f"  definition: {data['Definition'][:300]} {data.get('DefinitionURL', '')}".rstrip())
    if data.get("Answer"):
        lines.append(f"  answer: {str(data['Answer'])[:200]}")
    related = []
    for topic in data.get("RelatedTopics", []):
        if isinstance(topic, dict) and topic.get("Text") and topic.get("FirstURL"):
            related.append(topic)
        elif isinstance(topic, dict):  # a grouped section: {"Name":..., "Topics":[...]}
            related.extend(s for s in topic.get("Topics", []) if s.get("Text") and s.get("FirstURL"))
    for t in related[:k]:
        lines.append(f"  - {t['Text'][:200]} ({t['FirstURL']})")

    if not lines:
        return (f"no web results for '{query}' (DuckDuckGo instant-answer covers concepts/standards; "
                "rephrase toward a definition, or rely on the repo + docs)")
    return f"web results for '{query}' (external background — cite as web; never overrides repo code):\n" + "\n".join(lines)


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
