"""The eval CLI must not destroy the curated report — spec 06, TC-E-14..17.

``evals/report.md`` is hand-authored. It carries the parts no generator can
produce: that the combined SimHash + embedding accuracy was never measured, that
leak detection is deferred pending live Common Crawl access, and the reasoning
behind both. ``README.md`` cites ``uv run python evals/run_evals.py`` as the
reproduction command and links to that report two lines later.

The CLI used to default ``-o`` at ``evals/report.md``, so running exactly the
documented command replaced the caveats with a fifteen-line metric dump — the
honest report deleting itself the first time anyone followed the instructions.
The generated artifact now has its own path.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = REPO_ROOT / "evals"
CURATED_REPORT = EVALS_DIR / "report.md"

if str(EVALS_DIR) not in sys.path:
    sys.path.insert(0, str(EVALS_DIR))

run_evals = pytest.importorskip("run_evals")


GENERATED_REPORT = EVALS_DIR / "last-run.md"


@pytest.fixture(autouse=True)
def _generated_report_guard() -> Iterator[None]:
    """Leave no generated dump behind — these tests run the real CLI."""
    previous = GENERATED_REPORT.read_bytes() if GENERATED_REPORT.exists() else None
    try:
        yield
    finally:
        if previous is None:
            GENERATED_REPORT.unlink(missing_ok=True)
        else:
            GENERATED_REPORT.write_bytes(previous)


@pytest.fixture()
def curated_report_guard() -> Iterator[Path]:
    """Snapshot the curated report and restore it however the test ends."""
    original = CURATED_REPORT.read_bytes()
    try:
        yield CURATED_REPORT
    finally:
        CURATED_REPORT.write_bytes(original)


class TestDefaultRunPreservesTheCuratedReport:
    def test_tc_e_14_default_run_leaves_report_md_byte_identical(
        self, curated_report_guard: Path
    ) -> None:
        before = curated_report_guard.read_bytes()
        assert run_evals.main(["--skip-live-cc"]) == 0
        assert curated_report_guard.read_bytes() == before

    def test_tc_e_15_default_run_writes_the_generated_dump_elsewhere(
        self, curated_report_guard: Path
    ) -> None:
        assert run_evals.main(["--skip-live-cc"]) == 0
        assert GENERATED_REPORT.is_file()
        content = GENERATED_REPORT.read_text(encoding="utf-8").lower()
        assert "fingerprint" in content
        assert "pass" in content or "fail" in content

    def test_generated_dump_is_not_the_curated_report(self) -> None:
        """The two documents are different artifacts, not two names for one file."""
        assert run_evals.default_output_path() != CURATED_REPORT

    def test_curated_report_still_carries_the_caveats_after_a_run(
        self, curated_report_guard: Path
    ) -> None:
        """Guards the specific content a default run used to delete."""
        run_evals.main(["--skip-live-cc"])
        text = curated_report_guard.read_text(encoding="utf-8")
        assert "NOT MEASURED" in text
        assert "DEFERRED" in text


class TestExplicitOutputStillWorks:
    def test_tc_e_16_dash_o_writes_where_it_is_pointed(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "run.md"
        assert run_evals.main(["--skip-live-cc", "-o", str(target)]) == 0
        assert "fingerprint" in target.read_text(encoding="utf-8").lower()

    def test_tc_e_16b_dash_o_may_still_target_the_curated_report(
        self, curated_report_guard: Path
    ) -> None:
        """Explicit is fine; the fixture restores it. Only the *default* is safe."""
        assert run_evals.main(["--skip-live-cc", "-o", str(curated_report_guard)]) == 0
        assert "NOT MEASURED" not in curated_report_guard.read_text(encoding="utf-8")


class TestExitCode:
    def test_tc_e_17_exit_code_is_the_report_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from inkprint.evals.runner import EvalReport

        monkeypatch.setattr(
            run_evals,
            "run_all",
            lambda **_kwargs: EvalReport(exit_code=1, suites_run=["fingerprint"], results={}),
        )
        assert run_evals.main(["--skip-live-cc", "-o", str(tmp_path / "r.md")]) == 1
