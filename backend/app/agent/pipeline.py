"""The agent loop.

discover schema -> locate the data each appetite rule needs -> plan and run the
queries -> assemble a dossier per submission -> score -> enrich -> explain ->
rank. Every stage writes to a shared trace, so the ranking can be read
backwards to the queries that produced it.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from ..config import ENRICHMENT_ENABLED, LLM_ENABLED
from ..federato.client import FederatoClient, FederatoError
from ..federato.schema import SchemaIndex
from . import appetite
from .dossier import CLOSED_STATUSES, OPEN_STATUSES, DossierBuilder
from .enrich import WeatherEnricher
from .explain import explain
from .planner import REQUIREMENTS, QueryPlanner
from .trace import Trace

# Deepen the analysis only where it pays: enrichment costs an external round
# trip per location, so it goes to the submissions actually competing for the
# underwriter's attention.
DEEP_DIVE_TOP_N = 25


@dataclass
class TriageResult:
    submissions: list[dict]
    trace: dict
    stats: dict
    portfolio: dict

    def as_dict(self) -> dict:
        return {
            "submissions": self.submissions,
            "trace": self.trace,
            "stats": self.stats,
            "portfolio": self.portfolio,
        }


class UnderwritingAgent:
    def __init__(self, client: FederatoClient | None = None):
        self.client = client or FederatoClient()
        self._schema: SchemaIndex | None = None

    # ---- schema --------------------------------------------------------

    def schema(self, trace: Trace | None = None) -> SchemaIndex:
        """Discover the schema once per process and reuse it."""
        if self._schema is None:
            t0 = time.perf_counter()
            raw = self.client.schema()
            self._schema = SchemaIndex(raw)
            if trace:
                trace.step(
                    goal="Discover the data model",
                    rationale=(
                        "No field-by-field reference is published, so the agent asks the "
                        "API what exists before it asks for anything specific. Field "
                        "paths, reference targets and array boundaries all come from here."
                    ),
                    payload={"action": "schema"},
                    outcome=(f"{len(self._schema.resources)} resources: "
                             f"{', '.join(self._schema.resource_names())}"),
                    result_count=len(self._schema.resources),
                    duration_ms=int((time.perf_counter() - t0) * 1000),
                )
        return self._schema

    # ---- main entry point ----------------------------------------------

    def triage(self, statuses: list[str] | None = None,
               line_of_business: str | None = None,
               top_n: int = DEEP_DIVE_TOP_N,
               enrich: bool = ENRICHMENT_ENABLED,
               use_llm: bool = LLM_ENABLED) -> TriageResult:
        trace = Trace()
        schema = self.schema(trace)
        planner = QueryPlanner(self.client, schema, trace)

        planner.resolve_all(list(REQUIREMENTS))
        dossiers = DossierBuilder(planner, trace).build(statuses, line_of_business)
        if not dossiers:
            return TriageResult([], trace.as_dict(),
                                {"submission_count": 0}, {"by_state": []})

        scored = [(d, appetite.score(d)) for d in dossiers]
        scored.sort(key=lambda pair: pair[1].score, reverse=True)
        trace.step(
            goal="Score and rank the queue",
            rationale=(
                f"Each submission runs through all {len(appetite.FACTORS)} weighted "
                f"appetite factors. Hard stops on line of business and risk state cap "
                f"the score at 25 rather than zeroing it, so an out-of-footprint "
                f"account that is otherwise strong stays visible as a filing question."
            ),
            outcome=f"{len(scored)} submissions scored; top score {scored[0][1].score}.",
            result_count=len(scored),
        )

        weather_map = self._enrich(scored, top_n, enrich, trace)
        rows = self._write_up(scored, weather_map, top_n, use_llm, trace)
        rows.sort(key=lambda r: r["score"], reverse=True)
        # Flag repeat accounts: the same insured appearing twice in one queue is
        # something an underwriter wants to see, not a duplicate to hide.
        seen_accounts: dict[int, int] = {}
        for i, row in enumerate(rows, 1):
            row["rank"] = i
            iid = row.get("insured_id")
            if iid in seen_accounts:
                row["duplicate_account"] = True
                row["duplicate_of_rank"] = seen_accounts[iid]
            elif iid is not None:
                seen_accounts[iid] = i

        return TriageResult(
            submissions=rows,
            trace=trace.as_dict(),
            stats=self._stats(rows, trace),
            portfolio=self._portfolio(planner, trace),
        )

    # ---- stages --------------------------------------------------------

    def _enrich(self, scored: list[tuple[dict, Any]], top_n: int,
                enrich: bool, trace: Trace) -> dict[int, dict]:
        if not enrich:
            return {}
        enricher = WeatherEnricher(enabled=True)
        targets = [(d, c) for d, c in scored[:top_n] if d.get("locations")]
        if not targets:
            return {}

        def fetch(pair: tuple[dict, Any]) -> tuple[int, dict | None]:
            d, _ = pair
            # Locations are ordered by insured value, so this walks down from
            # the largest until one carries usable coordinates.
            for loc in d["locations"][:3]:
                risk = enricher.for_location(loc.get("latitude"), loc.get("longitude"))
                if risk:
                    out = risk.as_dict()
                    out["location_name"] = loc.get("name")
                    out["location_city"] = loc.get("city")
                    out["location_state"] = loc.get("state")
                    return d["submission_id"], out
            return d["submission_id"], None

        # Kept deliberately low: Open-Meteo is free and rate-limits bursts.
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(fetch, targets))

        out = {sid: risk for sid, risk in results if risk}
        moved = sum(1 for r in out.values() if r["adjustment"])
        trace.step(
            goal="Enrich the top of the queue with observed weather history",
            rationale=(
                f"Hazard tags say a site is exposed but not how hard it has actually "
                f"been hit. Open-Meteo's archive is keyless, so the top {top_n} "
                f"submissions get a 5-year severe-weather read at their primary "
                f"location. The adjustment is capped at +/-{5.0} points -- enough to "
                f"break ties between comparable risks, not enough to overturn the "
                f"carrier's own table."
            ),
            outcome=(f"{len(out)}/{len(targets)} locations resolved; "
                     f"{moved} had a non-zero adjustment."
                     + (f" Unavailable: {enricher.unavailable_reason}"
                        if enricher.unavailable_reason else "")),
            result_count=len(out),
        )
        return out

    def _write_up(self, scored: list[tuple[dict, Any]], weather_map: dict,
                  top_n: int, use_llm: bool, trace: Trace) -> list[dict]:
        rows: list[dict] = []
        llm_used = 0

        def build(idx_pair: tuple[int, tuple[dict, Any]]) -> dict:
            nonlocal llm_used
            idx, (d, card) = idx_pair
            weather = weather_map.get(d["submission_id"])
            base = card.score
            final = base
            if weather:
                final = max(0, min(100, round(base + weather["adjustment"])))
                # The note has to quote the number the underwriter sees, so the
                # enriched score goes in before the write-up is generated. The
                # recommendation stays on the base score: external weather is a
                # tiebreaker and does not get to change the carrier's call.
                card = replace(card, score=final)
            # Only the deep-dive slice gets an LLM write-up; the tail keeps the
            # deterministic note, which costs nothing and says the same things.
            wants_llm = use_llm and idx < top_n
            text, source = explain(d, card, weather, use_llm=wants_llm)
            if source == "llm":
                llm_used += 1
            payload = card.as_dict()
            payload["base_score"] = base
            payload["enrichment"] = weather
            return {
                **d,
                **payload,
                "score": final,
                "explanation": text,
                "explanation_source": source,
            }

        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(build, enumerate(scored)))

        trace.step(
            goal="Write the underwriter-facing note for each submission",
            rationale=(
                "Explanations are generated from the scorecard, not from the raw "
                "record, so a note can only cite a factor that was actually "
                "evaluated. The LLM rewrites the top of the queue; the tail keeps "
                "the deterministic text, and any LLM failure falls back to it."
                if use_llm else
                "No Anthropic key is set, so every note comes from the deterministic "
                "writer -- same facts, plainer prose."
            ),
            outcome=f"{len(rows)} notes written ({llm_used} by LLM, {len(rows) - llm_used} deterministic).",
            result_count=len(rows),
        )
        return rows

    def _portfolio(self, planner: QueryPlanner, trace: Trace) -> dict:
        """Portfolio concentration by state, for the 'already exposed?' question."""
        try:
            data = planner.run(
                planner.plan_portfolio_by_state(),
                goal="Measure existing portfolio concentration by state",
                rationale=(
                    "Appetite is not only about the submission. An account in a state "
                    "the book is already heavy in is worth less than the same account "
                    "somewhere the carrier has room."
                ),
            )
        except FederatoError as exc:
            trace.note(f"Portfolio rollup unavailable: {exc.raw}")
            return {"by_state": [], "unavailable": exc.raw}

        rows = data.get("results") or data.get("groups") or []
        total = data.get("total", len(rows))

        # The documented `over` stage keeps `id` in the partition key on this
        # deployment, so groups come back one row per policy. Detect that and
        # roll up client-side rather than reporting wrong numbers.
        collapsed = len(rows) < total
        if not collapsed:
            trace.note(
                "`over` did not collapse groups server-side (rows == total), so the "
                "state rollup was recomputed client-side. A policy is counted once "
                "per state it has exposure in, not once per unwound exposure unit, "
                "so a multi-state policy appears under each of its states."
            )
            agg: dict[str, dict] = {}
            seen: set[tuple[str, Any]] = set()
            for r in rows:
                state = (((r.get("exposure_units") or {}).get("location") or {})
                         .get("state"))
                pid = r.get("id")
                if not state or pid is None or (state, pid) in seen:
                    continue
                seen.add((state, pid))
                bucket = agg.setdefault(
                    state, {"state": state, "policies": 0, "premium": 0.0, "_accounts": set()})
                bucket["policies"] += 1
                bucket["premium"] += float(r.get("premium") or 0)
                if r.get("insured") is not None:
                    bucket["_accounts"].add(r["insured"])
            by_state = []
            for b in sorted(agg.values(), key=lambda x: x["premium"], reverse=True):
                b["accounts"] = len(b.pop("_accounts"))
                by_state.append(b)
        else:
            by_state = [
                {
                    "state": (((r.get("exposure_units") or {}).get("location") or {})
                              .get("state")),
                    "policies": r.get("policies"),
                    "accounts": r.get("accounts"),
                    "premium": r.get("premium"),
                }
                for r in rows
            ]

        grand = sum(s["premium"] for s in by_state) or 1.0
        for s in by_state:
            s["share"] = round(s["premium"] / grand, 4)
        return {"by_state": by_state, "server_side_grouping": collapsed}

    def _stats(self, rows: list[dict], trace: Trace) -> dict:
        recs: dict[str, int] = {}
        for r in rows:
            recs[r["recommendation"]] = recs.get(r["recommendation"], 0) + 1
        in_appetite = [r for r in rows if not r["disqualified"]]
        return {
            "submission_count": len(rows),
            "in_appetite": len(in_appetite),
            "disqualified": len(rows) - len(in_appetite),
            "recommendations": recs,
            "mean_score": round(sum(r["score"] for r in rows) / len(rows), 1) if rows else 0,
            "mean_confidence": round(
                sum(r["confidence"] for r in rows) / len(rows), 2) if rows else 0,
            "enriched": sum(1 for r in rows if r.get("enrichment")),
            "llm_explanations": sum(1 for r in rows if r["explanation_source"] == "llm"),
            "api_queries": trace.query_count,
            "elapsed_ms": trace.as_dict()["elapsed_ms"],
            "open_statuses": OPEN_STATUSES,
            "closed_statuses": CLOSED_STATUSES,
        }
