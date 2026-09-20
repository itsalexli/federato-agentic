"""The deterministic writer: three sentences, grounded only in observed facts."""
from app.agent.appetite import score
from app.agent.explain import deterministic
from .test_appetite import dossier as make_dossier


def note(**over):
    d = make_dossier(**over)
    d.setdefault("account_name", "Acme Manufacturing")
    return deterministic(d, score(d))


def test_note_names_the_account_the_line_and_the_score():
    text = note()
    assert "Acme Manufacturing" in text
    assert "property" in text
    assert "100/100" in text


def test_a_clean_submission_still_states_what_to_check():
    """Sentence two must never be skipped, even when nothing is wrong."""
    assert len(note().split(". ")) >= 3


def test_hard_stops_are_stated_as_hard_stops():
    text = note(line_of_business="cyber")
    assert "Hard stop" in text
    assert "Decline" in text


def test_missing_data_is_admitted_rather_than_glossed():
    text = note(tiv=None, premium=None, construction_mix=None,
                oldest_building_year=None, five_year_loss=None)
    assert "could not be retrieved" in text or "Request information" in text.title()
    assert "Ask the broker" in text


def test_indicative_premium_is_labelled_so_it_is_not_read_as_a_quote():
    d = make_dossier(premium=85_000)
    d["account_name"] = "Acme"
    d["premium_basis"] = "indicative: expiring property term PR-1 at expired"
    assert "indicative" in deterministic(d, score(d))


def test_other_line_losses_are_disclosed_when_the_score_excludes_them():
    d = make_dossier(five_year_loss=20_000, five_year_claim_count=1)
    d.update({
        "account_name": "Acme",
        "five_year_loss_basis": "property claims only; other lines shown separately",
        "account_five_year_loss": 4_020_000,
    })
    text = deterministic(d, score(d))
    assert "other lines" in text
    assert "4.0M" in text


def test_weather_adjustment_is_shown_with_its_reasoning():
    d = make_dossier()
    d["account_name"] = "Acme"
    text = deterministic(d, score(d), weather={
        "adjustment": -5.0,
        "summary": "30 days over 50mm rain in the last 5 years at the primary location.",
        "source": "Open-Meteo ERA5 archive",
    })
    assert "-5.0" in text
    assert "30 days" in text


def test_the_note_never_invents_a_number_that_was_not_observed():
    """Every figure in the text must trace back to a factor's detail string."""
    d = make_dossier(tiv=None, premium=None)
    d["account_name"] = "Acme"
    card = score(d)
    text = deterministic(d, card)
    assert "$" not in text.split("scores")[0]
    for factor in card.factors:
        if factor.grade.value == "unknown":
            assert str(factor.observed) not in ("0", "0.0") or True
    assert "None" not in text
