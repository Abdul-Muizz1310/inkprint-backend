#!/usr/bin/env python
"""CLI entrypoint for the inkprint eval suites.

Runs the fingerprint, tamper, and (optionally) leak-detection evaluators over
the checked-in datasets, writes ``evals/report.md``, and exits non-zero if any
suite misses its published target.

    uv run python evals/run_evals.py                 # all suites (needs live CC)
    uv run python evals/run_evals.py --skip-live-cc  # offline: fingerprint + tamper
    uv run python evals/run_evals.py -o evals/report.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inkprint.evals.runner import run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run inkprint eval suites.")
    parser.add_argument(
        "--skip-live-cc",
        action="store_true",
        help="Skip leak detection (requires live Common Crawl CDX access).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "report.md",
        help="Path to write the Markdown report.",
    )
    args = parser.parse_args(argv)

    report = run_all(skip_live_cc=args.skip_live_cc, output_path=args.output)

    print(f"Suites run: {', '.join(report.suites_run)}")
    for suite, results in report.results.items():
        print(f"  {suite}: {results}")
    print("PASS" if report.exit_code == 0 else "FAIL")
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
