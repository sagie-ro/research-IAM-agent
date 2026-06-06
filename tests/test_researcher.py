from code_qa.retrieval.researcher import FlowStep, TraceReport, _fan_out
from code_qa.retrieval.retriever import Finding, Findings


def test_fan_out_runs_in_parallel_and_attributes_workers():
    def fake_retriever(subquestion, agent, events):
        events.append({"agent": agent, "event": "tool_call", "name": "get_symbol"})
        return Findings(summary=f"answer for {subquestion}",
                        findings=[Finding(file="x.py", line_start=1, symbol="s", note="n")])

    trace: list = []
    out = _fan_out(["where is A", "where is B"], fake_retriever, trace, start_index=1, max_parallel=3)

    assert "where is A" in out and "where is B" in out
    agents = {e["agent"] for e in trace}
    assert "retriever#1" in agents and "retriever#2" in agents  # distinct workers
    assert any(e["event"] == "sub_findings" for e in trace)


def test_fan_out_caps_parallelism():
    def fake(subq, agent, events):
        return Findings(summary="", findings=[])

    trace: list = []
    _fan_out(["a", "b", "c", "d", "e"], fake, trace, start_index=1, max_parallel=2)
    workers = {e["worker"] for e in trace if e["event"] == "sub_findings"}
    assert len(workers) == 2  # capped


def test_trace_report_schema():
    report = TraceReport(
        summary="signing flow",
        steps=[FlowStep(order=1, symbol="JsignCLI.main", location="JsignCLI.java:54", calls=["execute"])],
        boundary_notes=["leaves into BouncyCastle for CMS"],
    )
    assert report.steps[0].symbol == "JsignCLI.main"
    assert report.boundary_notes
