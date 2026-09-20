"""Natural-language query loop.

This is the part where a model, rather than a rule, decides what to fetch.

A question arrives in English. The model is handed the schema the agent discovered
at runtime, the query language, and the carrier's appetite rules, and then it
plans: it writes a query payload, sees what comes back, and decides whether to
refine, widen, follow a reference, or answer. It can also hand a slice of the
queue to the deterministic scorer rather than judging appetite itself.

The division of labour is deliberate, and there are three roles rather than one.

The *planner* — the model in this loop — decides what to ask, and states with
each query the hypothesis it is testing: what it expects to find and why that
bears on the appetite decision. The *executor* is `QueryPlanner.run`, which is
deterministic and spends no tokens: it validates, repairs a bad field path and
broadens an empty result before the planner ever sees the outcome. The *critic*
(`critic.py`) is a separate call that reads the hypothesis against what actually
came back and returns a verdict, which goes into the trace and back to the
planner as the reason to query again or move on.

Splitting the critic out is the point. One model holding its own hypothesis and
its own results grades itself generously, and "I have enough" becomes
indistinguishable from "I have run out of ideas". A second call with a narrow
brief has no such stake.

The *scoring engine* still decides what a submission is worth, so scores stay
reproducible and auditable no matter what any of the three do. Every call lands
in the same reasoning trace.
"""
from __future__ import annotations

import json
from typing import Any

from ..config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL, CRITIC_ENABLED, LLM_ENABLED
from ..federato.client import FederatoError
from . import appetite, critic
from .dossier import CLOSED_STATUSES, OPEN_STATUSES
from .planner import QueryPlanner
from .trace import Trace

MAX_TURNS = 8          # tool round trips before the loop is cut off
PLAN_MAX_TOKENS = 2000   # a planning turn only has to emit one tool call
ANSWER_MAX_TOKENS = 8000  # prose over the whole book runs long; see _final_answer
MAX_ROWS_TO_MODEL = 20  # rows returned per query; totals are always exact


QUERY_LANGUAGE = """\
QUERY LANGUAGE (Mongo-flavoured). Payload keys, applied in this order:

  where     filter raw records (runs BEFORE references are expanded)
  expand    hydrate references, e.g. {"insured": true} or nested
            {"exposure_units": {"location": {"buildings": true}}}
  unwind    fan arrays into rows: ["exposure_units"]
  filter    filter AFTER expansion -- the only place a path through an
            expanded reference works, e.g. {"policy.insured": {"$in": [1,2]}}
  over      group by, e.g. ["line_of_business"]
  select    projection: ["a","b"] or {"a": true}, aggregations
            {"total": {"$sum": "premium"}}, {"n": {"$count": true}},
            {"k": {"$countDistinct": "id"}}
  sort      [{"field": "premium", "direction": "desc"}]
  pagination {"limit": 50, "offset": 0}

Only `resource` is required.

Operators: $eq $ne $exists $gt $gte $lt $lte $in $nin $contains $elemMatch,
combined with $and / $or / $not. Several keys in one clause imply $and.

THREE RULES THAT DECIDE WHETHER A QUERY WORKS:
1. Dot-paths do NOT cross arrays. Use $elemMatch to break at the boundary.
2. `where` runs before expansion, `filter` after. A clause on an expanded
   reference (policy.insured) MUST go in `filter` or it matches nothing.
3. A reference field holds an id, not the record. Expand it to read its fields.

KNOWN DEPLOYMENT QUIRK: the `over` stage does not collapse groups here -- `id`
stays in the partition key, so grouped queries return one row per record.
Aggregate in your own head from the rows instead of trusting a group total."""


APPETITE_BRIEF = f"""\
CARRIER APPETITE (2025 commercial property), for context when a question is
about fit. Do not score by hand -- call score_submissions, which applies this
table exactly and returns auditable scorecards.

  Line of business  property only (hard stop)
  Primary risk state  target {', '.join(sorted(appetite.TARGET_STATES))};
                      also acceptable {', '.join(sorted(appetite.ACCEPTABLE_STATES - appetite.TARGET_STATES))} (hard stop outside)
  TIV               target $50M-$100M, acceptable to $150M
  Premium           target $75K-$100K, acceptable $50K-$175K
  Loss history      under $100K incurred over 5 years
  Construction      >50% of insured value in non-combustible classes
  Building age      newer than 1990, target 2010+

Queue statuses: open = {', '.join(OPEN_STATUSES)}; closed = {', '.join(CLOSED_STATUSES)}."""


