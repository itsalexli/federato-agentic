"""Dossier assembly.

A submission on its own is thin: status, line of business, requested limit, a
broker and an insured. Every factor the appetite table scores on lives one or
two joins away. This module does what an underwriter does with a new
submission -- work the account rather than the piece of paper -- and folds the
result into one flat dict per submission that the scorer can read.

The route matters: open submissions have no bound policy, so premium, TIV,
construction and loss history all come from the *insured's* footprint and
prior terms, not from a policy attached to the submission.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from .planner import QueryPlanner
from .trace import Trace

# Statuses that mean "still in the queue, still actionable".
OPEN_STATUSES = ["received", "cleared", "quoted"]
CLOSED_STATUSES = ["bound", "declined", "lost"]

LOSS_LOOKBACK_YEARS = 5


def _five_years_ago(today: date | None = None) -> str:
    today = today or date.today()
    return (today - timedelta(days=365 * LOSS_LOOKBACK_YEARS)).isoformat()


class DossierBuilder:
    def __init__(self, planner: QueryPlanner, trace: Trace):
        self.planner = planner
        self.trace = trace

    # ---- fetch ---------------------------------------------------------

    def build(self, statuses: list[str] | None = None,
              line_of_business: str | None = None) -> list[dict]:
        statuses = statuses if statuses is not None else OPEN_STATUSES

        queue = self.planner.run(
            self.planner.plan_queue(statuses, line_of_business),
            goal="Pull the submission queue",
            rationale=(
                f"Start from the submissions an underwriter can still act on "
                f"({', '.join(statuses)}), newest first."
            ),
            broaden=[
                (self.planner.plan_queue(statuses), "Dropped the line-of-business filter."),
                (self.planner.plan_queue([]), "Dropped the status filter entirely."),
            ] if line_of_business else [
                (self.planner.plan_queue([]), "Dropped the status filter entirely."),
            ],
        )["results"]

        if not queue:
            self.trace.note("Queue came back empty even after broadening.")
            return []

        insured_ids = sorted({s["insured"] for s in queue if s.get("insured")})
        self.trace.note(
            f"{len(queue)} submissions across {len(insured_ids)} accounts. "
            "Account data is fetched in bulk rather than per submission, so the "
            "run costs a fixed handful of queries instead of one per row."
        )

        accounts = self._fetch_accounts(insured_ids)
        policies = self._fetch_policies(insured_ids)
        claims = self._fetch_claims(insured_ids)
        brokers = self._fetch_lookup("Broker", {s.get("broker") for s in queue})
        underwriters = self._fetch_lookup("Underwriter", {s.get("underwriter") for s in queue})

        return [
            self._assemble(s, accounts, policies, claims, brokers, underwriters)
            for s in queue
        ]

    def _fetch_accounts(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        rows = self.planner.run(
            self.planner.plan_accounts(ids),
            goal="Resolve the account behind each submission",
            rationale=(
                "Submission.insured is a reference. The account carries the HQ "
                "location, which is the fallback source of a primary risk state "
                "for an account with no bound property policy to inherit one from."
            ),
        )["results"]
        return {r["id"]: r for r in rows}

    def _fetch_policies(self, ids: list[int]) -> dict[int, list[dict]]:
        if not ids:
            return {}
        rows = self.planner.run(
            self.planner.plan_account_policies(ids),
            goal="Pull prior policies with their buildings hydrated",
            rationale=(
                "TIV, construction type and year built all live on Building, three "
                "reference hops from Policy (exposure_units -> location -> buildings). "
                "Expanding the whole chain in one query avoids an N+1 walk, and prior "
                "premium on the same line is the only premium signal an unquoted "
                "submission has."
            ),
        )["results"]
        out: dict[int, list[dict]] = defaultdict(list)
        for p in rows:
            iid = _ref_id(p.get("insured"))
            if iid is not None:
                out[iid].append(p)
        return out

    def _fetch_claims(self, ids: list[int]) -> dict[int, list[dict]]:
        if not ids:
            return {}
        since = _five_years_ago()
        rows = self.planner.run(
            self.planner.plan_account_claims(ids, since),
            goal=f"Pull {LOSS_LOOKBACK_YEARS}-year loss history per account",
            rationale=(
                "Claim has no insured field -- the link runs through Claim.policy. "
                "That clause has to run after the reference is hydrated, so it goes "
                "in `filter` rather than `where`, and the date cut-off stays in "
                "`where` where it can narrow the scan first."
            ),
        )["results"]
        out: dict[int, list[dict]] = defaultdict(list)
        for c in rows:
            pol = c.get("policy") or {}
            if not isinstance(pol, dict):
                continue
            iid = _ref_id(pol.get("insured"))
            if iid is None:
                continue
            # Carry the policy's line down onto the claim: loss history is only
            # meaningful against the line being underwritten.
            c["_line_of_business"] = pol.get("line_of_business")
            out[iid].append(c)
        return out

    def _fetch_lookup(self, resource: str, ids: set) -> dict[int, dict]:
        clean = sorted({i for i in ids if i is not None})
        if not clean:
            return {}
        rows = self.planner.run(
            {"resource": resource, "where": {"id": {"$in": clean}},
             "pagination": {"limit": len(clean)}},
            goal=f"Resolve {resource} names",
            rationale=f"{resource} is a reference on Submission; the queue needs names, not ids.",
        )["results"]
        return {r["id"]: r for r in rows}

    # ---- fold ----------------------------------------------------------

    def _assemble(self, sub: dict, accounts: dict, policies: dict, claims: dict,
                  brokers: dict, underwriters: dict) -> dict:
        iid = sub.get("insured")
        account = accounts.get(iid, {})
        prior = policies.get(iid, [])
        account_claims = claims.get(iid, [])
        lob = sub.get("line_of_business")

        buildings, locations = _collect_property(prior)
        # An account's HQ counts as known footprint even when no policy touches it.
        hq = account.get("hq")
        if isinstance(hq, dict):
            locations = _dedupe_by_id(locations + [hq])

        same_line = [p for p in prior if p.get("line_of_business") == lob]
        premium, premium_basis = _indicative_premium(same_line)
        loss_total, loss_count, loss_basis = _scored_loss(account_claims, lob, bool(same_line))
        account_loss, account_claim_count = _loss_summary(account_claims)

        return {
            # identity
            "submission_id": sub["id"],
            "submission_number": sub.get("submission_number"),
            "status": sub.get("status"),
            "received_date": sub.get("received_date"),
            "target_effective_date": sub.get("target_effective_date"),
            "requested_limit": sub.get("requested_limit"),
            "competitor": sub.get("competitor"),
            "decline_reason": sub.get("decline_reason"),
            "line_of_business": lob,
            # account
            "insured_id": iid,
            "account_name": account.get("name"),
            "entity_type": account.get("entity_type"),
            "annual_revenue": account.get("annual_revenue"),
            "employee_count": account.get("employee_count"),
            "year_founded": account.get("year_founded"),
            "naics_code": account.get("naics_code"),
            "broker_name": (brokers.get(sub.get("broker")) or {}).get("name"),
            "broker_tier": (brokers.get(sub.get("broker")) or {}).get("tier"),
            "underwriter_name": (underwriters.get(sub.get("underwriter")) or {}).get("name"),
            # scored facts
            "primary_risk_state": _primary_state(locations, buildings),
            "tiv": sum(b["tiv"] for b in buildings if b.get("tiv")) or None,
            "building_count": len(buildings) or None,
            "oldest_building_year": min((b["year_built"] for b in buildings
                                         if b.get("year_built")), default=None),
            "construction_mix": _construction_mix(buildings),
            "premium": premium,
            "premium_basis": premium_basis,
            "business_type": _business_type(same_line),
            "five_year_loss": loss_total,
            "five_year_claim_count": loss_count,
            "five_year_loss_basis": loss_basis,
            "account_five_year_loss": account_loss,
            "account_five_year_claim_count": account_claim_count,
            # provenance
            "duplicate_account": False,  # set by the pipeline once the queue is ranked
            "prior_policy_count": len(prior),
            "prior_policy_lines": sorted({p.get("line_of_business") for p in prior if p.get("line_of_business")}),
            "locations": _rank_locations(locations, buildings),
            "hazard_tags": sorted({t for loc in locations for t in (loc.get("hazard_tags") or [])}),
        }


# --- folding helpers --------------------------------------------------------

def _ref_id(value: Any) -> Any:
    """A reference is an id until it is expanded, then it is a record."""
    if isinstance(value, dict):
        return value.get("id")
    return value


def _dedupe_by_id(rows: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        rid = r.get("id")
        if rid is None or rid in seen:
            continue
        seen.add(rid)
        out.append(r)
    return out


def _collect_property(policies: list[dict]) -> tuple[list[dict], list[dict]]:
    """Walk hydrated policies down to unique buildings and locations.

    The walk is structural rather than path-based: the planner may expand
    several routes to Building in one query, so this recurses through whatever
    came back and recognises records by their fields. Deduplicated by id --
    the same building shows up under every policy that touches its location,
    and double-counting it would inflate TIV.
    """
    buildings: list[dict] = []
    locations: list[dict] = []

    def visit(node: Any, depth: int = 0) -> None:
        if depth > 8:
            return
        if isinstance(node, list):
            for item in node:
                visit(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        if _looks_like_building(node):
            buildings.append(node)
        elif _looks_like_location(node):
            locations.append(node)
        for value in node.values():
            if isinstance(value, (dict, list)):
                visit(value, depth + 1)

    visit(policies)
    return _dedupe_by_id(buildings), _dedupe_by_id(locations)


def _looks_like_building(node: dict) -> bool:
    return "id" in node and ("construction_type" in node or
                             ("tiv" in node and "year_built" in node))


def _looks_like_location(node: dict) -> bool:
    return "id" in node and "state" in node and ("zip" in node or "address" in node)


def _rank_locations(locations: list[dict], buildings: list[dict]) -> list[dict]:
    """Locations ordered by insured value, biggest first.

    Everything downstream treats locations[0] as *the* primary risk location --
    the state that gets scored, the coordinate that gets a weather lookup -- so
    the ordering has to mean something rather than being query order.
    """
    by_building = {b["id"]: b for b in buildings}
    out = []
    for loc in locations:
        tiv = 0.0
        for b in loc.get("buildings") or []:
            bid = b.get("id") if isinstance(b, dict) else b
            tiv += float((by_building.get(bid) or {}).get("tiv") or 0)
        out.append({
            **{k: loc.get(k) for k in
               ("id", "name", "city", "state", "zip", "latitude", "longitude",
                "hazard_tags", "protection_class")},
            "tiv": tiv or None,
        })
    return sorted(out, key=lambda x: x["tiv"] or 0, reverse=True)


def _primary_state(locations: list[dict], buildings: list[dict]) -> str | None:
    """The state carrying the most insured value, falling back to headcount.

    "Primary risk state" means where the exposure actually sits, so value wins
    over a simple majority of addresses.
    """
    if not locations:
        return None
    by_building = {b["id"]: b for b in buildings}
    value: Counter[str] = Counter()
    for loc in locations:
        st = loc.get("state")
        if not st:
            continue
        for b in loc.get("buildings") or []:
            bid = b.get("id") if isinstance(b, dict) else b
            tiv = (by_building.get(bid) or {}).get("tiv") or 0
            value[st] += tiv
    if value and max(value.values()) > 0:
        return value.most_common(1)[0][0]
    counts = Counter(loc["state"] for loc in locations if loc.get("state"))
    return counts.most_common(1)[0][0] if counts else None


def _construction_mix(buildings: list[dict]) -> dict[str, float]:
    """Construction types weighted by TIV, not by building count.

    The guideline says ">50% JM, non-combustible or masonry non-combustible".
    Weighting by value is the reading that matters to a property underwriter --
    ten sheds and one steel warehouse is not a frame risk.
    """
    mix: Counter[str] = Counter()
    for b in buildings:
        ctype = b.get("construction_type")
        if not ctype:
            continue
        mix[ctype] += b.get("tiv") or b.get("building_value") or 1
    return dict(mix)


def _indicative_premium(same_line_policies: list[dict]) -> tuple[float | None, str | None]:
    """Premium signal for a submission that has not been quoted.

    An open submission has no premium of its own. The most recent expiring term
    on the same line is what an underwriter actually anchors to, so that is
    what gets scored -- labelled as indicative so nobody reads it as a quote.
    """
    if not same_line_policies:
        return None, None
    def key(p: dict) -> str:
        return ((p.get("dates") or {}).get("effective")) or ""
    latest = max(same_line_policies, key=key)
    prem = latest.get("premium")
    if prem is None:
        return None, None
    return float(prem), (
        f"indicative: expiring {latest.get('line_of_business')} term "
        f"{latest.get('policy_number')} at {latest.get('status')}"
    )


def _business_type(same_line_policies: list[dict]) -> str | None:
    """New vs renewal, inferred from whether the account already has this line."""
    if not same_line_policies:
        return "new"
    return "renewal"


def _scored_loss(claims: list[dict], lob: str | None,
                 has_same_line: bool) -> tuple[float | None, int, str]:
    """The loss number the appetite rule should actually be applied to.

    An account's total incurred loss is the wrong input for a line-specific
    appetite rule. A medical group with $4.8M of health claims and a clean
    property record is not a $4.8M property risk. So when the account has
    written the same line before, only that line's losses are scored, and the
    account-wide figure is carried alongside for context.
    """
    if not claims:
        return 0.0, 0, "no claims on record for this account"
    if lob and has_same_line:
        same = [c for c in claims if c.get("_line_of_business") == lob]
        total, count = _loss_summary(same)
        return total, count, f"{lob} claims only; other lines shown separately"
    total, count = _loss_summary(claims)
    return total, count, "all lines -- no prior term on this line to isolate"


def _loss_summary(claims: list[dict]) -> tuple[float | None, int]:
    """Incurred loss = paid plus outstanding reserves.

    Scoring on paid alone would flatter an account whose large claims are still
    open, which is exactly the account you most want flagged.
    """
    if not claims:
        return 0.0, 0
    total = 0.0
    for c in claims:
        total += sum(float(c.get(k) or 0) for k in
                     ("paid_indemnity", "paid_expense",
                      "reserve_indemnity", "reserve_expense"))
    return total, len(claims)
