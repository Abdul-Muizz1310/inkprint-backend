"""Tests for the eval suite runner — spec 06-evals.md."""

from pathlib import Path

import pytest

EVALS_DIR = Path(__file__).resolve().parents[2] / "evals"


# ── Runner ───────────────────────────────────────────────────────────────────


class TestEvalRunner:
    def test_tc_e_01_runner_exits_zero_on_pass(self):
        """TC-E-01: run_evals.py exits 0 when all targets met."""
        from inkprint.evals.runner import run_all

        # With mocked passing results
        report = run_all(skip_live_cc=True, mock_results=True)
        assert report.exit_code == 0

    def test_tc_e_02_runner_exits_one_on_fail(self):
        """TC-E-02: run_evals.py exits 1 when any target missed."""
        from inkprint.evals.runner import run_all

        report = run_all(
            skip_live_cc=True,
            mock_results=True,
            override_fingerprint_accuracy=0.50,  # below 0.90 target
        )
        assert report.exit_code == 1

    def test_tc_e_03_skip_live_cc_flag(self):
        """TC-E-03: --skip-live-cc skips leak detection suite."""
        from inkprint.evals.runner import run_all

        report = run_all(skip_live_cc=True, mock_results=True)
        assert "leak" not in report.suites_run

    def test_tc_e_04_report_written(self, tmp_path):
        """TC-E-04: Report is written with date, scores, pass/fail."""
        from inkprint.evals.runner import run_all

        run_all(
            skip_live_cc=True,
            mock_results=True,
            output_path=tmp_path / "report.md",
        )
        assert (tmp_path / "report.md").exists()
        content = (tmp_path / "report.md").read_text()
        assert "fingerprint" in content.lower()
        assert "pass" in content.lower() or "fail" in content.lower()


# ── Fingerprint eval dataset ─────────────────────────────────────────────────


class TestFingerprintEvalData:
    def test_tc_e_05_100_pairs(self):
        """TC-E-05: fingerprint_pairs.yaml has exactly 100 pairs."""
        import yaml

        path = EVALS_DIR / "fingerprint_pairs.yaml"
        assert path.exists(), f"{path} not found"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data["pairs"]) == 100

    def test_tc_e_06_pair_fields(self):
        """TC-E-06: Each pair has original, variant, expected fields."""
        import yaml

        path = EVALS_DIR / "fingerprint_pairs.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        for i, pair in enumerate(data["pairs"]):
            assert "original" in pair, f"Pair {i} missing 'original'"
            assert "variant" in pair, f"Pair {i} missing 'variant'"
            assert "expected" in pair, f"Pair {i} missing 'expected'"
            assert pair["expected"] in ("similar", "unrelated"), (
                f"Pair {i} has invalid expected: {pair['expected']}"
            )

    def test_tc_e_07_accuracy_target(self):
        """TC-E-07: Accuracy >= 0.90 on the full fingerprint eval set."""
        from inkprint.evals.fingerprint_eval import evaluate_fingerprint_pairs

        result = evaluate_fingerprint_pairs()
        assert result.accuracy >= 0.90, f"Fingerprint accuracy {result.accuracy:.2%} < 90% target"


# ── Leak eval dataset ────────────────────────────────────────────────────────


class TestLeakEvalData:
    def test_tc_e_08_dataset_counts(self):
        """TC-E-08: leak_probe.yaml has 20 known_leaked + 20 clean."""
        import yaml

        path = EVALS_DIR / "leak_probe.yaml"
        assert path.exists(), f"{path} not found"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data["known_leaked"]) == 20
        assert len(data["clean"]) == 20

    @pytest.mark.slow
    def test_tc_e_09_true_positive_rate(self):
        """TC-E-09: True positive rate >= 18/20."""
        from inkprint.evals.leak_eval import evaluate_leak_probe

        result = evaluate_leak_probe()
        assert result.true_positives >= 18, (
            f"True positive rate {result.true_positives}/20 < 18/20 target"
        )

    @pytest.mark.slow
    def test_tc_e_10_false_positive_rate(self):
        """TC-E-10: False positive rate <= 2/20."""
        from inkprint.evals.leak_eval import evaluate_leak_probe

        result = evaluate_leak_probe()
        assert result.false_positives <= 2, (
            f"False positive rate {result.false_positives}/20 > 2/20 target"
        )


# ── Tamper eval dataset ──────────────────────────────────────────────────────


class TestTamperEvalData:
    def test_tc_e_11_50_manifests(self):
        """TC-E-11: tamper_tests.yaml has exactly 50 tampered manifests."""
        import yaml

        path = EVALS_DIR / "tamper_tests.yaml"
        assert path.exists(), f"{path} not found"
        with open(path) as f:
            data = yaml.safe_load(f)
        assert len(data["manifests"]) == 50

    def test_tc_e_12_tamper_type_labels(self):
        """TC-E-12: Each manifest has a tamper_type label."""
        import yaml

        path = EVALS_DIR / "tamper_tests.yaml"
        with open(path) as f:
            data = yaml.safe_load(f)
        for i, m in enumerate(data["manifests"]):
            assert "tamper_type" in m, f"Manifest {i} missing tamper_type"

    def test_tc_e_13_rejection_rate(self):
        """TC-E-13: Rejection rate = 50/50."""
        from inkprint.evals.tamper_eval import evaluate_tamper_tests

        result = evaluate_tamper_tests()
        assert result.rejected == 50, f"Rejection rate {result.rejected}/50, expected 50/50"
