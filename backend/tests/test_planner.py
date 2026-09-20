"""Planner behaviour: locating data from the schema, and adapting when a query
comes back wrong. A stub client stands in for the API."""
import pytest

from app.agent.planner import QueryPlanner
from app.agent.trace import Trace
from app.federato.client import FederatoError
from app.federato.schema import SchemaIndex
from .test_schema import RAW


class StubClient:
    """Replays a scripted sequence of responses, recording what it was asked."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.seen = []

    def query(self, payload):
        self.seen.append(payload)
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def planner(*responses):
    client = StubClient(*responses)
    return QueryPlanner(client, SchemaIndex(RAW), Trace()), client


def rows(n, total=None):
    return {"results": [{"id": i} for i in range(n)], "total": total if total is not None else n}


# --- locating data ----------------------------------------------------------

def test_locates_tiv_on_building_rather_than_guessing():
    p, _ = planner()
    route = p.resolve("tiv")
    assert route.resource == "Building"
    assert route.path == "tiv"


def test_prefers_the_anchor_resource_when_it_holds_the_field_itself():
    p, _ = planner()
    assert p.resolve("premium").resource == "Policy"


def test_route_resolution_is_recorded_in_the_trace():
    p, _ = planner()
    p.resolve_all(["tiv", "premium"])
    step = p.trace.steps[-1]
    assert "Building.tiv" in step.outcome


# --- adaptation -------------------------------------------------------------

def test_broadens_the_query_when_a_valid_one_returns_nothing():
    p, client = planner(rows(0), rows(4))
    broad = {"resource": "Policy"}
    out = p.run({"resource": "Policy", "where": {"status": "bound"}},
                goal="g", rationale="r",
                broaden=[(broad, "Dropped the status filter.")])
    assert len(out["results"]) == 4
    assert client.seen[1] == broad
    assert p.trace.steps[-1].adaptation == "Dropped the status filter."


def test_stops_broadening_once_results_arrive():
    p, client = planner(rows(3))
    p.run({"resource": "Policy"}, goal="g", rationale="r",
          broaden=[({"resource": "Policy"}, "unused")])
    assert len(client.seen) == 1


def test_rewrites_an_array_dot_path_as_elemmatch_and_retries():
    """The documented pitfall, repaired from the schema instead of failing."""
    err = FederatoError('[VALIDATION_ERROR] bad path {"path":"locations.state"}')
    p, client = planner(err, rows(6))
    out = p.run({"resource": "Submission", "where": {"locations.state": "CA"}},
                goal="g", rationale="r")
    assert len(out["results"]) == 6
    assert client.seen[1]["where"] == {"locations": {"$elemMatch": {"state": "CA"}}}


def test_drops_an_unknown_filter_rather_than_losing_the_whole_result_set():
    err = FederatoError('[VALIDATION_ERROR] unknown field {"path":"nonsense"}')
    p, client = planner(err, rows(2))
    p.run({"resource": "Policy", "where": {"nonsense": 1, "status": "bound"}},
          goal="g", rationale="r")
    assert "nonsense" not in client.seen[1]["where"]
    assert client.seen[1]["where"]["status"] == "bound"


def test_an_unrepairable_error_is_raised_not_swallowed():
    err = FederatoError("[INTERNAL_ERROR] upstream exploded")
    p, _ = planner(err)
    with pytest.raises(FederatoError):
        p.run({"resource": "Policy"}, goal="g", rationale="r")
    assert p.trace.steps[-1].error


# --- plan shapes ------------------------------------------------------------

def test_account_policy_plan_expands_every_route_to_building_at_once():
    p, _ = planner()
    expand = p.plan_account_policies([1, 2])["expand"]
    assert expand["exposure_units"]["location"]["buildings"] is True
    assert expand["insured"]["hq"]["buildings"] is True


def test_claim_plan_filters_after_expansion_not_before():
    """Claim has no insured field; the link only exists once policy is hydrated."""
    p, _ = planner()
    plan = p.plan_account_claims([1], "2021-01-01")
    assert "date_of_loss" in plan["where"]
    assert "policy.insured" in plan["filter"]
