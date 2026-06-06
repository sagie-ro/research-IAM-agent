"""Eval cases (repo-agnostic shape). Retrieval recall uses expect_files/expect_symbols;
the LLM-judge uses `rubric`; boundary/negative cases use must_include / must_not_include.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalCase:
    id: str
    repo: str  # local path or git URL
    question: str
    expect_files: list[str] = field(default_factory=list)
    expect_symbols: list[str] = field(default_factory=list)
    rubric: str = ""  # what a correct answer must satisfy (for the LLM-judge)
    must_include: list[str] = field(default_factory=list)  # substrings the answer must contain
    must_not_include: list[str] = field(default_factory=list)  # substrings it must NOT contain
    qtype: str = "locate"


CASES: list[EvalCase] = [
    EvalCase(
        id="signify-verify",
        repo="https://github.com/ralphje/signify",
        question="Where is Authenticode signature verification implemented?",
        expect_files=["signed_data.py", "signer_info.py"],
        expect_symbols=["verify"],
        rubric="Identifies that signature verification exists and points to the verification "
               "methods (e.g. AuthenticodeFile.verify / AuthenticodeSignature.verify / SignedData.verify / "
               "SignerInfo.verify) with file locations.",
    ),
    EvalCase(
        id="signify-can-sign",
        repo="https://github.com/ralphje/signify",
        question="Can this library create/sign Authenticode signatures, or only verify them?",
        expect_files=["authenticode"],
        expect_symbols=["verify"],
        rubric="States that signify VERIFIES/INSPECTS Authenticode signatures and CANNOT create/sign "
               "them (verify-only). A wrong answer claims it can sign.",
        must_not_include=["can create authenticode signatures", "able to sign authenticode"],
        qtype="boundary",
    ),
    EvalCase(
        id="jsign-cli",
        repo="https://github.com/ebourg/jsign",
        question="Where is the command-line entry point and how does signing start?",
        expect_files=["JsignCLI.java", "SignerHelper.java"],
        expect_symbols=["main"],
        rubric="Points to JsignCLI.main as the CLI entry and shows signing is driven through "
               "SignerHelper, with file locations.",
    ),
    EvalCase(
        id="signify-summary",
        repo="https://github.com/ralphje/signify",
        question="What does this application do?",
        expect_symbols=["authenticode", "verif"],
        rubric="Explains signify verifies/inspects Windows Authenticode signatures (PE/MSI/catalog) "
               "off-Windows; notes it is verify-only; names key modules.",
        qtype="summarize",
    ),
    EvalCase(
        id="jsign-summary",
        repo="https://github.com/ebourg/jsign",
        question="What does this project do, at a high level?",
        expect_symbols=["sign", "authenticode"],
        rubric="Explains jsign signs (and verifies) Authenticode for multiple formats via CLI/Maven/"
               "Gradle/Ant; mentions key-store/HSM/cloud backends.",
        qtype="summarize",
    ),
    EvalCase(
        id="jsign-signing-flow",
        repo="https://github.com/ebourg/jsign",
        question="What is the flow (classes and function calls) of executable signing, "
                 "starting from the command-line entry point?",
        expect_files=["JsignCLI", "SignerHelper", "AuthenticodeSigner"],
        expect_symbols=["sign"],
        rubric="Traces CLI (JsignCLI) -> SignerHelper -> AuthenticodeSigner producing the signature, "
               "and notes the BouncyCastle boundary (CMS/crypto is third-party).",
        qtype="trace",
    ),
    EvalCase(
        id="signify-verify-flow",
        repo="https://github.com/ralphje/signify",
        question="Trace the flow of signature verification from the entry point through the layers.",
        expect_files=["base.py", "signed_data.py", "context.py"],
        expect_symbols=["verify"],
        rubric="Traces AuthenticodeFile.verify -> AuthenticodeSignature.verify -> SignedData.verify -> "
               "SignerInfo.verify -> VerificationContext.verify, and notes the oscrypto/certvalidator "
               "boundary (crypto is third-party).",
        qtype="trace",
    ),
]
