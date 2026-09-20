"""Export the full dataset behind the API to local JSON.

    python -m app.dump                 # -> data/
    python -m app.dump --out somewhere
    python -m app.dump --combined      # also write one dataset.json

Every resource is paged through to completion, so the files are the whole
dataset rather than a first page. The schema is written alongside it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ROOT
from .federato.client import FederatoClient, FederatoError

PAGE = 200


def fetch_all(client: FederatoClient, resource: str) -> list[dict]:
    """Page through one resource until every record is retrieved."""
    rows: list[dict] = []
    offset = 0
    total = None
    while True:
        data = client.query({
            "resource": resource,
            "pagination": {"limit": PAGE, "offset": offset},
            "sort": [{"field": "id"}],
        })
        batch = data.get("results") or []
        if total is None:
            total = data.get("total", len(batch))
        rows.extend(batch)
        offset += PAGE
        if not batch or len(rows) >= (total or 0):
            break
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dump", description="Export the API dataset to JSON.")
    ap.add_argument("--out", default=str(ROOT / "data"), help="Output directory.")
    ap.add_argument("--combined", action="store_true",
                    help="Also write a single dataset.json containing every resource.")
    ap.add_argument("--indent", type=int, default=2, help="JSON indent (0 for compact).")
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    indent = args.indent or None

    client = FederatoClient()
    try:
        schema = client.schema()
    except FederatoError as exc:
        print(f"Could not fetch schema: {exc.raw}", file=sys.stderr)
        return 1

    (out / "_schema.json").write_text(json.dumps(schema, indent=indent))
    print(f"_schema.json          {len(schema)} resources", file=sys.stderr)

    combined: dict[str, list[dict]] = {}
    for name in sorted(schema):
        try:
            rows = fetch_all(client, name)
        except FederatoError as exc:
            print(f"{name:<21} FAILED: {exc.raw}", file=sys.stderr)
            continue
        (out / f"{name}.json").write_text(json.dumps(rows, indent=indent))
        combined[name] = rows
        print(f"{name + '.json':<21} {len(rows):>4} records", file=sys.stderr)

    if args.combined:
        (out / "dataset.json").write_text(json.dumps(combined, indent=indent))
        total = sum(len(v) for v in combined.values())
        print(f"{'dataset.json':<21} {total:>4} records across {len(combined)} resources",
              file=sys.stderr)

    print(f"\nWrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
