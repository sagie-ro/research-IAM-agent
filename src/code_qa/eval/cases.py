"""Seed evaluation cases. Repo-agnostic shape; expand at Inc 7 (PLAN.md section 9)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    repo: str  # local path or git URL
    question: str
    expect_files: list[str] = field(default_factory=list)
    expect_symbols: list[str] = field(default_factory=list)
    qtype: str = "locate"


CASES: list[EvalCase] = [
    EvalCase(
        id="signify-verify",
        repo="https://github.com/ralphje/signify",
        question="Where is Authenticode signature verification implemented?",
        expect_files=["signed_data.py", "signer_info.py"],
        expect_symbols=["verify"],
    ),
    EvalCase(
        id="signify-can-sign",
        repo="https://github.com/ralphje/signify",
        question="Can this library create/sign Authenticode signatures, or only verify them?",
        expect_files=["authenticode"],
        expect_symbols=["verify"],
        qtype="boundary",
    ),
    EvalCase(
        id="jsign-cli",
        repo="https://github.com/ebourg/jsign",
        question="Where is the command-line entry point and how does signing start?",
        expect_files=["JsignCLI.java", "SignerHelper.java"],
        expect_symbols=["main"],
    ),
]
