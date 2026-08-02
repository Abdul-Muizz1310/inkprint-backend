#!/usr/bin/env python
"""CLI entrypoint for the inkprint eval suites.

Runs the fingerprint, tamper, and (optionally) leak-detection evaluators over
the checked-in datasets, writes a generated report, and exits non-zero if any
suite misses its published target.

    uv run python evals/run_evals.py                 # all suites (needs live CC)
    uv run python evals/run_evals.py --skip-live-cc  # offline: fingerprint + tamper
    uv run python evals/run_evals.py -o somewhere.md # write the dump elsewhere

The default output is ``evals/last-run.md``, **not** ``evals/report.md`` (spec 06,
TC-E-14). ``report.md`` is hand-authored: it records what is measured versus
deferred and why — that the combined SimHash + embedding number was never
measured, and that leak detection awaits live Common Crawl access. The generator
emits a terse metric dump, so defaulting here meant that running the very command
the README cites as the reproduction step deleted those caveats. Overwriting the
curated file is still possible, but only by asking for it explicitly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from inkprint.evals.runner import run_all

#: Hand-authored narrative report. Never a runner output.
CURATED_REPORT = Path(__file__).resolve().parent / "report.md"

#: Machine-generated dump of the most recent run.
GENERATED_REPORT = Path(__file__).resolve().parent / "last-run.md"


def default_output_path() -> Path:
    """Where a run with no ``-o`` writes. Must never be :data:`CURATED_REPORT`."""
    return GENERATED_REPORT


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
        default=default_output_path(),
        help=(
            "Path to write the generated Markdown report "
            f"(default: {GENERATED_REPORT.name}). Pointing this at report.md "
            "overwrites the hand-authored narrative report."
        ),
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
