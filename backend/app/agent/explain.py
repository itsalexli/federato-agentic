"""Decision explanations.

Two paths to the same contract: three sentences an underwriter can act on,
grounded only in facts the scorer actually observed.

The deterministic writer runs always and is what the tests assert against. The
LLM writer, when a key is present, rewrites the same material in better prose
-- but it is handed the scorecard rather than the raw data, so it can only
restate factors that were genuinely evaluated. If it fails or times out, the
deterministic text stands and the run says so.
"""
from __future__ import annotations

from ..config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_ENABLED
from .appetite import Grade, Scorecard, money

RECOMMENDATION_TEXT = {
    "prioritize": "Prioritize -- work this ahead of the rest of the queue.",
    "review": "Review for acceptance.",
    "review_with_conditions": "Review, but expect to attach conditions.",
    "request_information": "Request information before pricing.",
    "decline": "Decline, or refer back to the broker.",
}

SYSTEM_PROMPT = """You write triage notes for commercial property underwriters.

You will be given a submission's scorecard: each appetite factor, the grade it \
earned, and the observed value behind it. Write exactly three sentences.

Sentence 1: the account, the line, and the single strongest reason it scored \
where it did.
Sentence 2: the material counterweight -- the worst factor, any contradiction, \
or the data that was missing. Never skip this sentence; if the submission is \
clean, say what would still need checking.
Sentence 3: the recommendation and the concrete next action.

Rules:
- Use only facts present in the scorecard. Never invent a number.
- Where a value is marked indicative or unknown, say so plainly.
- Write the way an underwriter talks. No marketing tone, no hedging filler, \
no bullet points, no headings.
- Do not open with the account name every time; vary the sentence shape."""


def explain(dossier: dict, card: Scorecard, weather: dict | None = None,
            use_llm: bool = LLM_ENABLED) -> tuple[str, str]:
    """Return (explanation, source) where source is 'llm' or 'deterministic'."""
    fallback = deterministic(dossier, card, weather)
    if not use_llm:
        return fallback, "deterministic"
    try:
        return _llm(dossier, card, weather), "llm"
    except Exception:
        return fallback, "deterministic"


# --- deterministic writer ---------------------------------------------------

def deterministic(dossier: dict, card: Scorecard, weather: dict | None = None) -> str:
    name = dossier.get("account_name") or f"Submission {dossier.get('submission_number')}"
    lob = dossier.get("line_of_business") or "unspecified line"
    ranked = sorted(card.factors, key=lambda f: f.points, reverse=True)
    best = [f for f in ranked if f.grade in (Grade.TARGET, Grade.ACCEPTABLE)]
    worst = [f for f in card.factors if f.grade is Grade.UNACCEPTABLE]
    unknown = [f for f in card.factors if f.grade is Grade.UNKNOWN]

    if best:
        top = best[0]
        first = f"{name} ({lob}) scores {card.score}/100. {top.detail}"
        if len(best) > 1:
            first += f" {best[1].detail}"
    else:
        first = f"{name} ({lob}) scores {card.score}/100 with nothing scoring in appetite."

    if card.disqualified:
        second = "Hard stop -- " + "; ".join(
            d.rstrip(".") for d in card.disqualifiers) + "."
    elif worst:
        second = " ".join(f.detail for f in worst[:2])
    elif unknown:
        missing = ", ".join(f.label.lower() for f in unknown)
        second = (f"Scored at {card.confidence:.0%} confidence -- {missing} "
                  f"could not be retrieved for this account.")
    else:
        second = ("Every factor is inside appetite; the open question is whether the "
                  "indicative premium survives pricing.")

    # The first contradiction just re-lists factors the sentence above already
    # spelled out, so only the low-confidence warning earns a place in prose.
    provisional = [c for c in card.contradictions if "provisional" in c]
    if provisional:
        second += " " + provisional[0]

    if weather and weather.get("adjustment"):
        sign = "+" if weather["adjustment"] > 0 else ""
        second += (f" That score includes a {sign}{weather['adjustment']} weather "
                   f"adjustment: {weather['summary']}")

    third = RECOMMENDATION_TEXT.get(card.recommendation, "Review.")
    if card.recommendation == "request_information":
        wanted = ", ".join(f.label.lower() for f in unknown) or "the missing exposure data"
        third += f" Ask the broker for {wanted}."
    elif dossier.get("premium_basis"):
        third += f" Premium shown is {dossier['premium_basis']}."
    if dossier.get("account_five_year_loss") and dossier.get("five_year_loss_basis", "").startswith(
            str(dossier.get("line_of_business"))):
        other = (dossier["account_five_year_loss"] or 0) - (dossier.get("five_year_loss") or 0)
        if other > 0:
            third += (f" Scored on {dossier['line_of_business']} losses only; the account "
                      f"carries a further {money(other)} on other lines.")

    return " ".join(part.strip() for part in (first, second, third) if part).strip()


# --- LLM writer -------------------------------------------------------------

def _llm(dossier: dict, card: Scorecard, weather: dict | None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _prompt(dossier, card, weather)}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    if not text:
        raise ValueError("empty completion")
    return text


def _prompt(dossier: dict, card: Scorecard, weather: dict | None) -> str:
    lines = [
        f"Account: {dossier.get('account_name')}",
        f"Submission: {dossier.get('submission_number')} ({dossier.get('status')})",
        f"Line of business: {dossier.get('line_of_business')}",
        f"Received: {dossier.get('received_date')}; target effective: {dossier.get('target_effective_date')}",
        f"Broker: {dossier.get('broker_name')} (tier {dossier.get('broker_tier')})",
        "",
        f"SCORE: {card.score}/100 at {card.confidence:.0%} confidence",
        f"System recommendation: {card.recommendation}",
        "",
        "FACTORS:",
    ]
    for f in card.factors:
        lines.append(
            f"- {f.label}: {f.grade.value.upper()} "
            f"({f.points:.0f}/{f.weight:.0f} pts) -- {f.detail}"
        )
    if dossier.get("premium_basis"):
        lines += ["", f"NOTE: premium is not a quote -- {dossier['premium_basis']}."]
    if card.disqualifiers:
        lines += ["", "HARD STOPS: " + "; ".join(card.disqualifiers)]
    if card.contradictions:
        lines += ["", "CONTRADICTIONS: " + " ".join(card.contradictions)]
    if weather:
        lines += ["", f"EXTERNAL WEATHER ({weather.get('source')}): {weather.get('summary')} "
                      f"Score adjustment applied: {weather.get('adjustment')}."]
    lines += [
        "",
        f"Prior policies on file for this account: {dossier.get('prior_policy_count')} "
        f"({', '.join(dossier.get('prior_policy_lines') or []) or 'none'}).",
        "",
        "Write the three-sentence triage note.",
    ]
    return "\n".join(lines)
