"""Answers questions about the agent itself.

`ask.py` answers questions about the *book* by planning queries. This answers
questions about the *run* -- why a submission scored what it did, which queries
produced it, why a rule is written the way it is. It needs no tools: the
reasoning trace, the scorecard and the appetite config are already in memory,
so one completion with the right context beats a tool-calling loop.
"""
from __future__ import annotations

from ..config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_ENABLED
from . import appetite

MAX_TRACE_STEPS = 14


ARCHITECTURE = """\
HOW THIS AGENT IS BUILT (ground truth -- do not embellish):

Pipeline: discover schema -> locate the data each appetite rule needs -> plan
queries -> execute with adaptation -> assemble a dossier per submission ->
score -> enrich -> explain -> rank.

Schema discovery. No field-by-field reference is published, so the agent calls
action:"schema" at startup and derives everything from the response. Join routes
come from a breadth-first search over reference fields, never hardcoded. Policy
reaches Building by two equally short routes -- insured.hq.buildings and
exposure_units.location.buildings -- and both are expanded in one query because
they reach different buildings.

The core data problem. Open submissions (received/cleared/quoted) have NO linked
policy: Policy.submission covers only the 113 bound ones. So premium, TIV,
construction, building year and loss history are unreachable that way. The agent
works the account instead -- Submission.insured -> HQ location, the buildings on
prior policies, and the account's claims.

Scoring is deterministic, not model-generated. Eight weighted factors totalling
100 points. Target scores full weight, acceptable 60%, unknown 30%, unacceptable
0. Line of business and primary risk state are hard stops that CAP the score at
25 rather than zeroing it, so a strong out-of-footprint account stays visible.
Confidence is the share of scoring weight backed by observed data.

Deliberate judgement calls, each made because of something in the data:
- Missing data grades 30%, not 0 -- otherwise every unworked submission sinks.
- Loss is scored as INCURRED (paid + outstanding reserves); 61% of loss in this
  book is still reserved, so paid-only would understate it roughly 2.6x.
- Loss is scoped to the line being underwritten when the account has written
  that line before; account-wide loss is carried alongside and disclosed.
- Premium on an unquoted submission is the expiring same-line term, labelled
  indicative. It is never a hard stop: two thirds of this book's written
  property premium already sits outside the stated band.
- Construction is weighted by insured value, not building count.
- Fire Resistive is graded acceptable though the table never names it -- it
  outranks every class the table does name.
- Primary risk state is the state carrying the most insured value.

Enrichment. Open-Meteo's ERA5 archive, keyless, gives 5 years of daily rain and
wind gusts at each account's largest location. It adjusts the score by at most
+/-5 points -- a tiebreaker, never enough to overturn the carrier's table.

Explanations. Generated FROM the scorecard, not the raw record, so a note can
only cite a factor that was actually evaluated. A deterministic writer always
runs; the model rewrites the top of the queue when a key is present.

Known API quirk: the `over` stage does not collapse groups on this deployment,
so the agent detects it at runtime and recomputes rollups client-side."""


SYSTEM = """You explain an underwriting agent to the person using it.

You are given the architecture, the reasoning trace from the run currently on \
screen, and -- when the user has a submission selected -- its full scorecard. \
Answer from those. They are the truth about this run.

Rules:
- Be specific. Cite the actual score, factor, query or number, not a paraphrase.
- If the answer is in the trace, say which step.
- Distinguish what is deterministic from what a model did. Scoring and ranking \
are rules; only the prose and the natural-language query planner involve a model. \
Never imply a score was model-generated.
- If something is not in the context you were given, say so plainly instead of \
inventing it.
- Two or three short paragraphs at most, usually less. No headings, no bullet \
lists unless genuinely enumerating. Plain sentences.
- Write to an underwriter or an engineer reading over their shoulder, not to a \
judge being pitched."""


class MetaError(RuntimeError):
    pass


def _weights() -> str:
    return "; ".join(
        f"{f.label} {f.weight:g}" + (" (hard stop)" if f.hard_stop else "")
        for f in appetite.FACTORS
    )


