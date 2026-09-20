"""HTTP surface for the underwriting agent.

A triage run costs roughly 7 API queries and 15 seconds, so results are cached
per parameter set and the UI refreshes explicitly rather than re-running the
agent on every render.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

from .agent.ask import AskError, AskSession
from .agent.meta import MetaError, answer as meta_answer
from .agent.dossier import CLOSED_STATUSES, OPEN_STATUSES
from .agent.pipeline import UnderwritingAgent
from .agent import appetite
from .config import ENRICHMENT_ENABLED, LLM_ENABLED
from .federato.client import FederatoError

app = FastAPI(
    title="Federato Underwriting Agent",
    description="Scores, ranks and explains a commercial submission queue.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5273", "http://127.0.0.1:5273"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent = UnderwritingAgent()
_cache: dict[tuple, Any] = {}
_lock = threading.Lock()


def _run(statuses: list[str] | None, lob: str | None, enrich: bool,
         use_llm: bool, refresh: bool) -> dict:
    key = (tuple(statuses or []), lob, enrich, use_llm)
    with _lock:
        if not refresh and key in _cache:
            return _cache[key]
    try:
        result = _agent.triage(statuses=statuses, line_of_business=lob,
                               enrich=enrich, use_llm=use_llm).as_dict()
    except FederatoError as exc:
        raise HTTPException(status_code=502, detail=f"Federato API: {exc.raw}") from exc
    with _lock:
        _cache[key] = result
    return result


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "llm_explanations": LLM_ENABLED,
        "enrichment": ENRICHMENT_ENABLED,
    }


@app.get("/api/guidelines")
def guidelines() -> dict:
    """The appetite table the agent scores against, as it is actually applied."""
    return {
        "factors": [
            {"key": f.key, "label": f.label, "weight": f.weight,
             "hard_stop": f.hard_stop, "requires": list(f.requires)}
            for f in appetite.FACTORS
        ],
        "max_points": appetite.MAX_POINTS,
        "thresholds": {
            "target_states": sorted(appetite.TARGET_STATES),
            "acceptable_states": sorted(appetite.ACCEPTABLE_STATES),
            "tiv_ceiling": appetite.TIV_CEILING,
            "tiv_target": appetite.TIV_TARGET,
            "premium_band": appetite.PREMIUM_BAND,
            "premium_target": appetite.PREMIUM_TARGET,
            "building_year_acceptable": appetite.BUILDING_YEAR_ACCEPTABLE,
            "building_year_target": appetite.BUILDING_YEAR_TARGET,
            "loss_limit": appetite.LOSS_LIMIT,
            "acceptable_construction": sorted(appetite.ACCEPTABLE_CONSTRUCTION),
        },
        "grade_points": {g.value: p for g, p in appetite.GRADE_POINTS.items()},
        "statuses": {"open": OPEN_STATUSES, "closed": CLOSED_STATUSES},
    }


@app.get("/api/schema")
def schema() -> dict:
    """The discovered data model, as the agent sees it."""
    idx = _agent.schema()
    return {
        "resources": {
            name: {
                path: {
                    "type": f.type,
                    "resource": f.resource,
                    "cardinality": f.cardinality,
                    "in_array": f.in_array,
                    "optional": f.optional,
                }
                for path, f in res.fields.items()
            }
            for name, res in idx.resources.items()
        }
    }


@app.get("/api/triage")
def triage(
    status: list[str] | None = Query(default=None,
                                     description="Submission statuses to include."),
    line_of_business: str | None = Query(default=None),
    enrich: bool = Query(default=ENRICHMENT_ENABLED),
    llm: bool = Query(default=LLM_ENABLED),
    refresh: bool = Query(default=False),
) -> dict:
    """Score, rank and explain the queue."""
    return _run(status, line_of_business, enrich, llm and LLM_ENABLED, refresh)


@app.get("/api/submissions/{submission_id}")
def submission(submission_id: int,
               status: list[str] | None = Query(default=None)) -> dict:
    """One submission's full scorecard, from the cached run."""
    data = _run(status, None, ENRICHMENT_ENABLED, LLM_ENABLED, False)
    for row in data["submissions"]:
        if row["submission_id"] == submission_id:
            return row
    raise HTTPException(status_code=404, detail=f"Submission {submission_id} not in this queue.")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/ask")
def ask(body: AskRequest) -> dict:
    """Answer a question about the book by planning and running queries.

    This is the one path where a model, not a rule, decides what to fetch.
    """
    try:
        return AskSession(_agent).ask(body.question.strip())
    except AskError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except FederatoError as exc:
        raise HTTPException(status_code=502, detail=f"Federato API: {exc.raw}") from exc


class HowRequest(BaseModel):
    """A question about the run on screen, plus what the user is looking at."""
    question: str = Field(min_length=3, max_length=500)
    tab: str | None = None
    submission_id: int | None = None
    statuses: list[str] | None = None


@app.post("/api/how")
def how(body: HowRequest) -> dict:
    """Explain how the agent produced what the user is looking at.

    Distinct from /api/ask: that plans queries against the book, this reads
    back the run already in memory -- its trace, stats and scorecards.
    """
    data = _run(body.statuses, None, ENRICHMENT_ENABLED, LLM_ENABLED, False)
    submission = None
    if body.submission_id is not None:
        submission = next(
            (r for r in data["submissions"] if r["submission_id"] == body.submission_id),
            None,
        )
    try:
        return meta_answer(body.question.strip(), {
            "tab": body.tab,
            "stats": data["stats"],
            "trace": data["trace"],
            "submission": submission,
        })
    except MetaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
