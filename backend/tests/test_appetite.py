"""Scoring behaviour against the 2025 commercial property table."""
import pytest

from app.agent.appetite import FACTORS, Grade, score


def dossier(**over):
    """A submission that targets on every factor, before `over` spoils one."""
    base = {
        "line_of_business": "property",
        "business_type": "renewal",
        "primary_risk_state": "CA",
        "tiv": 75_000_000,
        "premium": 85_000,
        "oldest_building_year": 2015,
        "construction_mix": {"Masonry Non-Combustible": 10_000_000},
        "five_year_loss": 0.0,
        "five_year_claim_count": 0,
    }
    base.update(over)
    return base


def grade_of(card, key):
    return next(f.grade for f in card.factors if f.key == key)


def test_a_perfect_submission_scores_100():
    assert score(dossier()).score == 100


def test_weights_sum_to_the_full_scale():
    assert sum(f.weight for f in FACTORS) == 100


# --- hard stops -------------------------------------------------------------

def test_non_property_line_is_a_hard_stop():
    card = score(dossier(line_of_business="cyber"))
    assert card.disqualified
    assert card.recommendation == "decline"


def test_out_of_footprint_state_is_a_hard_stop():
    assert score(dossier(primary_risk_state="TN")).disqualified


def test_hard_stop_caps_rather_than_zeroes_so_strong_risks_stay_visible():
    """An out-of-footprint account that is otherwise excellent is a filing
    question, not a nothing -- it must still outrank a genuinely bad risk."""
    out_of_state = score(dossier(primary_risk_state="TN"))
    genuinely_bad = score(dossier(
        primary_risk_state="TN", tiv=200_000_000, premium=10_000,
        oldest_building_year=1955, construction_mix={"Wood Frame": 5_000_000},
        five_year_loss=900_000, five_year_claim_count=12,
    ))
    assert out_of_state.score > genuinely_bad.score
    assert out_of_state.score <= 25


# --- individual factors -----------------------------------------------------

@pytest.mark.parametrize("state,expected", [
    ("CA", Grade.TARGET), ("OH", Grade.TARGET),
    ("GA", Grade.ACCEPTABLE), ("UT", Grade.ACCEPTABLE),
    ("TX", Grade.UNACCEPTABLE), ("NY", Grade.UNACCEPTABLE),
])
def test_state_grading_follows_the_table(state, expected):
    assert grade_of(score(dossier(primary_risk_state=state)), "state") is expected


@pytest.mark.parametrize("tiv,expected", [
    (75_000_000, Grade.TARGET),
    (20_000_000, Grade.ACCEPTABLE),
    (140_000_000, Grade.ACCEPTABLE),
    (160_000_000, Grade.UNACCEPTABLE),
])
def test_tiv_bands(tiv, expected):
    assert grade_of(score(dossier(tiv=tiv)), "tiv") is expected


@pytest.mark.parametrize("premium,expected", [
    (85_000, Grade.TARGET),
    (60_000, Grade.ACCEPTABLE),
    (40_000, Grade.UNACCEPTABLE),
    (200_000, Grade.UNACCEPTABLE),
])
def test_premium_bands(premium, expected):
    assert grade_of(score(dossier(premium=premium)), "premium") is expected


@pytest.mark.parametrize("year,expected", [
    (2015, Grade.TARGET), (1995, Grade.ACCEPTABLE), (1975, Grade.UNACCEPTABLE),
])
def test_building_age_bands(year, expected):
    assert grade_of(score(dossier(oldest_building_year=year)), "building_age") is expected


def test_construction_is_weighted_by_value_not_building_count():
    """Ten sheds and one steel warehouse is not a frame risk."""
    by_value = score(dossier(construction_mix={
        "Wood Frame": 1_000_000,      # many small buildings
        "Steel Frame": 40_000_000,    # one that carries the value
    }))
    # Same building counts, inverted values -- the grade must follow the money.
    by_count = score(dossier(construction_mix={
        "Wood Frame": 40_000_000,
        "Steel Frame": 1_000_000,
    }))
    assert grade_of(by_value, "construction") is not Grade.UNACCEPTABLE
    assert grade_of(by_count, "construction") is Grade.UNACCEPTABLE


def test_majority_combustible_construction_is_out_of_appetite():
    card = score(dossier(construction_mix={
        "Wood Frame": 40_000_000, "Steel Frame": 1_000_000,
    }))
    assert grade_of(card, "construction") is Grade.UNACCEPTABLE


def test_fire_resistive_is_read_as_acceptable_though_unnamed_in_the_table():
    """It outranks every class the table does name; grading it out would
    invert the rule's intent. The explanation says so explicitly."""
    card = score(dossier(construction_mix={"Fire Resistive": 30_000_000}))
    factor = next(f for f in card.factors if f.key == "construction")
    assert factor.grade in (Grade.TARGET, Grade.ACCEPTABLE)
    assert "outranks" in factor.detail


def test_loss_over_the_limit_is_out_of_appetite():
    card = score(dossier(five_year_loss=250_000, five_year_claim_count=3))
    assert grade_of(card, "loss_history") is Grade.UNACCEPTABLE


# --- missing data -----------------------------------------------------------

def test_missing_data_grades_unknown_rather_than_bad():
    """Penalising an unworked submission as though it were a bad risk would
    bury every genuinely new account in the queue."""
    known = score(dossier(premium=None))
    scored_as_bad = score(dossier(premium=10_000))
    assert grade_of(known, "premium") is Grade.UNKNOWN
    assert known.score > scored_as_bad.score


def test_confidence_tracks_the_share_of_observed_data():
    assert score(dossier()).confidence == 1.0
    thin = score(dossier(tiv=None, premium=None, construction_mix=None))
    assert thin.confidence < 0.65


def test_low_confidence_asks_for_information_instead_of_declining():
    card = score(dossier(
        tiv=None, premium=None, construction_mix=None,
        oldest_building_year=None, five_year_loss=None, business_type=None,
    ))
    assert card.recommendation == "request_information"


def test_heavily_unknown_submissions_are_flagged_as_provisional():
    card = score(dossier(tiv=None, premium=None, construction_mix=None))
    assert any("provisional" in c for c in card.contradictions)


# --- contradictions ---------------------------------------------------------

def test_mixed_submissions_surface_the_contradiction():
    card = score(dossier(five_year_loss=500_000, five_year_claim_count=6))
    assert card.contradictions
    assert "loss history" in card.contradictions[0]


def test_recommendation_ladder_is_monotonic_in_score():
    ladder = ["prioritize", "review", "review_with_conditions", "decline"]
    seen = [
        score(dossier()).recommendation,
        score(dossier(premium=60_000, tiv=20_000_000,
                      oldest_building_year=1995)).recommendation,
    ]
    assert all(s in ladder for s in seen)
    assert ladder.index(seen[0]) <= ladder.index(seen[1])
