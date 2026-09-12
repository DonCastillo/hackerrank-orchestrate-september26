#!/usr/bin/env python3
"""Buy or Wait? — entry point.

    python code/main.py                      # full run -> ./output.csv
    python code/main.py --no-llm             # engine only, no network
    python code/main.py --limit 10           # first N requests
    python code/main.py --request-ids request_01 request_19
    python code/main.py --validate           # check an existing ./output.csv
    python code/main.py --score-samples      # diff engine vs dataset/sample_requests.csv

Usually invoked through ../bootstrap.py, which sets up the isolated venv first.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

# Make sibling modules importable regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import OUTPUT_COLUMNS, OUTPUT_CSV, ROOT  # noqa: E402
from loader import Dataset, Request, load_dataset  # noqa: E402


def _load_env() -> None:
    """Read ./.env into os.environ without overriding already-set variables."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    except ImportError:
        pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Buy or Wait? decision engine")
    p.add_argument("--no-llm", action="store_true",
                   help="skip message/image interpretation; deterministic engine only")
    p.add_argument("--limit", type=int, default=None, help="process only the first N requests")
    p.add_argument("--request-ids", nargs="+", default=None, help="process only these request_ids")
    p.add_argument("--output", type=Path, default=OUTPUT_CSV, help="output CSV path")
    p.add_argument("--validate", action="store_true", help="validate --output and exit")
    p.add_argument("--score-samples", action="store_true",
                   help="run the engine on sample_requests.csv and report mismatches")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def _select_requests(ds: Dataset, args: argparse.Namespace) -> list[Request]:
    reqs = ds.requests
    if args.request_ids:
        wanted = set(args.request_ids)
        reqs = [r for r in reqs if r.request_id in wanted]
    if args.limit is not None:
        reqs = reqs[: args.limit]
    return reqs


def run_engine(ds: Dataset, requests: list[Request], use_llm: bool, verbose: bool = False) -> dict:
    """Return {request_id: Decision} for the given requests."""
    from evidence import gather_amendments
    from explain import explain
    from planner import decide
    from state import build_state

    amendments = gather_amendments(ds, use_llm=use_llm)
    decisions = {}
    for i, req in enumerate(requests, 1):
        state = build_state(ds, req, amendments)
        decision = decide(ds, state)
        decision.decision_explanation = explain(state, decision)
        decisions[req.request_id] = decision
        if verbose:
            print(f"[{i}/{len(requests)}] {req.request_id}: "
                  f"{decision.affordability_status} / {decision.recommended_payment_method}")
    return decisions


def write_output(decisions: dict, requests: list[Request], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for req in requests:
            w.writerow(decisions[req.request_id].to_row())


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    _load_env()
    ds = load_dataset()

    if args.validate:
        from validate import validate_output
        problems = validate_output(ds, args.output)
        for p in problems:
            print("  -", p)
        print(f"{'VALID' if not problems else f'{len(problems)} problem(s)'}: {args.output}")
        return 0 if not problems else 1

    use_llm = not args.no_llm
    if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set; falling back to --no-llm (cached responses still apply).",
              file=sys.stderr)
        # evidence.py will still serve cached responses; only fresh calls are impossible.

    if args.score_samples:
        from score_samples import score_samples
        decisions = run_engine(ds, list(ds.samples), use_llm, args.verbose)
        matched, total, lines = score_samples(ds, decisions)
        for line in lines:
            print("  -", line)
        print(f"samples: {matched}/{total} columns match")
        return 0 if matched == total else 1

    requests = _select_requests(ds, args)
    decisions = run_engine(ds, requests, use_llm, args.verbose)
    write_output(decisions, requests, args.output)
    print(f"wrote {len(requests)} rows -> {args.output}")

    if not args.limit and not args.request_ids:
        from usage_report import write_usage_report
        write_usage_report(len(requests))
        print("wrote code/evaluation/usage_report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
