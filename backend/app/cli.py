"""Terminal front end.

    python -m app.cli                      # rank the open queue
    python -m app.cli --top 5 --verbose    # with full factor breakdowns
    python -m app.cli --trace              # show the agent's reasoning trace
    python -m app.cli --all --lob property # include bound/declined/lost
    python -m app.cli --json out.json      # machine-readable export
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent.dossier import CLOSED_STATUSES, OPEN_STATUSES
from .agent.pipeline import UnderwritingAgent
from .config import ENRICHMENT_ENABLED, LLM_ENABLED
from .federato.client import FederatoError

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, YELLOW, RED, BLUE, CYAN = (
    "\033[32m", "\033[33m", "\033[31m", "\033[34m", "\033[36m")

GRADE_COLOR = {"target": GREEN, "acceptable": BLUE,
               "unacceptable": RED, "unknown": YELLOW}
GRADE_MARK = {"target": "++", "acceptable": " +",
              "unacceptable": " x", "unknown": " ?"}


def _plain(text: str) -> str:
    return text if sys.stdout.isatty() else _strip(text)


def _strip(text: str) -> str:
    for code in (BOLD, DIM, RESET, GREEN, YELLOW, RED, BLUE, CYAN):
        text = text.replace(code, "")
    return text


def _money(v) -> str:
    if v is None:
        return "--"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"${v / 1_000_000:.1f}M"
    if abs(v) >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def _bar(score: int, width: int = 20) -> str:
    filled = round(width * score / 100)
    color = GREEN if score >= 70 else YELLOW if score >= 45 else RED
    return f"{color}{'#' * filled}{DIM}{'.' * (width - filled)}{RESET}"


def _wrap(text: str, width: int, indent: str) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return f"\n{indent}".join(lines)


def _ask(question: str) -> int:
    """Run the natural-language query loop and print what it did."""
    from .agent.ask import AskError, AskSession

    print(f"{DIM}Planning queries...{RESET}", file=sys.stderr)
    try:
        result = AskSession(UnderwritingAgent()).ask(question)
    except AskError as exc:
        print(f"{YELLOW}{exc}{RESET}", file=sys.stderr)
        return 1
    except FederatoError as exc:
        print(f"{RED}Federato API error:{RESET} {exc.raw}", file=sys.stderr)
        return 1

    out = ["", f"{BOLD}Q  {question}{RESET}", ""]
    out.append(_wrap(result["answer"], 92, "   "))
    out.append("")
    steps = [s for s in result["trace"]["steps"] if s["payload"] or s["result_count"] is not None]
    if steps:
        out.append(f"{DIM}{'-' * 60}{RESET}")
        out.append(f"{BOLD}Queries the model chose{RESET} "
                   f"{DIM}({result['tool_calls']} tool calls, {result['model']}){RESET}")
        out.append("")
        for i, s in enumerate(steps, 1):
            out.append(f"  {BOLD}{i}. {s['goal']}{RESET}")
            if s["payload"]:
                compact = json.dumps(s["payload"], separators=(",", ":"))
                if len(compact) > 200:
                    compact = compact[:197] + "..."
                out.append(f"     {CYAN}{compact}{RESET}")
            if s["outcome"]:
                out.append(f"     -> {s['outcome']}")
            if s["adaptation"]:
                out.append(f"     {YELLOW}adapted: {s['adaptation']}{RESET}")
            out.append("")
    if result["truncated"]:
        out.append(f"{YELLOW}Hit the query limit; the answer is partial.{RESET}")
    print(_plain("\n".join(out)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="underwriting-agent",
        description="Score, rank and explain a commercial submission queue.")
    ap.add_argument("--top", type=int, default=10, help="How many to print (default 10).")
    ap.add_argument("--lob", default=None, help="Filter to one line of business.")
    ap.add_argument("--all", action="store_true",
                    help="Include bound/declined/lost, not just the open queue.")
    ap.add_argument("--verbose", "-v", action="store_true", help="Full factor breakdown.")
    ap.add_argument("--trace", action="store_true", help="Print the reasoning trace.")
    ap.add_argument("--no-enrich", action="store_true", help="Skip external weather data.")
    ap.add_argument("--no-llm", action="store_true", help="Force deterministic explanations.")
    ap.add_argument("--json", metavar="PATH", help="Write the full result as JSON.")
    ap.add_argument("--ask", metavar="QUESTION",
                    help="Ask a question in plain English instead of ranking the queue.")
    args = ap.parse_args(argv)

    if args.ask:
        return _ask(args.ask)

    statuses = (OPEN_STATUSES + CLOSED_STATUSES) if args.all else OPEN_STATUSES
    print(f"{DIM}Discovering schema, planning queries, scoring queue...{RESET}", file=sys.stderr)

    try:
        result = UnderwritingAgent().triage(
            statuses=statuses,
            line_of_business=args.lob,
            enrich=ENRICHMENT_ENABLED and not args.no_enrich,
            use_llm=LLM_ENABLED and not args.no_llm,
        )
    except FederatoError as exc:
        print(f"{RED}Federato API error:{RESET} {exc.raw}", file=sys.stderr)
        return 1

    if args.json:
        with open(args.json, "w") as fh:
            json.dump(result.as_dict(), fh, indent=2)
        print(f"Wrote {args.json}", file=sys.stderr)

    out = []
    st, subs = result.stats, result.submissions
    out.append("")
    out.append(f"{BOLD}UNDERWRITING QUEUE{RESET}  "
               f"{st['submission_count']} submissions  |  "
               f"{GREEN}{st['in_appetite']} in appetite{RESET}  |  "
               f"{RED}{st['disqualified']} out{RESET}  |  "
               f"mean {st['mean_score']}/100 at {st['mean_confidence']:.0%} confidence")
    out.append(f"{DIM}{st['api_queries']} API queries, {st['elapsed_ms'] / 1000:.1f}s. "
               f"{st['llm_explanations']} LLM notes, {st['enriched']} weather-enriched.{RESET}")
    out.append("")

    for row in subs[:args.top]:
        head = (f"{BOLD}#{row['rank']:>2} {row['score']:>3}/100{RESET} {_bar(row['score'])} "
                f"{BOLD}{row['account_name'] or '(unnamed account)'}{RESET}")
        if row.get("duplicate_account"):
            head += f"  {YELLOW}[same account as #{row['duplicate_of_rank']}]{RESET}"
        out.append(head)
        out.append(
            f"     {DIM}{row['submission_number']} | {row['line_of_business']} | "
            f"{row['status']} | {row['primary_risk_state'] or '??'} | "
            f"TIV {_money(row['tiv'])} | premium {_money(row['premium'])} | "
            f"received {row['received_date']}{RESET}")
        out.append(f"     {CYAN}{row['recommendation'].replace('_', ' ').upper()}{RESET}"
                   f"{DIM} at {row['confidence']:.0%} confidence{RESET}")
        out.append(f"     {_wrap(row['explanation'], 92, '     ')}")

        if args.verbose:
            out.append("")
            for f in row["factors"]:
                color = GRADE_COLOR[f["grade"]]
                out.append(f"       {color}{GRADE_MARK[f['grade']]}{RESET} "
                           f"{f['label']:<22} {f['points']:>4.1f}/{f['max_points']:<4.0f} "
                           f"{DIM}{f['detail']}{RESET}")
            if row.get("enrichment"):
                e = row["enrichment"]
                out.append(f"       {BLUE} ~{RESET} {'Weather (external)':<22} "
                           f"{e['adjustment']:>+4.1f}      {DIM}{e['summary']} "
                           f"[{e['source']}]{RESET}")
        out.append("")

    if result.portfolio.get("by_state"):
        out.append(f"{BOLD}PORTFOLIO CONCENTRATION{RESET} {DIM}(bound + active premium by state){RESET}")
        for s in result.portfolio["by_state"][:8]:
            bar = "#" * round(30 * s["share"])
            out.append(f"  {s['state'] or '??':<3} {_money(s['premium']):>8} "
                       f"{s['share']:>6.1%} {DIM}{bar}{RESET}")
        out.append("")

    if args.trace:
        out.append(f"{BOLD}REASONING TRACE{RESET}")
        for i, step in enumerate(result.trace["steps"], 1):
            out.append(f"  {BOLD}{i}. {step['goal']}{RESET}")
            out.append(f"     {DIM}{_wrap(step['rationale'], 88, '     ')}{RESET}")
            if step["payload"]:
                compact = json.dumps(step["payload"], separators=(",", ":"))
                if len(compact) > 220:
                    compact = compact[:217] + "..."
                out.append(f"     {CYAN}{compact}{RESET}")
            if step["outcome"]:
                out.append(f"     -> {_wrap(step['outcome'], 88, '        ')}")
            if step["adaptation"]:
                out.append(f"     {YELLOW}adapted: {step['adaptation']}{RESET}")
            out.append("")
        for note in result.trace["notes"]:
            out.append(f"  {DIM}note: {_wrap(note, 88, '        ')}{RESET}")
        out.append("")

    print(_plain("\n".join(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
