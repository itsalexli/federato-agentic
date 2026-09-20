"""The natural-language query loop.

The model is stubbed with a scripted sequence of tool calls, so the plumbing --
dispatch, validation, truncation, error feedback, trace capture -- is exercised
end to end without an API key or a real completion.
"""
import sys
import types

import pytest

from app.agent import ask as ask_mod
from app.agent.ask import AskError, AskSession
from app.agent.planner import QueryPlanner
from app.agent.trace import Trace
from app.federato.client import FederatoError
from app.federato.schema import SchemaIndex
from .test_schema import RAW


class StubClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def query(self, payload):
        self.seen.append(payload)
        nxt = self.responses.pop(0) if self.responses else {"results": [], "total": 0}
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def planner(*responses):
    client = StubClient(*responses)
    return QueryPlanner(client, SchemaIndex(RAW), Trace()), client


def session():
    return AskSession(agent=None)


# --- run_query tool ---------------------------------------------------------

def test_rejects_a_payload_with_no_resource():
    p, _ = planner()
    out = session()._run_query(p, {"where": {"status": "active"}}, "why")
    assert "error" in out


def test_unknown_resource_hands_back_the_real_resource_list():
    p, _ = planner()
    out = session()._run_query(p, {"resource": "Submissions"}, "why")
    assert "error" in out
    assert "Policy" in out["known_resources"]


def test_returns_rows_and_an_exact_total():
    p, _ = planner({"results": [{"id": 1}, {"id": 2}], "total": 2})
    out = session()._run_query(p, {"resource": "Policy"}, "why")
    assert out["total"] == 2
    assert out["returned"] == 2
    assert len(out["rows"]) == 2


def test_truncates_rows_but_keeps_the_total_exact():
    """A count must come from `total`, never from the rows the model can see."""
    big = {"results": [{"id": i} for i in range(500)], "total": 500}
    p, _ = planner(big)
    out = session()._run_query(p, {"resource": "Policy"}, "why")
    assert out["total"] == 500
    assert len(out["rows"]) == ask_mod.MAX_ROWS_TO_MODEL
    assert "exact" in out["note"]


def test_warns_on_an_array_dot_path_before_spending_a_round_trip():
    """The documented pitfall, caught and explained rather than silently empty."""
    p, _ = planner({"results": [], "total": 0})
    out = session()._run_query(
        p, {"resource": "Submission", "where": {"locations.state": "CA"}}, "why")
    assert any("$elemMatch" in w for w in out["warnings"])


def test_a_filter_reaching_through_an_expanded_reference_is_not_warned_about():
    """`filter` legitimately sees paths the raw resource schema cannot."""
    p, _ = planner({"results": [{"id": 1}], "total": 1})
    out = session()._run_query(
        p,
        {"resource": "Policy", "expand": {"insured": True},
         "filter": {"insured.name": "Acme"}},
        "why",
    )
    assert "warnings" not in out


def test_an_api_error_comes_back_as_feedback_not_an_exception():
    """An error the planner cannot repair reaches the model as data, so it can
    correct itself on the next turn instead of the run dying."""
    p, _ = planner(FederatoError('[VALIDATION_ERROR] Unknown operator "$grt"'))
    out = session()._run_query(
        p, {"resource": "Policy", "where": {"premium": {"$grt": 1}}}, "why")
    assert "error" in out
    assert "hint" in out


def test_a_repairable_bad_field_is_fixed_before_the_model_ever_sees_it():
    """The model's mistakes go through the same adaptive runner as everything
    else -- a dropped bad clause beats a failed turn."""
    p, client = planner(
        FederatoError('[VALIDATION_ERROR] unknown field {"path":"nonsense"}'),
        {"results": [{"id": 1}], "total": 1},
    )
    out = session()._run_query(
        p, {"resource": "Policy", "where": {"nonsense": 1, "status": "active"}}, "why")
    assert out["total"] == 1
    assert "nonsense" not in client.seen[1]["where"]


def test_every_model_query_lands_in_the_trace():
    p, _ = planner({"results": [{"id": 1}], "total": 1})
    session()._run_query(p, {"resource": "Policy"}, "Counting active policies")
    assert p.trace.steps[-1].goal == "Counting active policies"
    assert p.trace.steps[-1].payload["resource"] == "Policy"


# --- the loop ---------------------------------------------------------------

class Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class StubMessages:
    """Replays scripted model turns and records what it was sent."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        return self.script.pop(0)


class StubAnthropic:
    instance = None

    def __init__(self, api_key=None):
        self.messages = StubAnthropic.instance


def install(monkeypatch, script):
    StubAnthropic.instance = StubMessages(script)
    mod = types.ModuleType("anthropic")
    mod.Anthropic = StubAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(ask_mod, "LLM_ENABLED", True)
    monkeypatch.setattr(ask_mod, "ANTHROPIC_API_KEY", "stub")
    return StubAnthropic.instance


class StubAgent:
    """Stands in for UnderwritingAgent: a schema, a client, nothing else."""

    def __init__(self, *responses):
        self.client = StubClient(*responses)

    def schema(self, trace=None):
        return SchemaIndex(RAW)


def test_without_a_key_it_says_so_instead_of_failing_obscurely(monkeypatch):
    monkeypatch.setattr(ask_mod, "LLM_ENABLED", False)
    with pytest.raises(AskError) as e:
        AskSession(StubAgent()).ask("anything")
    assert "ANTHROPIC_API_KEY" in str(e.value)


def test_a_tool_call_is_executed_and_its_result_fed_back(monkeypatch):
    script = [
        Block(stop_reason="tool_use", content=[
            Block(type="tool_use", id="t1", name="run_query",
                  input={"payload": {"resource": "Policy", "where": {"status": "active"}},
                         "why": "Count active policies"}),
        ]),
        Block(stop_reason="end_turn", content=[
            Block(type="text", text="There are 76 active policies."),
        ]),
    ]
    stub = install(monkeypatch, script)
    agent = StubAgent({"results": [{"id": 1}], "total": 76})

    out = AskSession(agent).ask("How many active policies are there?")

    assert out["answer"] == "There are 76 active policies."
    assert out["tool_calls"] == 1
    assert agent.client.seen[0]["where"] == {"status": "active"}
    # the tool result must reach the model on the following turn
    followup = stub.calls[1]["messages"][-1]["content"][0]
    assert followup["type"] == "tool_result"
    assert '"total": 76' in followup["content"]


def test_the_models_queries_appear_in_the_returned_trace(monkeypatch):
    script = [
        Block(stop_reason="tool_use", content=[
            Block(type="tool_use", id="t1", name="run_query",
                  input={"payload": {"resource": "Policy"}, "why": "Look at policies"}),
        ]),
        Block(stop_reason="end_turn", content=[Block(type="text", text="Done.")]),
    ]
    install(monkeypatch, script)
    out = AskSession(StubAgent({"results": [], "total": 0})).ask("q")
    goals = [s["goal"] for s in out["trace"]["steps"]]
    assert "Look at policies" in goals


def test_the_schema_and_query_rules_are_given_to_the_model(monkeypatch):
    script = [Block(stop_reason="end_turn", content=[Block(type="text", text="ok")])]
    stub = install(monkeypatch, script)
    AskSession(StubAgent()).ask("q")
    system = stub.calls[0]["system"]
    assert "$elemMatch" in system          # the array rule
    assert "Building:" in system           # the discovered schema
    assert "score_submissions" in system   # scoring is delegated, not improvised


def test_an_unknown_tool_name_is_reported_back_rather_than_crashing(monkeypatch):
    script = [
        Block(stop_reason="tool_use", content=[
            Block(type="tool_use", id="t1", name="delete_everything", input={}),
        ]),
        Block(stop_reason="end_turn", content=[Block(type="text", text="ok")]),
    ]
    stub = install(monkeypatch, script)
    AskSession(StubAgent()).ask("q")
    assert "Unknown tool" in stub.calls[1]["messages"][-1]["content"][0]["content"]


def test_the_loop_is_capped_and_says_so(monkeypatch):
    turn = Block(stop_reason="tool_use", content=[
        Block(type="tool_use", id="t", name="run_query",
              input={"payload": {"resource": "Policy"}, "why": "again"}),
    ])
    script = [turn] * 4 + [Block(stop_reason="end_turn",
                                 content=[Block(type="text", text="Partial answer.")])]
    install(monkeypatch, script)
    out = AskSession(StubAgent(), max_turns=3).ask("q")
    assert out["truncated"] is True
    assert out["answer"] == "Partial answer."
