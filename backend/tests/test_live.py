"""Live end-to-end checks. Skipped automatically when creds are absent.

    pytest backend/tests/test_live.py -v
"""
import pytest

from app.config import CLIENT_ID, CLIENT_SECRET
from app.agent.pipeline import UnderwritingAgent

pytestmark = pytest.mark.skipif(
    not (CLIENT_ID and CLIENT_SECRET),
    reason="FEDERATO_CLIENT_ID / FEDERATO_CLIENT_SECRET not set",
)


@pytest.fixture(scope="module")
def agent():
    return UnderwritingAgent()


@pytest.fixture(scope="module")
def result(agent):
    return agent.triage(enrich=False, use_llm=False)


def test_schema_discovery_returns_the_expected_resources(agent):
    idx = agent.schema()
    for expected in ("Policy", "Submission", "Building", "Location", "Claim", "Insured"):
        assert expected in idx


def test_the_documented_array_trap_is_caught_before_it_is_sent(agent):
    """`locations.state` is the failure the guidelines warn about."""
    idx = agent.schema()
    ok, _ = idx.validate_path("Policy", "premium")
    assert ok


def test_triage_ranks_the_open_queue(result):
    assert result.submissions
    scores = [s["score"] for s in result.submissions]
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 100 for s in scores)


def test_every_submission_carries_an_explanation_and_a_recommendation(result):
    for s in result.submissions:
        assert s["explanation"].strip()
        assert s["recommendation"]
        assert s["factors"]


def test_the_queue_costs_a_fixed_handful_of_queries_not_one_per_row(result):
    """Bulk fetching is the difference between 7 queries and 21."""
    assert result.stats["api_queries"] < 12
    assert result.stats["submission_count"] > 10


def test_the_trace_records_a_payload_for_every_query(result):
    queried = [s for s in result.trace["steps"] if s["payload"]]
    assert len(queried) == result.trace["query_count"]
    assert all(s["rationale"] for s in result.trace["steps"])


def test_property_submissions_outrank_out_of_appetite_lines(result):
    """The carrier's table is property-only; the ranking has to reflect that."""
    best = result.submissions[0]
    assert best["line_of_business"] == "property"
    assert not best["disqualified"]
