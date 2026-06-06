import types

from code_qa.retrieval.researcher import FlowStep, TraceReport, _fan_out, run_researcher
from code_qa.retrieval.retriever import Finding, Findings


class _AI:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _Model:
    """Stub chat model: scripted tool_calls per turn + a fixed structured output."""

    def __init__(self, tool_calls_fn, structured_obj):
        self._tcf, self._obj = tool_calls_fn, structured_obj

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return _AI(self._tcf())

    def with_structured_output(self, schema):
        return types.SimpleNamespace(invoke=lambda msgs: self._obj)


def test_researcher_enforces_total_retriever_ceiling():
    n = {"i": 0}

    def researcher_keeps_spawning():
        n["i"] += 1
        return [{"name": "spawn_retrievers",
                 "args": {"subquestions": ["a", "b", "c", "d", "e", "f"]},
                 "id": f"c{n['i']}"}]

    researcher = _Model(researcher_keeps_spawning, TraceReport(summary="done"))
    retriever = _Model(lambda: [], Findings(summary="x", findings=[]))  # stops immediately
    retrieval = types.SimpleNamespace(tools=[], overview="ov")
    trace: list = []

    run_researcher(researcher, retriever, retrieval, "trace it", trace,
                   max_steps=8, max_parallel=6, retriever_max_steps=2, max_total=10)

    workers = {e["worker"] for e in trace if e.get("event") == "sub_findings"}
    assert len(workers) == 10  # ceiling holds across batches (6 + 4), not 8 * 6


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


def test_researcher_delegates_reading(toolbox):
    from code_qa.retrieval import make_tools
    from code_qa.retrieval.researcher import _DELEGATED

    names = {t.name for t in make_tools(toolbox)}
    assert {"read_file", "search_lexical"} <= names          # the full toolbox has them
    planning = names - _DELEGATED                            # what the researcher keeps (pre-spawn_retrievers)
    assert "read_file" not in planning and "search_lexical" not in planning
    assert {"get_call_path", "structure_digest", "find_implementations"} <= planning


def test_trace_report_schema():
    report = TraceReport(
        summary="signing flow",
        steps=[FlowStep(order=1, symbol="JsignCLI.main", location="JsignCLI.java:54", calls=["execute"])],
        boundary_notes=["leaves into BouncyCastle for CMS"],
    )
    assert report.steps[0].symbol == "JsignCLI.main"
    assert report.boundary_notes
