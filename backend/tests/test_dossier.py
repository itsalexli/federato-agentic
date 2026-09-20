"""Folding hydrated API records into the flat dict the scorer reads."""
from app.agent.dossier import (
    _business_type, _collect_property, _indicative_premium, _loss_summary,
    _primary_state, _rank_locations, _ref_id, _scored_loss, _construction_mix,
)


def building(id_, tiv, year=2000, ctype="Steel Frame"):
    return {"id": id_, "tiv": tiv, "year_built": year, "construction_type": ctype}


def location(id_, state, buildings, lat=None, lon=None):
    return {"id": id_, "state": state, "zip": "00000", "buildings": buildings,
            "latitude": lat, "longitude": lon, "name": f"Site {id_}"}


def test_ref_id_handles_both_expanded_and_unexpanded_references():
    assert _ref_id(7) == 7
    assert _ref_id({"id": 7, "name": "Acme"}) == 7
    assert _ref_id(None) is None


def test_collects_buildings_from_every_expanded_route():
    """The planner expands both the HQ route and the exposure-unit route in one
    query; the walk has to pick up buildings from whichever one came back."""
    policies = [{
        "id": 1,
        "insured": {"id": 9, "hq": location(1, "CA", [building(10, 1_000)])},
        "exposure_units": [{"id": 2, "location": location(2, "CA", [building(20, 2_000)])}],
    }]
    buildings, locations = _collect_property(policies)
    assert {b["id"] for b in buildings} == {10, 20}
    assert {l["id"] for l in locations} == {1, 2}


def test_shared_buildings_are_counted_once():
    """The same location appears under every policy that touches it, and
    double-counting would inflate TIV."""
    loc = location(1, "CA", [building(10, 5_000_000)])
    policies = [
        {"id": 1, "exposure_units": [{"id": 1, "location": loc}]},
        {"id": 2, "exposure_units": [{"id": 2, "location": loc}]},
    ]
    buildings, _ = _collect_property(policies)
    assert len(buildings) == 1
    assert sum(b["tiv"] for b in buildings) == 5_000_000


def test_primary_state_follows_insured_value_not_address_count():
    """Three small Texas sheds do not outvote one large California plant."""
    buildings = [building(1, 500), building(2, 500), building(3, 500), building(4, 90_000)]
    locations = [
        location(1, "TX", [{"id": 1}]), location(2, "TX", [{"id": 2}]),
        location(3, "TX", [{"id": 3}]), location(4, "CA", [{"id": 4}]),
    ]
    assert _primary_state(locations, buildings) == "CA"


def test_primary_state_falls_back_to_address_count_without_values():
    locations = [location(1, "TX", []), location(2, "TX", []), location(3, "CA", [])]
    assert _primary_state(locations, []) == "TX"


def test_primary_state_is_none_without_locations():
    assert _primary_state([], []) is None


def test_locations_are_ordered_by_insured_value():
    """Everything downstream treats locations[0] as the primary risk site."""
    buildings = [building(1, 1_000), building(2, 80_000)]
    locations = [location(1, "TX", [{"id": 1}]), location(2, "CA", [{"id": 2}])]
    ranked = _rank_locations(locations, buildings)
    assert ranked[0]["state"] == "CA"
    assert ranked[0]["tiv"] == 80_000


def test_construction_mix_is_weighted_by_tiv():
    mix = _construction_mix([building(1, 9_000, ctype="Frame"),
                             building(2, 1_000, ctype="Steel Frame")])
    assert mix == {"Frame": 9_000, "Steel Frame": 1_000}


# --- premium ----------------------------------------------------------------

def test_indicative_premium_uses_the_most_recent_term():
    policies = [
        {"premium": 50_000, "dates": {"effective": "2022-01-01"},
         "policy_number": "OLD", "line_of_business": "property", "status": "expired"},
        {"premium": 90_000, "dates": {"effective": "2025-01-01"},
         "policy_number": "NEW", "line_of_business": "property", "status": "active"},
    ]
    premium, basis = _indicative_premium(policies)
    assert premium == 90_000
    assert "NEW" in basis and "indicative" in basis


def test_no_prior_term_means_no_premium_signal():
    assert _indicative_premium([]) == (None, None)


def test_business_type_is_inferred_from_prior_terms_on_the_same_line():
    assert _business_type([]) == "new"
    assert _business_type([{"premium": 1}]) == "renewal"


# --- losses -----------------------------------------------------------------

def test_incurred_loss_includes_outstanding_reserves():
    """Scoring paid-only would flatter an account whose big claims are still
    open -- exactly the account you most want flagged."""
    total, count = _loss_summary([{
        "paid_indemnity": 10_000, "paid_expense": 5_000,
        "reserve_indemnity": 80_000, "reserve_expense": 5_000,
    }])
    assert total == 100_000
    assert count == 1


def test_loss_is_scoped_to_the_line_being_underwritten():
    """A medical group with $4M of health claims and a clean property record
    is not a $4M property risk."""
    claims = [
        {"paid_indemnity": 4_000_000, "_line_of_business": "health"},
        {"paid_indemnity": 20_000, "_line_of_business": "property"},
    ]
    total, count, basis = _scored_loss(claims, "property", has_same_line=True)
    assert total == 20_000
    assert count == 1
    assert "property claims only" in basis


def test_loss_falls_back_to_all_lines_without_a_prior_term_to_isolate():
    claims = [{"paid_indemnity": 4_000_000, "_line_of_business": "health"}]
    total, _, basis = _scored_loss(claims, "property", has_same_line=False)
    assert total == 4_000_000
    assert "all lines" in basis


def test_a_clean_account_scores_zero_loss_not_unknown():
    total, count, basis = _scored_loss([], "property", has_same_line=True)
    assert total == 0.0 and count == 0
    assert "no claims" in basis
