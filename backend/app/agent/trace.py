"""Reasoning trace.

Every query the agent runs is recorded with the goal that motivated it, the
rationale for its shape, and what came back. This is what lets an underwriter
(or a judge) answer "why did it ask for that?" rather than taking the ranking
on faith.

Two of those fields make the record falsifiable rather than merely explanatory.
A step may carry the `hypothesis` the planner stated *before* the query ran --
what it expected to find and why that would matter -- and the `verification` a
critic returned *after*, judging whether the result actually bore it out. Read
together they give expectation -> outcome -> verdict, which is auditable in a
way a rationale written alongside the answer is not.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Step:
    goal: str
    rationale: str
    payload: dict | None = None
    outcome: str = ""
    result_count: int | None = None
    duration_ms: int = 0
    adapted_from: dict | None = None
    adaptation: str | None = None
    error: str | None = None
    # Stated before the query ran: what the planner expected to learn.
    hypothesis: str | None = None
    # Returned after it ran: {"verdict", "reasoning", "next_step"}.
    verification: dict | None = None

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "rationale": self.rationale,
            "hypothesis": self.hypothesis,
            "verification": self.verification,
            "payload": self.payload,
            "outcome": self.outcome,
            "result_count": self.result_count,
            "duration_ms": self.duration_ms,
            "adapted_from": self.adapted_from,
            "adaptation": self.adaptation,
            "error": self.error,
        }


@dataclass
class Trace:
    steps: list[Step] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    _t0: float = field(default_factory=time.perf_counter)

    def step(self, goal: str, rationale: str, **kw: Any) -> Step:
        s = Step(goal=goal, rationale=rationale, **kw)
        self.steps.append(s)
        return s

    def note(self, text: str) -> None:
        self.notes.append(text)

    def last_query_step(self) -> Step | None:
        """The most recent step that actually ran a query.

        A repair or a broaden appends a *further* step, so the step a verdict
        belongs on is the last one carrying a payload -- not the one the caller
        started with, and not simply `steps[-1]`, which may be a bookkeeping
        step with no query behind it.
        """
        for s in reversed(self.steps):
            if s.payload is not None:
                return s
        return None

    @property
    def query_count(self) -> int:
        return sum(1 for s in self.steps if s.payload is not None)

    def as_dict(self) -> dict:
        return {
            "steps": [s.as_dict() for s in self.steps],
            "notes": self.notes,
            "query_count": self.query_count,
            "elapsed_ms": int((time.perf_counter() - self._t0) * 1000),
        }
