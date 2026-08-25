from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.deployment import (
    classifier_parity_report,
    determine_review_reasons,
    equal_weight_probability_mean,
    normalize_probability_output,
)


class DeploymentContractTest(unittest.TestCase):
    def test_zipmap_columns_follow_class_id_not_mapping_order(self):
        raw = [{2: 0.6, 0: 0.1, 1: 0.3}]
        probabilities = normalize_probability_output(raw, [0, 1, 2])
        np.testing.assert_allclose(probabilities, [[0.1, 0.3, 0.6]])

    def test_string_zipmap_keys_are_supported(self):
        raw = [{"1": 0.75, "0": 0.25}]
        probabilities = normalize_probability_output(raw, [0, 1])
        np.testing.assert_allclose(probabilities, [[0.25, 0.75]])

    def test_logits_are_not_silently_reported_as_probabilities(self):
        with self.assertRaisesRegex(ValueError, "outside the probability range"):
            normalize_probability_output(np.array([[3.0, -1.0]]), [0, 1])

    def test_seed_ensemble_is_an_equal_arithmetic_probability_mean(self):
        members = [
            np.array([[0.9, 0.1]]),
            np.array([[0.8, 0.2]]),
            np.array([[0.7, 0.3]]),
            np.array([[0.4, 0.6]]),
            np.array([[0.2, 0.8]]),
        ]
        actual = equal_weight_probability_mean(
            members, class_count=2, expected_members=5
        )
        np.testing.assert_allclose(actual, [[0.6, 0.4]], atol=1e-7)
        with self.assertRaisesRegex(ValueError, "expected 5 seed heads"):
            equal_weight_probability_mean(
                members[:4], class_count=2, expected_members=5
            )

    def test_review_reasons_are_explicit_and_composable(self):
        reasons = determine_review_reasons(
            predicted_label="Instansi lain",
            confidence=0.5,
            confidence_threshold=0.7,
            catch_all_label="Instansi lain",
            epistemic_uncertainty=0.12,
            epistemic_uncertainty_threshold=0.1,
        )
        self.assertEqual(
            reasons,
            ["low_confidence", "catch_all_class", "high_epistemic_uncertainty"],
        )

    def test_uncertainty_threshold_requires_uncertainty_output(self):
        with self.assertRaisesRegex(ValueError, "uncertainty-enabled"):
            determine_review_reasons(
                predicted_label="Dinas Perhubungan",
                confidence=0.9,
                confidence_threshold=0.7,
                epistemic_uncertainty_threshold=0.1,
            )

    def test_classifier_parity_gate_reports_pass_and_fail(self):
        reference = np.array([[0.2, 0.8], [0.7, 0.3]])
        close = np.array([[0.200001, 0.799999], [0.700001, 0.299999]])
        passed = classifier_parity_report(
            reference,
            close,
            probability_tolerance=2e-6,
        )
        self.assertTrue(passed.passed)
        self.assertEqual(passed.top1_agreement, 1.0)

        flipped = np.array([[0.9, 0.1], [0.7, 0.3]])
        failed = classifier_parity_report(reference, flipped)
        self.assertFalse(failed.passed)
        self.assertEqual(failed.top1_agreement, 0.5)


if __name__ == "__main__":
    unittest.main()