def _context(payload: dict) -> str:
    """Flatten the on-screen state into something worth reading."""
    out: list[str] = []

    stats = payload.get("stats") or {}
    if stats:
        out.append(
            "THIS RUN: {n} submissions, {ok} in appetite, {bad} hard-stopped. "
            "Mean score {m}/100 at {c:.0%} mean confidence. {q} API queries in "
            "{s:.1f}s. {e} weather-enriched, {l} LLM-written notes.".format(
                n=stats.get("submission_count", "?"), ok=stats.get("in_appetite", "?"),
                bad=stats.get("disqualified", "?"), m=stats.get("mean_score", "?"),
                c=stats.get("mean_confidence", 0) or 0, q=stats.get("api_queries", "?"),
                s=(stats.get("elapsed_ms", 0) or 0) / 1000,
                e=stats.get("enriched", 0), l=stats.get("llm_explanations", 0),
            )
        )

    if payload.get("tab"):
        out.append(f"The user is looking at the {payload['tab']} view.")

    sub = payload.get("submission")
    if sub:
        lines = [
            f"SELECTED SUBMISSION -- {sub.get('account_name')} "
            f"({sub.get('submission_number')}), rank {sub.get('rank')}, "
            f"score {sub.get('score')}/100 at {(sub.get('confidence') or 0):.0%} confidence, "
            f"recommendation '{sub.get('recommendation')}'.",
            f"Line {sub.get('line_of_business')}, status {sub.get('status')}, "
            f"state {sub.get('primary_risk_state')}, TIV {sub.get('tiv')}, "
            f"premium {sub.get('premium')} ({sub.get('premium_basis') or 'no prior term'}), "
            f"5-year loss {sub.get('five_year_loss')} ({sub.get('five_year_loss_basis')}).",
            "Factors:",
        ]
        for f in sub.get("factors") or []:
            lines.append(f"  - {f['label']}: {f['grade'].upper()} "
                         f"{f['points']}/{f['max_points']} -- {f['detail']}")
        if sub.get("disqualifiers"):
            lines.append("Hard stops: " + "; ".join(sub["disqualifiers"]))
        if sub.get("contradictions"):
            lines.append("Contradictions: " + " ".join(sub["contradictions"]))
        if sub.get("enrichment"):
            e = sub["enrichment"]
            lines.append(f"Weather: {e.get('summary')} Adjustment {e.get('adjustment')}, "
                         f"base score {sub.get('base_score')}.")
        lines.append(f"Note shown to the underwriter ({sub.get('explanation_source')}): "
                     f"{sub.get('explanation')}")
        out.append("\n".join(lines))

    steps = (payload.get("trace") or {}).get("steps") or []
    if steps:
        rows = ["REASONING TRACE FROM THIS RUN:"]
        for i, s in enumerate(steps[:MAX_TRACE_STEPS], 1):
            rows.append(f"{i}. {s.get('goal')} -- {s.get('rationale')}")
            if s.get("payload"):
                rows.append(f"   query: {s['payload']}")
            if s.get("outcome"):
                rows.append(f"   result: {s['outcome']}")
            if s.get("adaptation"):
                rows.append(f"   adapted: {s['adaptation']}")
        for note in (payload.get("trace") or {}).get("notes") or []:
            rows.append(f"note: {note}")
        out.append("\n".join(rows))

    out.append("FACTOR WEIGHTS: " + _weights())
    return "\n\n".join(out)


def answer(question: str, payload: dict) -> dict:
    if not LLM_ENABLED:
        raise MetaError(
            "This needs an Anthropic key. Add ANTHROPIC_API_KEY to .env and restart. "
            "The ? button beside the tabs shows the same reasoning without one."
        )
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=900,
        system="\n\n".join([SYSTEM, ARCHITECTURE]),
        messages=[{
            "role": "user",
            "content": f"{_context(payload)}\n\n---\n\nQuestion: {question}",
        }],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    return {"answer": text or "No answer was produced.", "model": ANTHROPIC_MODEL}
