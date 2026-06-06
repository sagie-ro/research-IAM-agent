from code_qa.eval.cases import EvalCase
from code_qa.eval.runner import boundary, groundedness, recall


def test_recall_from_findings():
    result = {"answer": "verify in signed_data.py",
              "findings": {"findings": [{"file": "a/signed_data.py", "symbol": "verify", "line_start": 1}]}}
    case = EvalCase("c", "r", "q", expect_files=["signed_data.py", "missing.py"], expect_symbols=["verify"])
    rf, rs = recall(result, case)
    assert rf == 0.5 and rs == 1.0


def test_recall_from_report_steps():
    result = {"answer": "", "report": {
        "summary": "signing flow",
        "steps": [{"location": "JsignCLI.java:54", "symbol": "main", "calls": ["execute"]}],
        "boundary_notes": ["BouncyCastle"]}}
    case = EvalCase("c", "r", "q", expect_files=["JsignCLI.java"], expect_symbols=["main", "execute"])
    rf, rs = recall(result, case)
    assert rf == 1.0 and rs == 1.0


def test_groundedness_detects_fake_citation(toolbox):
    # one real (pkg/mod.py) + one hallucinated (ghost.py) -> 50% grounded
    assert groundedness({"answer": "see pkg/mod.py:1 and ghost.py:5"}, toolbox.h) == 0.5
    assert groundedness({"answer": "no citations here"}, toolbox.h) is None


def test_boundary_checks():
    case = EvalCase("c", "r", "q", must_include=["verify"], must_not_include=["can sign"])
    assert boundary("it can only verify", case) is True
    assert boundary("it can sign and verify", case) is False
    assert boundary("anything", EvalCase("c", "r", "q")) is None
