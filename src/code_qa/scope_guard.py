"""Scope-guard — first-pass, deterministic abuse filter (principle 7).

This is a cheap pre-filter only. The load-bearing defenses also live at the prompt
level (retrieved code is treated as data, never instructions) and, in later
increments, in LLM intent classification. Kept intentionally small and explicit.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|the\s+|any\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+.*(instructions?|rules?|guidelines?)",
    r"(reveal|show|print|repeat|expose|share)\s+.*(system\s+prompt|your\s+instructions?|your\s+prompt)",
    r"what\s+(is|are)\s+your\s+(system\s+prompt|instructions?)",
    r"you\s+are\s+now\s+",
    r"developer\s+mode",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


class ScopeDecision(BaseModel):
    allowed: bool
    reason: str = ""


def deterministic_guard(question: str, max_chars: int) -> ScopeDecision:
    q = question.strip()
    if not q:
        return ScopeDecision(allowed=False, reason="empty question")
    if len(q) > max_chars:
        return ScopeDecision(
            allowed=False, reason=f"question exceeds {max_chars} chars (resource guard)"
        )
    if _INJECTION_RE.search(q):
        return ScopeDecision(
            allowed=False, reason="possible prompt-injection / self-disclosure attempt"
        )
    return ScopeDecision(allowed=True)
