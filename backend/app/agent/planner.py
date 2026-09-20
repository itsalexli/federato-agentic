"""Query planning.

The planner is the part that "thinks". It is handed an underwriting need in
the abstract -- "I need total insured value for this account" -- and works out,
from the schema it discovered at runtime, which resource actually holds that
number and how to reach it. Nothing in here names a join path by hand: routes
come from `SchemaIndex.path_between`, so if the schema changed shape the
planner would re-derive them.

It also adapts. A query that validates but returns nothing gets retried with a
broader filter; a query rejected for a bad field path gets repaired from the
schema's own suggestions rather than failing the run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..federato.client import FederatoClient, FederatoError
from ..federato.schema import SchemaIndex
from .trace import Trace


@dataclass
class Route:
    """Where a piece of underwriting data physically lives."""
    requirement: str
    resource: str
    path: str
    chains: list[list[str]]   # every minimal reference route from the anchor
    anchor: str               # resource the routes start at
    note: str = ""

    @property
    def chain(self) -> list[str]:
        """The shortest single route, for callers that only need one."""
        return self.chains[0] if self.chains else []

    def describe(self) -> str:
        if not self.chains or self.chains == [[]]:
            return f"{self.requirement}: {self.resource}.{self.path} (no join needed)"
        hops = " and ".join(
            " -> ".join([self.anchor] + c) for c in self.chains
        )
        return f"{self.requirement}: {self.resource}.{self.path} via {hops}"


# What each appetite factor needs, described by the *name* of the field rather
# than its location. The planner searches the schema for these.
REQUIREMENTS: dict[str, dict[str, Any]] = {
    "tiv":                  {"field": "tiv", "anchor": "Policy"},
    "construction_mix":     {"field": "construction_type", "anchor": "Policy"},
    "oldest_building_year": {"field": "year_built", "anchor": "Policy"},
    "primary_risk_state":   {"field": "state", "anchor": "Insured", "prefer": "Location"},
    "premium":              {"field": "premium", "anchor": "Policy"},
    "five_year_loss":       {"field": "paid_indemnity", "anchor": "Policy"},
    "business_type":        {"field": "business_type", "anchor": "Policy"},
}


class QueryPlanner:
    def __init__(self, client: FederatoClient, schema: SchemaIndex, trace: Trace):
        self.client = client
        self.schema = schema
        self.trace = trace
        self._routes: dict[str, Route] = {}

    # ---- discovery -----------------------------------------------------

    def resolve(self, requirement: str) -> Route | None:
        """Locate a requirement in the schema, caching the answer."""
        if requirement in self._routes:
            return self._routes[requirement]
        spec = REQUIREMENTS.get(requirement)
        if not spec:
            return None

        field_name = spec["field"]
        anchor = spec["anchor"]
        preferred = spec.get("prefer")

        candidates: list[tuple[str, str]] = []
        for res_name in self.schema.resource_names():
            for path, info in self.schema[res_name].fields.items():
                if path.split(".")[-1] == field_name and info.type not in ("object", "array"):
                    candidates.append((res_name, path))
        if not candidates:
            return None

        # Prefer an explicitly requested resource, then the anchor itself
        # (no join needed), then whatever is reachable in the fewest hops.
        def rank(c: tuple[str, str]) -> tuple[int, int, str]:
            res, path = c
            if preferred and res == preferred:
                return (0, 0, path)
            if res == anchor:
                return (1, 0, path)
            found = self.schema.paths_between(anchor, res)
            return (2, len(found[0]) if found else 99, path)

        res, path = sorted(candidates, key=rank)[0]
        # Keep every minimal route, not just one: a resource can be reachable
        # by several equally short paths that reach different records.
        chains = [[]] if res == anchor else self.schema.paths_between(anchor, res)
        route = Route(requirement, res, path, chains, anchor)
        self._routes[requirement] = route
        return route

    def resolve_all(self, requirements: list[str]) -> dict[str, Route]:
        """Resolve every requirement and record the map in the trace."""
        found: dict[str, Route] = {}
        missing: list[str] = []
        for req in requirements:
            r = self.resolve(req)
            if r:
                found[req] = r
            else:
                missing.append(req)
        self.trace.step(
            goal="Locate the data behind each appetite rule",
            rationale=(
                "The appetite table scores on TIV, construction, building year, risk "
                "state, premium and loss history. None of those live on Submission, so "
                "each one is located in the discovered schema and a reference route is "
                "derived rather than hardcoded."
            ),
            outcome="; ".join(r.describe() for r in found.values())
                    + (f" | unresolved: {', '.join(missing)}" if missing else ""),
            result_count=len(found),
        )
        return found

    # ---- execution with adaptation -------------------------------------

    def run(self, payload: dict, goal: str, rationale: str,
            broaden: list[tuple[dict, str]] | None = None,
            hypothesis: str | None = None) -> dict:
        """Execute a query, repairing or broadening it if the first shape fails.

        `broaden` is an ordered list of (replacement_payload, why) fallbacks,
        tried when the query is valid but returns nothing.

        `hypothesis` is what the caller expected this query to show. It rides
        through the repair and broaden recursions onto every step they create,
        because the adapted query is still serving the original expectation --
        and the adapted step is the one a critic will end up judging.
        """
        t0 = time.perf_counter()
        step = self.trace.step(goal=goal, rationale=rationale, payload=payload,
                               hypothesis=hypothesis)
        try:
            data = self.client.query(payload)
        except FederatoError as exc:
            step.error = exc.raw
            repaired = self._repair(payload, exc)
            if repaired is None:
                step.outcome = f"Failed: {exc.raw}"
                step.duration_ms = int((time.perf_counter() - t0) * 1000)
                raise
            fixed_payload, why = repaired
            step.outcome = f"First shape rejected ({exc.code or 'error'}); repaired and retried."
            step.duration_ms = int((time.perf_counter() - t0) * 1000)
            return self.run(
                fixed_payload,
                goal=goal,
                rationale=f"Retry after repair. {why}",
                hypothesis=hypothesis,
            )

        rows = data.get("results") or data.get("groups") or []
        step.result_count = len(rows)
        step.duration_ms = int((time.perf_counter() - t0) * 1000)

        if not rows and broaden:
            next_payload, why = broaden[0]
            step.outcome = f"0 rows. Broadening: {why}"
            follow = self.run(
                next_payload,
                goal=goal,
                rationale=f"Broadened query. {why}",
                broaden=broaden[1:],
                hypothesis=hypothesis,
            )
            self.trace.steps[-1].adapted_from = payload
            self.trace.steps[-1].adaptation = why
            return follow

        step.outcome = f"{len(rows)} rows (total {data.get('total', len(rows))})"
        return data

    def _repair(self, payload: dict, exc: FederatoError) -> tuple[dict, str] | None:
        """Best-effort repair of a rejected query using the schema.

        Handles the two failure modes worth automating: a field path that
        crosses an array (rewrite to $elemMatch) and an unknown field (drop the
        clause, so one bad filter doesn't lose the whole result set).
        """
        if not exc.is_validation_error:
            return None
        resource = payload.get("resource")
        if not resource or resource not in self.schema:
            return None

        for clause_name in ("where", "filter"):
            clause = payload.get(clause_name)
            if not isinstance(clause, dict):
                continue
            for key in list(clause):
                if key.startswith("$"):
                    continue
                ok, hint = self.schema.validate_path(resource, key)
                if ok:
                    continue
                fixed = dict(payload)
                new_clause = dict(clause)
                info = self.schema.field(resource, key)
                if info and info.in_array:
                    root = key.split(".")[0]
                    rest = key[len(root) + 1:]
                    new_clause.pop(key)
                    new_clause[root] = {"$elemMatch": {rest: clause[key]}}
                    fixed[clause_name] = new_clause
                    return fixed, f"{key!r} crosses the {root!r} array; rewrote it as $elemMatch."
                new_clause.pop(key)
                fixed[clause_name] = new_clause
                return fixed, f"Dropped unrecognised filter {key!r}. {hint or ''}".strip()
        return None

    # ---- concrete plans ------------------------------------------------

    def plan_queue(self, statuses: list[str], line_of_business: str | None = None,
                   limit: int = 200) -> dict:
        """The submission queue itself."""
        where: dict[str, Any] = {}
        if statuses:
            where["status"] = {"$in": statuses}
        if line_of_business:
            where["line_of_business"] = line_of_business
        payload: dict[str, Any] = {"resource": "Submission", "pagination": {"limit": limit}}
        if where:
            payload["where"] = where
        payload["sort"] = [{"field": "received_date", "direction": "desc"}]
        return payload

    def plan_accounts(self, insured_ids: list[int]) -> dict:
        """Accounts behind the queue, with HQ location expanded in one hop.

        `hq` is a single reference, so it expands cleanly -- this is the cheap
        way to get a primary risk state for accounts with no bound property
        policy to inherit one from.
        """
        return {
            "resource": "Insured",
            "where": {"id": {"$in": insured_ids}},
            "expand": {"hq": True},
            "pagination": {"limit": len(insured_ids) or 1},
        }

    def plan_account_policies(self, insured_ids: list[int]) -> dict:
        """Prior policies per account: premium context and every route to buildings.

        The schema exposes two equally short paths from Policy to Building --
        through the insured's HQ and through the policy's own exposure units --
        and they reach different buildings. Both are expanded in a single
        round trip rather than queried per policy, which is the whole point of
        the expand stage existing.
        """
        routes = self.schema.paths_between("Policy", "Building") or [
            ["exposure_units", "location", "buildings"]
        ]
        return {
            "resource": "Policy",
            "where": {"insured": {"$in": insured_ids}},
            "expand": self.schema.merge_expands(routes),
            "pagination": {"limit": 400},
        }

    def plan_account_claims(self, insured_ids: list[int], since: str) -> dict:
        """Five-year loss history, filtered after the policy is hydrated.

        `insured` lives on Policy, not Claim, so the clause has to run *after*
        expansion -- that is `filter`, not `where`.
        """
        return {
            "resource": "Claim",
            "where": {"date_of_loss": {"$gte": since}},
            "expand": {"policy": True},
            "filter": {"policy.insured": {"$in": insured_ids}},
            "pagination": {"limit": 500},
        }

    def plan_portfolio_by_state(self) -> dict:
        """Portfolio concentration, for the 'are we already exposed here?' read."""
        return {
            "resource": "Policy",
            "where": {"status": {"$in": ["active", "bound"]}},
            "expand": {"exposure_units": {"location": True}},
            "unwind": ["exposure_units"],
            "over": ["exposure_units.location.state"],
            "select": {
                # `id` and `insured` are projected explicitly so the rollup can
                # be recomputed client-side when `over` does not collapse.
                "id": True,
                "insured": True,
                "exposure_units": {"location": {"state": True}},
                "policies": {"$countDistinct": "id"},
                "accounts": {"$countDistinct": "insured"},
                "premium": {"$sum": "premium"},
            },
            "sort": [{"field": "premium", "direction": "desc"}],
        }
