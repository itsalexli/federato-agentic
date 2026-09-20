"""Reasoning trace.

Every query the agent runs is recorded with the goal that motivated it, the
rationale for its shape, and what came back. This is what lets an underwriter
(or a judge) answer "why did it ask for that?" rather than taking the ranking
on faith.
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

    def as_dict(self) -> dict:
        return {
            "goal": self.goal,
            "rationale": self.rationale,
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
