"""The carrier's 2025 appetite guidelines, expressed as data.

Keeping the guidelines declarative matters for two reasons: the planner reads
them to decide which fields it must go fetch, and the explainer reads the same
objects to describe why a submission scored the way it did. Change a threshold
here and the queries, the scores and the prose all move together.

Grading per the reference table:
    TARGET       -- the carrier actively wants this
    ACCEPTABLE   -- inside appetite, not a priority
    UNACCEPTABLE -- outside appetite
    UNKNOWN      -- the data to judge it wasn't available
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class Grade(str, Enum):
    TARGET = "target"
    ACCEPTABLE = "acceptable"
    UNACCEPTABLE = "unacceptable"
    UNKNOWN = "unknown"


# How much each grade is worth, before the factor's weight is applied.
GRADE_POINTS = {
    Grade.TARGET: 1.0,
    Grade.ACCEPTABLE: 0.6,
    Grade.UNACCEPTABLE: 0.0,
    # Unknown scores at the acceptable/unacceptable midpoint rather than zero.
    # Penalising missing data as though it were bad data would bury every new
    # submission that simply hasn't been worked up yet.
    Grade.UNKNOWN: 0.3,
}


@dataclass
class FactorResult:
    key: str
    label: str
    grade: Grade
    weight: float
    observed: Any
    detail: str
    is_hard_stop: bool = False

    @property
    def points(self) -> float:
        return GRADE_POINTS[self.grade] * self.weight

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "grade": self.grade.value,
            "weight": self.weight,
            "observed": self.observed,
            "detail": self.detail,
            "points": round(self.points, 2),
            "max_points": self.weight,
            "is_hard_stop": self.is_hard_stop,
        }


@dataclass
class Factor:
    """One row of the appetite table."""
    key: str
    label: str
    weight: float
    evaluate: Callable[[dict], tuple[Grade, Any, str]]
    # A hard stop means an UNACCEPTABLE grade disqualifies the submission
    # outright rather than just costing points.
    hard_stop: bool = False
    # Which dossier fields this factor consumes. The planner reads these to
    # work out what it needs to fetch.
    requires: tuple[str, ...] = field(default_factory=tuple)

    def run(self, dossier: dict) -> FactorResult:
        grade, observed, detail = self.evaluate(dossier)
        return FactorResult(
            key=self.key, label=self.label, grade=grade, weight=self.weight,
            observed=observed, detail=detail, is_hard_stop=self.hard_stop,
        )


# --- the 2025 commercial property table -------------------------------------

TARGET_STATES = {"OH", "PA", "MD", "CO", "CA", "FL"}
ACCEPTABLE_STATES = TARGET_STATES | {"NC", "SC", "GA", "VA", "UT"}

# The guidelines name "JM, non-combustible/steel, or masonry non-combustible"
# as acceptable. Fire Resistive and Modified Fire Resistive aren't listed, but
# they sit *above* every named class on the standard ISO construction ladder,
# so reading them as unacceptable would invert the intent of the rule. They are
# graded acceptable and the reason is surfaced in the explanation.
ACCEPTABLE_CONSTRUCTION = {
    "joisted masonry",
    "masonry non-combustible",
    "non-combustible",
    "steel frame",
    "fire resistive",
    "modified fire resistive",
}
INFERRED_CONSTRUCTION = {"fire resistive", "modified fire resistive"}
COMBUSTIBLE_CONSTRUCTION = {"frame", "wood frame"}

TARGET_LOB = "property"
LOSS_LIMIT = 100_000
TIV_CEILING = 150_000_000
TIV_TARGET = (50_000_000, 100_000_000)
PREMIUM_BAND = (50_000, 175_000)
PREMIUM_TARGET = (75_000, 100_000)
BUILDING_YEAR_ACCEPTABLE = 1990
BUILDING_YEAR_TARGET = 2010


def money(v: Any) -> str:
    """Human-readable currency, used by the scorer and the explainer alike."""
    return _money(v)


def _money(v: Any) -> str:
    if v is None:
        return "unknown"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def _f_line_of_business(d: dict):
    lob = d.get("line_of_business")
    if not lob:
        return Grade.UNKNOWN, None, "Line of business not stated on the submission."
    if lob == TARGET_LOB:
        return Grade.TARGET, lob, "Property is the carrier's target line."
    return (Grade.UNACCEPTABLE, lob,
            f"{lob} is outside the property book these guidelines cover.")


def _f_submission_type(d: dict):
    bt = d.get("business_type")
    if bt == "renewal":
        return Grade.TARGET, bt, "Renewal business is the carrier's stated target."
    if bt == "new":
        return Grade.ACCEPTABLE, bt, "New business is acceptable but not targeted."
    return Grade.UNKNOWN, bt, "Could not tell new business from renewal."


def _f_state(d: dict):
    st = d.get("primary_risk_state")
    if not st:
        return Grade.UNKNOWN, None, "No primary risk state could be resolved for this account."
    if st in TARGET_STATES:
        return Grade.TARGET, st, f"{st} is a target state."
    if st in ACCEPTABLE_STATES:
        return Grade.ACCEPTABLE, st, f"{st} is acceptable but not targeted."
    return Grade.UNACCEPTABLE, st, f"{st} is not in the filed footprint."


def _f_tiv(d: dict):
    tiv = d.get("tiv")
    if tiv is None:
        return Grade.UNKNOWN, None, "No TIV available -- no building values on record for this account."
    if tiv > TIV_CEILING:
        return (Grade.UNACCEPTABLE, tiv,
                f"TIV of {_money(tiv)} is over the {_money(TIV_CEILING)} ceiling.")
    if TIV_TARGET[0] <= tiv <= TIV_TARGET[1]:
        return (Grade.TARGET, tiv,
                f"TIV of {_money(tiv)} sits in the {_money(TIV_TARGET[0])}-{_money(TIV_TARGET[1])} sweet spot.")
    return (Grade.ACCEPTABLE, tiv,
            f"TIV of {_money(tiv)} is under the {_money(TIV_CEILING)} ceiling but outside the target band.")


def _f_premium(d: dict):
    prem = d.get("premium")
    if prem is None:
        return Grade.UNKNOWN, None, "No premium indication yet -- the submission is not quoted."
    if not (PREMIUM_BAND[0] <= prem <= PREMIUM_BAND[1]):
        side = "under" if prem < PREMIUM_BAND[0] else "over"
        return (Grade.UNACCEPTABLE, prem,
                f"Premium of {_money(prem)} is {side} the {_money(PREMIUM_BAND[0])}-{_money(PREMIUM_BAND[1])} band.")
    if PREMIUM_TARGET[0] <= prem <= PREMIUM_TARGET[1]:
        return (Grade.TARGET, prem,
                f"Premium of {_money(prem)} is in the {_money(PREMIUM_TARGET[0])}-{_money(PREMIUM_TARGET[1])} target band.")
    return Grade.ACCEPTABLE, prem, f"Premium of {_money(prem)} is inside the acceptable band."


def _f_building_age(d: dict):
    yr = d.get("oldest_building_year")
    if yr is None:
        return Grade.UNKNOWN, None, "No construction years on record for this account's buildings."
    if yr < BUILDING_YEAR_ACCEPTABLE:
        return (Grade.UNACCEPTABLE, yr,
                f"Oldest building dates to {yr}, before the {BUILDING_YEAR_ACCEPTABLE} cut-off.")
    if yr >= BUILDING_YEAR_TARGET:
        return Grade.TARGET, yr, f"Every building is {BUILDING_YEAR_TARGET} or newer (oldest {yr})."
    return Grade.ACCEPTABLE, yr, f"Oldest building is {yr} -- post-1990 and acceptable."


def _f_construction(d: dict):
    mix = d.get("construction_mix") or {}
    if not mix:
        return Grade.UNKNOWN, None, "No construction types on record for this account's buildings."
    total = sum(mix.values())
    good = sum(v for k, v in mix.items() if k.lower() in ACCEPTABLE_CONSTRUCTION)
    share = good / total if total else 0.0
    inferred = [k for k in mix if k.lower() in INFERRED_CONSTRUCTION]
    combustible = [k for k in mix if k.lower() in COMBUSTIBLE_CONSTRUCTION]
    note = ""
    if inferred:
        note = (f" {', '.join(inferred)} is graded acceptable: it is not named in the table "
                f"but outranks every class that is.")
    if share > 0.5:
        detail = f"{share:.0%} of building value is acceptable construction.{note}"
        return (Grade.TARGET if share >= 0.9 else Grade.ACCEPTABLE), round(share, 3), detail
    detail = f"Only {share:.0%} of building value is acceptable construction"
    if combustible:
        detail += f"; {', '.join(combustible)} makes up the balance"
    return Grade.UNACCEPTABLE, round(share, 3), detail + f".{note}"


def _f_loss_history(d: dict):
    loss = d.get("five_year_loss")
    if loss is None:
        return Grade.UNKNOWN, None, "No claim history retrievable for this account."
    count = d.get("five_year_claim_count") or 0
    claims = f"{count} claim{'s' if count != 1 else ''}"
    if loss > LOSS_LIMIT:
        return (Grade.UNACCEPTABLE, loss,
                f"{_money(loss)} incurred across {claims} in 5 years, over the {_money(LOSS_LIMIT)} limit.")
    if loss == 0:
        return Grade.TARGET, loss, "No claims in the last 5 years."
    return (Grade.ACCEPTABLE, loss,
            f"{_money(loss)} incurred across {claims} in 5 years, under the {_money(LOSS_LIMIT)} limit.")


FACTORS: list[Factor] = [
    Factor("line_of_business", "Line of business", 20, _f_line_of_business,
           hard_stop=True, requires=("line_of_business",)),
    Factor("state", "Primary risk state", 18, _f_state,
           hard_stop=True, requires=("primary_risk_state",)),
    Factor("tiv", "Total insured value", 16, _f_tiv, requires=("tiv",)),
    Factor("premium", "Total premium", 14, _f_premium, requires=("premium",)),
    Factor("loss_history", "5-year loss history", 12, _f_loss_history,
           requires=("five_year_loss", "five_year_claim_count")),
    Factor("construction", "Construction type", 10, _f_construction,
           requires=("construction_mix",)),
    Factor("building_age", "Building age", 6, _f_building_age,
           requires=("oldest_building_year",)),
    Factor("submission_type", "Submission type", 4, _f_submission_type,
           requires=("business_type",)),
]

MAX_POINTS = sum(f.weight for f in FACTORS)


@dataclass
class Scorecard:
    score: int
    factors: list[FactorResult]
    disqualified: bool
    disqualifiers: list[str]
    confidence: float
    recommendation: str
    contradictions: list[str]

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "max_score": 100,
            "factors": [f.as_dict() for f in self.factors],
            "disqualified": self.disqualified,
            "disqualifiers": self.disqualifiers,
            "confidence": round(self.confidence, 2),
            "recommendation": self.recommendation,
            "contradictions": self.contradictions,
        }


def score(dossier: dict) -> Scorecard:
    """Run every factor over an assembled dossier and produce a scorecard."""
    results = [f.run(dossier) for f in FACTORS]

    disqualifiers = [
        f"{r.label}: {r.detail}"
        for r in results
        if r.is_hard_stop and r.grade is Grade.UNACCEPTABLE
    ]
    earned = sum(r.points for r in results)
    raw = round(100 * earned / MAX_POINTS)

    # Confidence is the share of scoring weight backed by real observed data.
    known_weight = sum(r.weight for r in results if r.grade is not Grade.UNKNOWN)
    confidence = known_weight / MAX_POINTS

    # A hard-stop failure caps the score rather than zeroing it: an underwriter
    # still wants to see that an out-of-footprint account is otherwise strong,
    # because it's a candidate for a broker conversation or a filing question.
    final = min(raw, 25) if disqualifiers else raw

    contradictions = _find_contradictions(results)
    return Scorecard(
        score=final,
        factors=results,
        disqualified=bool(disqualifiers),
        disqualifiers=disqualifiers,
        confidence=confidence,
        recommendation=_recommend(final, disqualifiers, confidence, contradictions),
        contradictions=contradictions,
    )


def _find_contradictions(results: list[FactorResult]) -> list[str]:
    """Flag submissions that pull in both directions, so the prose can say so."""
    out = []
    strong = [r for r in results if r.grade is Grade.TARGET]
    weak = [r for r in results if r.grade is Grade.UNACCEPTABLE]
    if strong and weak:
        out.append(
            f"Targets on {', '.join(r.label.lower() for r in strong)} "
            f"but falls outside appetite on {', '.join(r.label.lower() for r in weak)}."
        )
    unknown_weight = sum(r.weight for r in results if r.grade is Grade.UNKNOWN)
    if unknown_weight >= 25:
        missing = [r.label.lower() for r in results if r.grade is Grade.UNKNOWN]
        out.append(
            f"{unknown_weight:.0f} of {MAX_POINTS:.0f} scoring points rest on data we "
            f"could not retrieve ({', '.join(missing)}), so this rank is provisional."
        )
    return out


def _recommend(score_: int, disqualifiers: list[str], confidence: float,
               contradictions: list[str]) -> str:
    if disqualifiers:
        return "decline"
    if confidence < 0.55:
        return "request_information"
    if score_ >= 80:
        return "prioritize"
    if score_ >= 60:
        return "review"
    if score_ >= 40:
        return "review_with_conditions"
    return "decline"
