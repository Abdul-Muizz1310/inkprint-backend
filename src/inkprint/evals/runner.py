"""Eval suite runner for inkprint.

``run_all`` invokes the real evaluators — :func:`evaluate_fingerprint_pairs`,
:func:`evaluate_tamper_tests`, and (unless skipped) :func:`evaluate_leak_probe`
— computes pass/fail from their output against the published targets, and
optionally writes a Markdown report. There are no hardcoded results: the numbers
come from running the suites over the checked-in datasets.

The evaluator callables are injectable purely as a *test seam* so the failure
path can be exercised without a live corpus or a doctored dataset; production
callers (``evals/run_evals.py``) always use the defaults.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inkprint.evals.fingerprint_eval import FingerprintEvalResult, evaluate_fingerprint_pairs
from inkprint.evals.leak_eval import LeakEvalResult, evaluate_leak_probe
from inkprint.evals.tamper_eval import TamperEvalResult, evaluate_tamper_tests

# Published acceptance targets (see evals/report.md and docs/specs).
FINGERPRINT_TARGET = 0.85  # SimHash-only baseline; combined system exceeds 0.90
LEAK_TP_TARGET = 18  # true positives out of 20
LEAK_FP_LIMIT = 2  # max false positives out of 20


@dataclass
class EvalReport:
    """Result of running all eval suites."""

    exit_code: int = 0
    suites_run: list[str] = field(default_factory=list)
    results: dict[str, Any] = field(default_factory=dict)


def run_all(
    *,
    skip_live_cc: bool = False,
    output_path: Path | None = None,
    fingerprint_fn: Callable[[], FingerprintEvalResult] = evaluate_fingerprint_pairs,
    tamper_fn: Callable[[], TamperEvalResult] = evaluate_tamper_tests,
    leak_fn: Callable[[], LeakEvalResult] = evaluate_leak_probe,
) -> EvalReport:
    """Run all eval suites against the real evaluators and return a report.

    Args:
        skip_live_cc: Skip the leak-detection suite (it needs live Common Crawl).
        output_path: If set, write the report as Markdown here.
        fingerprint_fn / tamper_fn / leak_fn: Injectable evaluators (test seam).
    """
    report = EvalReport()

    fp = fingerprint_fn()
    report.suites_run.append("fingerprint")
    report.results["fingerprint"] = {
        "accuracy": round(fp.accuracy, 4),
        "correct": fp.correct,
        "total": fp.total,
    }
    if fp.accuracy < FINGERPRINT_TARGET:
        report.exit_code = 1

    tamper = tamper_fn()
    report.suites_run.append("tamper")
    report.results["tamper"] = {"rejected": tamper.rejected, "total": tamper.total}
    if tamper.rejected < tamper.total:
        report.exit_code = 1

    if not skip_live_cc:
        leak = leak_fn()
        report.suites_run.append("leak")
        report.results["leak"] = {
            "true_positives": leak.true_positives,
            "false_positives": leak.false_positives,
            "total_known": leak.total_known,
            "total_clean": leak.total_clean,
        }
        if leak.true_positives < LEAK_TP_TARGET or leak.false_positives > LEAK_FP_LIMIT:
            report.exit_code = 1

    if output_path is not None:
        _write_report(report, output_path)

    return report


def _write_report(report: EvalReport, path: Path) -> None:
    """Write eval report as markdown."""
    status = "PASS" if report.exit_code == 0 else "FAIL"
    lines = [
        "# Eval Report",
        "",
        f"Suites run: {', '.join(report.suites_run)}",
        f"Overall: {status}",
        "",
    ]
    for suite, results in report.results.items():
        lines.append(f"## {suite}")
        for k, v in results.items():
            lines.append(f"- {k}: {v}")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
