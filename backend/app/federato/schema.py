"""Runtime schema discovery.

The challenge deliberately withholds a field-by-field reference, so the agent
learns the shape of the world by calling `action: "schema"` at startup. This
module turns that raw response into something the planner can interrogate:
which fields exist, which are references, which are arrays (and therefore need
$elemMatch rather than a dot-path), and how to get from resource A to B.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class FieldInfo:
    path: str
    type: str
    optional: bool = False
    resource: str | None = None      # set when type == "reference"
    cardinality: str | None = None   # "one" | "many"
    in_array: bool = False           # any array sits between root and here


@dataclass
class ResourceInfo:
    name: str
    fields: dict[str, FieldInfo] = field(default_factory=dict)

    def has(self, path: str) -> bool:
        return path in self.fields

    def references(self) -> dict[str, FieldInfo]:
        return {p: f for p, f in self.fields.items() if f.type == "reference"}


class SchemaIndex:
    """Flattened, queryable view of the schema response."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.resources: dict[str, ResourceInfo] = {}
        for name, body in raw.items():
            if not isinstance(body, dict):
                continue
            info = ResourceInfo(name=name)
            for f in _walk(body.get("fields", {})):
                info.fields[f.path] = f
            self.resources[name] = info

    # ---- lookups -------------------------------------------------------

    def __contains__(self, resource: str) -> bool:
        return resource in self.resources

    def __getitem__(self, resource: str) -> ResourceInfo:
        return self.resources[resource]

    def resource_names(self) -> list[str]:
        return sorted(self.resources)

    def field(self, resource: str, path: str) -> FieldInfo | None:
        res = self.resources.get(resource)
        return res.fields.get(path) if res else None

    def validate_path(self, resource: str, path: str) -> tuple[bool, str | None]:
        """Check a field path, with the array-traversal trap called out.

        Returns (ok, hint). A path that crosses an array boundary validates as
        False with a hint, because the API accepts it silently and then matches
        nothing -- the single most common way to lose an hour on this challenge.
        """
        res = self.resources.get(resource)
        if res is None:
            return False, f"Unknown resource {resource!r}. Known: {', '.join(self.resource_names())}"
        info = res.fields.get(path)
        if info is None:
            near = self.suggest(resource, path)
            hint = f"{resource} has no field {path!r}."
            if near:
                hint += f" Closest: {', '.join(near)}"
            return False, hint
        if info.in_array:
            root = path.split(".")[0]
            return False, (
                f"{path!r} traverses the array {root!r}. Dot-paths do not cross "
                f"arrays -- use {{'{root}': {{'$elemMatch': {{...}}}}}} or unwind it."
            )
        return True, None

    def suggest(self, resource: str, path: str, limit: int = 3) -> list[str]:
        """Cheap substring-overlap suggestions for a mistyped path."""
        res = self.resources.get(resource)
        if not res:
            return []
        leaf = path.split(".")[-1].lower()
        scored = []
        for cand in res.fields:
            cleaf = cand.split(".")[-1].lower()
            if leaf in cleaf or cleaf in leaf:
                scored.append((abs(len(cleaf) - len(leaf)), cand))
        return [c for _, c in sorted(scored)[:limit]]

    # ---- traversal -----------------------------------------------------

    def path_between(self, start: str, target: str, max_hops: int = 3) -> list[str] | None:
        """Shortest chain of reference fields from `start` to `target`."""
        routes = self.paths_between(start, target, max_hops)
        return routes[0] if routes else None

    def paths_between(self, start: str, target: str, max_hops: int = 3) -> list[list[str]]:
        """Every *minimal-length* reference route from `start` to `target`.

        Returning all of them matters: Policy reaches Building both through
        `insured.hq.buildings` and through `exposure_units.location.buildings`,
        and those are different buildings. Taking whichever one BFS happened to
        find first would silently drop half an account's footprint, so the
        planner expands them all.
        """
        if start == target:
            return [[]]
        routes: list[list[str]] = []
        best: int | None = None
        seen_at: dict[str, int] = {start: 0}
        q: deque[tuple[str, list[str]]] = deque([(start, [])])
        while q:
            res, trail = q.popleft()
            depth = len(trail)
            if depth >= max_hops or (best is not None and depth >= best):
                continue
            for fpath, finfo in self.resources.get(res, ResourceInfo(res)).references().items():
                nxt = finfo.resource
                if not nxt:
                    continue
                route = trail + [fpath]
                if nxt == target:
                    if best is None or len(route) < best:
                        best, routes = len(route), [route]
                    elif len(route) == best:
                        routes.append(route)
                    continue
                # Revisiting a resource is only worth it at an equal or shorter
                # depth, which is what keeps sibling routes alive.
                if seen_at.get(nxt, 99) >= len(route):
                    seen_at[nxt] = len(route)
                    q.append((nxt, route))
        return routes

    def expand_clause(self, chain: list[str]) -> dict:
        """Turn ['exposure_units', 'location', 'buildings'] into a nested expand."""
        clause: Any = True
        for part in reversed(chain):
            clause = {part: clause}
        return clause if isinstance(clause, dict) else {}

    def merge_expands(self, chains: list[list[str]]) -> dict:
        """Fold several reference routes into one expand stage.

        One query that walks every route beats one query per route.
        """
        merged: dict = {}
        for chain in chains:
            node = merged
            for i, part in enumerate(chain):
                last = i == len(chain) - 1
                existing = node.get(part)
                if last:
                    node[part] = existing if isinstance(existing, dict) else True
                else:
                    if not isinstance(existing, dict):
                        existing = {}
                    node[part] = existing
                    node = existing
        return merged

    def summarize(self, resources: list[str] | None = None) -> str:
        """Compact text rendering of the schema, for an LLM prompt."""
        names = resources or self.resource_names()
        lines = []
        for name in names:
            res = self.resources.get(name)
            if not res:
                continue
            lines.append(f"{name}:")
            for path, f in res.fields.items():
                if f.type == "reference":
                    lines.append(f"  {path} -> {f.resource} ({f.cardinality})")
                else:
                    tag = " [inside array]" if f.in_array else ""
                    lines.append(f"  {path}: {f.type}{tag}")
        return "\n".join(lines)


def _walk(fields: dict, prefix: str = "", in_array: bool = False) -> Iterator[FieldInfo]:
    """Flatten the nested schema into dotted paths, tracking array crossings."""
    for name, body in fields.items():
        if not isinstance(body, dict):
            continue
        path = f"{prefix}{name}"
        ftype = body.get("type", "unknown")
        optional = bool(body.get("optional"))

        if ftype == "reference":
            many = body.get("cardinality") == "many"
            yield FieldInfo(path, "reference", optional, body.get("resource"),
                            body.get("cardinality"), in_array)
            # A "many" reference is an array of ids; descending through it in a
            # dot-path is the same trap as any other array.
            del many
        elif ftype == "object":
            yield FieldInfo(path, "object", optional, in_array=in_array)
            yield from _walk(body.get("fields", {}), f"{path}.", in_array)
        elif ftype == "array":
            item = body.get("itemSchema") or {}
            yield FieldInfo(path, "array", optional, in_array=in_array)
            if item.get("type") == "object":
                yield from _walk(item.get("fields", {}), f"{path}.", True)
            elif item.get("type") == "reference":
                yield FieldInfo(f"{path}[]", "reference", optional,
                                item.get("resource"), "many", True)
        else:
            yield FieldInfo(path, ftype, optional, in_array=in_array)