SYSTEM = """You are the query-planning half of an underwriting agent. An \
underwriter asks you a question in English; you answer it from the carrier's \
live data by deciding which queries to run.

You have the schema below. It was discovered at runtime -- it is the truth \
about what exists. Never guess a field name that is not in it.

HOW TO WORK:
- Plan before you query. Say which resource holds the answer and how you will \
reach it, then call run_query.
- State a hypothesis with every query: what you expect the data to show, \
concretely enough to be wrong, and why it matters for the decision. "Most of \
the CA property queue sits above $50M TIV, which would put it in target band" \
is a hypothesis. "Get TIV data" is not.
- A verifier checks each result against the hypothesis you stated and reports \
back. Take its verdict seriously: `insufficient` means query again for what it \
says is missing; `contradicted` means your premise was wrong, so revise it \
rather than re-running the same shape. Do not argue with it, and do not repeat \
a query it has already judged thin.
- Start narrow, then widen. If a query returns nothing, the usual causes are a \
dot-path through an array, a clause that belongs in `filter` rather than \
`where`, or a filter that is simply too tight.
- Follow references with `expand` instead of issuing one query per row.
- Totals in a result are exact even when the rows are truncated. Use the total \
for counts; do not count truncated rows and report that as the answer.
- For anything about appetite, fit, ranking or which submissions to work \
first, call score_submissions. It runs the carrier's own weighted table and \
returns scores, recommendations and per-factor reasoning. Do not invent your \
own scoring.
- Four or five queries is plenty for most questions. Stop when you can answer.

HOW TO ANSWER:
Lead with the answer, in the underwriter's language. Give the numbers you \
actually retrieved. Name the submissions or accounts involved. If the data \
could not answer part of the question, say which part and why rather than \
filling the gap. No preamble, no restating the question, no markdown headings."""


TOOLS = [
    {
        "name": "run_query",
        "description": (
            "Run one query against the carrier's database and return the "
            "matching records. Read-only. Rows are truncated but `total` is "
            "always the exact match count."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "description": (
                        "The query body. `resource` is required; where, expand, "
                        "unwind, filter, over, select, sort and pagination are "
                        "optional."
                    ),
                },
                "why": {
                    "type": "string",
                    "description": (
                        "One sentence: what this query is for and why this "
                        "shape. Shown to the underwriter in the reasoning trace."
                    ),
                },
                "hypothesis": {
                    "type": "string",
                    "description": (
                        "What you expect this query to show, stated concretely "
                        "enough to be wrong, and why it matters for the "
                        "appetite decision. A verifier will check the result "
                        "against this and report back, and the underwriter "
                        "sees it in the trace next to what actually came back."
                    ),
                },
            },
            "required": ["payload", "why", "hypothesis"],
        },
    },
    {
        "name": "score_submissions",
        "description": (
            "Score and rank a slice of the submission queue against the "
            "carrier's appetite guidelines. Returns per-submission scores, "
            "recommendations, confidence and the factor breakdown behind each "
            "one. Use this for any question about appetite fit, priority or "
            "which submissions to work first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "statuses": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Submission statuses to include. Defaults to the open "
                        f"queue ({', '.join(OPEN_STATUSES)})."
                    ),
                },
                "line_of_business": {
                    "type": "string",
                    "description": "Optional single line to filter to, e.g. 'property'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many ranked submissions to return. Default 10.",
                },
            },
        },
    },
]


class AskError(RuntimeError):
    pass


