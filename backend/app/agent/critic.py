"""The critic half of the loop.

The planner states, before it queries, what it expects the data to show and why
that matters for the appetite decision. Something has to check whether the data
actually said that. Left to one model in one context, that check collapses into
the planning: a model that writes a hypothesis and then reads its own results
tends to find them satisfying, and "stop" becomes indistinguishable from "bored".

So the verdict is rendered by a separate call with a deliberately narrow brief.
It sees the hypothesis, the query that was run, and what came back -- not the
conversation, not the question's full history -- and answers one question: did
this bear the hypothesis out? Its verdict is both written into the trace, where
an underwriter can read expectation against outcome, and fed back to the planner
as the reason to query again or to move on.

The critic never writes a query and never scores a submission. It only judges
whether the ground gained was the ground claimed.
"""
from __future__ import annotations

import json
from typing import Any

from ..config import ANTHROPIC_MODEL

# The verdicts, and what each one means for the loop.
SATISFIED = "satisfied"        # hypothesis borne out; move on
INSUFFICIENT = "insufficient"  # right idea, not enough data; query again
CONTRADICTED = "contradicted"  # data says something else; rethink the approach

SYSTEM = """You verify one step of an underwriting agent's reasoning.

The planner stated a hypothesis -- what it expected a query to show and why that \
would matter -- then ran the query. You are shown the hypothesis, the query and \
the result. You judge one thing: did the result actually bear the hypothesis out?

Be strict and literal. Specifically:
- A query that returned rows is not automatically a success. If the hypothesis \
said "most CA property submissions exceed $50M TIV" and three rows came back, \
the hypothesis was not borne out -- it was under-evidenced.
- Zero rows is real evidence, not a failure. It may contradict the hypothesis \
outright, which is a finding worth having.
- Do not judge whether the underwriter's question was answered. That is the \
planner's job. Judge only this one expectation against this one result.
- Do not propose a query payload. Say what is still missing, in one sentence, \
and let the planner write the query.

Verdicts:
  satisfied      the result supports the hypothesis well enough to build on
  insufficient   the hypothesis still looks right but the data is too thin
  contradicted   the data points the other way, or the premise was wrong"""


VERDICT_TOOL = {
    "name": "record_verdict",
    "description": "Record the verification verdict for this reasoning step.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": [SATISFIED, INSUFFICIENT, CONTRADICTED],
                "description": "Whether the result bore out the stated hypothesis.",
            },
            "reasoning": {
                "type": "string",
                "description": (
                    "One or two sentences citing the actual numbers, comparing "
                    "what was expected against what came back. Shown to the "
                    "underwriter in the reasoning trace."
                ),
            },
            "next_step": {
                "type": "string",
                "description": (
                    "If the verdict is not `satisfied`, one sentence on what is "
                    "still missing. Empty when satisfied."
                ),
            },
        },
        "required": ["verdict", "reasoning"],
    },
}

MAX_RESULT_CHARS = 4000  # the critic needs the shape of the result, not all of it


def verify(client, question: str, hypothesis: str, payload: dict,
           result: dict, model: str = ANTHROPIC_MODEL) -> dict:
    """Judge one executed query against the hypothesis that motivated it.

    Returns `{"verdict", "reasoning", "next_step"}`. Never raises: a critic that
    fails is not a reason to lose the answer, so an error degrades to a
    `satisfied` verdict that says so, and the planner carries on as it does today.
    """
    evidence = json.dumps(result, default=str)
    if len(evidence) > MAX_RESULT_CHARS:
        evidence = evidence[:MAX_RESULT_CHARS] + " ...(truncated)"

    prompt = (
        f"The underwriter asked: {question}\n\n"
        f"HYPOTHESIS the planner stated before querying:\n{hypothesis}\n\n"
        f"QUERY it ran:\n{json.dumps(payload, default=str)}\n\n"
        f"RESULT:\n{evidence}\n\n"
        "Did the result bear out the hypothesis? Call record_verdict."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=500,
            system=SYSTEM,
            tools=[VERDICT_TOOL],
            tool_choice={"type": "tool", "name": "record_verdict"},
            messages=[{"role": "user", "content": prompt}],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_verdict":
                data: dict[str, Any] = dict(block.input or {})
                verdict = data.get("verdict")
                if verdict not in (SATISFIED, INSUFFICIENT, CONTRADICTED):
                    verdict = SATISFIED
                return {
                    "verdict": verdict,
                    "reasoning": data.get("reasoning") or "",
                    "next_step": data.get("next_step") or "",
                }
    except Exception as exc:  # noqa: BLE001 - see docstring
        return {
            "verdict": SATISFIED,
            "reasoning": f"Verification unavailable ({type(exc).__name__}); not blocking the answer.",
            "next_step": "",
        }

    return {"verdict": SATISFIED, "reasoning": "No verdict returned.", "next_step": ""}


def as_feedback(verification: dict) -> str:
    """Render a verdict as the line the planner sees on its next turn."""
    line = f"VERIFIER [{verification['verdict']}]: {verification['reasoning']}"
    if verification.get("next_step"):
        line += f" Still missing: {verification['next_step']}"
    return line