class AskSession:
    """One question, one tool-calling loop, one answer."""

    def __init__(self, agent, max_turns: int = MAX_TURNS):
        self.agent = agent
        self.max_turns = max_turns
        self._scored: dict[tuple, list[dict]] = {}

    # ---- tools ---------------------------------------------------------

    def _run_query(self, planner: QueryPlanner, payload: dict, why: str,
                   hypothesis: str | None = None) -> dict:
        """Execute a model-written query through the agent's adaptive runner."""
        if not isinstance(payload, dict) or "resource" not in payload:
            return {"error": "payload must be an object with a `resource` key."}

        resource = payload["resource"]
        if resource not in planner.schema:
            return {
                "error": f"Unknown resource {resource!r}.",
                "known_resources": planner.schema.resource_names(),
            }

        # Check field paths before spending a round trip, and hand back the
        # schema's own hint so the model can correct itself on the next turn.
        warnings = []
        for clause in ("where", "filter"):
            body = payload.get(clause)
            if isinstance(body, dict):
                for key in body:
                    if key.startswith("$"):
                        continue
                    ok, hint = planner.schema.validate_path(resource, key)
                    # A `filter` clause legitimately reaches through expanded
                    # references, which the raw resource schema cannot see.
                    if not ok and not (clause == "filter" and "." in key):
                        warnings.append(f"{clause}.{key}: {hint}")

        try:
            data = planner.run(
                payload,
                goal=why,
                rationale="Chosen by the model to answer the question.",
                hypothesis=hypothesis,
            )
        except FederatoError as exc:
            return {"error": exc.raw, "hint": "Check the field paths against the schema."}

        rows = data.get("results") or data.get("groups") or []
        out: dict[str, Any] = {
            "total": data.get("total", len(rows)),
            "returned": min(len(rows), MAX_ROWS_TO_MODEL),
            "rows": rows[:MAX_ROWS_TO_MODEL],
        }
        if len(rows) > MAX_ROWS_TO_MODEL:
            out["note"] = (
                f"{len(rows)} rows matched; {MAX_ROWS_TO_MODEL} shown. "
                f"`total` is exact -- use it for counts, or narrow the query."
            )
        if warnings:
            out["warnings"] = warnings
        return out

    def _score(self, statuses: list[str] | None, lob: str | None, limit: int) -> dict:
        """Hand a slice of the queue to the deterministic scorer."""
        key = (tuple(statuses or OPEN_STATUSES), lob)
        if key not in self._scored:
            result = self.agent.triage(
                statuses=statuses or OPEN_STATUSES,
                line_of_business=lob,
                enrich=False,      # the model's loop should stay fast
                use_llm=False,     # notes are written once, at the end
            )
            self._scored[key] = result.submissions
        rows = self._scored[key]

        return {
            "total": len(rows),
            "returned": min(len(rows), limit),
            "submissions": [
                {
                    "rank": r["rank"],
                    "score": r["score"],
                    "submission_number": r["submission_number"],
                    "account": r["account_name"],
                    "line_of_business": r["line_of_business"],
                    "status": r["status"],
                    "state": r["primary_risk_state"],
                    "tiv": r["tiv"],
                    "premium": r["premium"],
                    "five_year_loss": r["five_year_loss"],
                    "recommendation": r["recommendation"],
                    "confidence": r["confidence"],
                    "disqualifiers": r["disqualifiers"],
                    "factors": [
                        {"label": f["label"], "grade": f["grade"], "detail": f["detail"]}
                        for f in r["factors"]
                    ],
                }
                for r in rows[:limit]
            ],
        }

    def _verify(self, client, trace: Trace, question: str, hypothesis: str,
                payload: dict, result: dict) -> dict | None:
        """Ask the critic whether this result bore out the stated hypothesis.

        The verdict is written onto the step the executor actually finished on
        -- after any repair or broaden, which is a different step from the one
        the query started as -- and returned so it can be fed back to the
        planner.
        """
        if not CRITIC_ENABLED or not hypothesis or "error" in result:
            return None

        verification = critic.verify(client, question, hypothesis, payload, result)
        step = trace.last_query_step()
        if step is not None:
            step.verification = verification
        return verification

    def _final_answer(self, client, system, messages: list[dict], nudge: str):
        """Ask for the prose answer with the tools withheld.

        Two things make this different from a planning turn: the whole budget
        goes to text because no tool call can consume it, and the nudge is
        merged into the trailing user turn rather than appended after it, since
        two user messages in a row are rejected and the conversation usually
        ends on the tool results.
        """
        convo = list(messages)
        if convo and convo[-1]["role"] == "user":
            content = convo[-1]["content"]
            merged = (
                content + "\n\n" + nudge if isinstance(content, str)
                else [*content, {"type": "text", "text": nudge}]
            )
            convo[-1] = {"role": "user", "content": merged}
        else:
            convo.append({"role": "user", "content": nudge})
        return client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANSWER_MAX_TOKENS,
            system=system,
            messages=convo,
        )

    # ---- the loop ------------------------------------------------------

    def ask(self, question: str) -> dict:
        if not LLM_ENABLED:
            raise AskError(
                "Asking questions needs an Anthropic key. Add ANTHROPIC_API_KEY to "
                ".env and restart. The ranked queue and its explanations work without one."
            )
        import anthropic

        trace = Trace()
        schema = self.agent.schema(trace)
        planner = QueryPlanner(self.agent.client, schema, trace)
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        system = "\n\n".join([
            SYSTEM,
            QUERY_LANGUAGE,
            APPETITE_BRIEF,
            "SCHEMA (discovered at runtime):\n" + schema.summarize(),
        ])

        messages: list[dict] = [{"role": "user", "content": question}]
        turns = 0
        truncated = False
        verdicts: list[str] = []

        while True:
            resp = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=PLAN_MAX_TOKENS,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            if resp.stop_reason == "max_tokens":
                # The turn was cut mid-sentence, so whatever text it holds is a
                # fragment and any tool_use block in it is incomplete. Ask again
                # for the answer alone rather than shipping the fragment.
                trace.note(
                    "The model's turn hit its token ceiling, so the answer was "
                    "rewritten from the queries already run."
                )
                resp = self._final_answer(client, system, messages, (
                    "Answer the question now, in full, from what you have already "
                    "retrieved. Do not run further queries."
                ))
                break
            if resp.stop_reason != "tool_use":
                break

            turns += 1
            if turns > self.max_turns:
                truncated = True
                trace.note(
                    f"Stopped after {self.max_turns} tool calls. The answer below is "
                    f"based on what had been retrieved by then."
                )
                # Let the model write a final answer from what it has.
                messages.append({"role": "assistant", "content": resp.content})
                resp = self._final_answer(client, system, messages, (
                    "You have reached the query limit. Answer now from what you have "
                    "retrieved, and say plainly which part of the question you could "
                    "not get to."
                ))
                break

            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                if block.name == "run_query":
                    query = block.input.get("payload") or {}
                    hypothesis = block.input.get("hypothesis") or ""
                    payload = self._run_query(
                        planner,
                        query,
                        block.input.get("why") or "Model-chosen query.",
                        hypothesis=hypothesis,
                    )
                    verification = self._verify(
                        client, trace, question, hypothesis, query, payload)
                    if verification:
                        verdicts.append(verification["verdict"])
                        # The verdict rides back on the tool result, so the
                        # planner reads it as part of what it got rather than
                        # as a separate instruction.
                        payload["verification"] = critic.as_feedback(verification)
                elif block.name == "score_submissions":
                    step = trace.step(
                        goal="Score a slice of the queue",
                        rationale=("The model handed appetite judgement to the "
                                   "deterministic scorer rather than grading by hand."),
                    )
                    payload = self._score(
                        block.input.get("statuses"),
                        block.input.get("line_of_business"),
                        int(block.input.get("limit") or 10),
                    )
                    step.outcome = f"{payload['total']} submissions scored."
                    step.result_count = payload["total"]
                else:
                    payload = {"error": f"Unknown tool {block.name!r}."}

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(payload, default=str),
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": results})

        answer = "".join(
            b.text for b in resp.content if getattr(b, "type", "") == "text"
        ).strip()

        return {
            "question": question,
            "answer": answer or "No answer was produced.",
            "trace": trace.as_dict(),
            "tool_calls": turns,
            "truncated": truncated,
            "verdicts": verdicts,
            "model": ANTHROPIC_MODEL,
        }
