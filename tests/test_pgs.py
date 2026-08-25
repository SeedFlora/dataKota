from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.pgs import (
    minimum_trees_for_virtual_ensembles,
    pgs_predict,
    pgs_predict_proba,
    validate_pgs_model,
)


class _FakeVirtualEnsembleModel:
    def __init__(self, output: np.ndarray):
        self.output = output
        self.calls = []

    def virtual_ensembles_predict(self, X, **kwargs):
        self.calls.append(kwargs)
        return self.output


class _FakePGSCheckpoint:
    def __init__(self, trees: int, posterior_sampling: bool = True):
        self.tree_count_ = trees
        self.posterior_sampling = posterior_sampling

    def get_all_params(self):
        return {"posterior_sampling": self.posterior_sampling}


class PGSTest(unittest.TestCase):
    def test_multiclass_uses_mean_of_probabilities_and_mutual_information(self):
        logits = np.array(
            [
                [
                    [4.0, 0.0, -1.0],
                    [0.0, 4.0, -1.0],
                ]
            ],
            dtype=np.float64,
        )
        model = _FakeVirtualEnsembleModel(logits)
        result = pgs_predict(model, np.zeros((1, 5)), 2)

        shifted = logits - logits.max(axis=2, keepdims=True)
        per_ensemble = np.exp(shifted) / np.exp(shifted).sum(axis=2, keepdims=True)
        expected_probs = per_ensemble.mean(axis=1)
        expected_predictive_entropy = -np.sum(
            expected_probs * np.log(expected_probs), axis=1
        )
        expected_data_entropy = -np.sum(
            per_ensemble * np.log(per_ensemble),
            axis=2,
        ).mean(axis=1)

        np.testing.assert_allclose(result.probabilities, expected_probs, atol=1e-7)
        np.testing.assert_allclose(
            result.epistemic_mutual_information,
            expected_predictive_entropy - expected_data_entropy,
            atol=1e-7,
        )
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0]["prediction_type"], "VirtEnsembles")

    def test_backward_compatible_wrapper_returns_epistemic_mi(self):
        logits = np.array([[[1.0, -1.0], [1.0, -1.0]]])
        model = _FakeVirtualEnsembleModel(logits)
        probabilities, uncertainty = pgs_predict_proba(
            model,
            np.zeros((1, 2)),
            2,
        )
        np.testing.assert_allclose(probabilities.sum(axis=1), 1.0)
        np.testing.assert_allclose(uncertainty, 0.0, atol=1e-7)

    def test_binary_single_logit_is_converted_to_two_probabilities(self):
        logits = np.array([[[0.0], [2.0]]])
        result = pgs_predict(
            _FakeVirtualEnsembleModel(logits),
            np.zeros((1, 3)),
            2,
        )
        self.assertEqual(result.probabilities.shape, (1, 2))
        np.testing.assert_allclose(result.probabilities.sum(axis=1), 1.0)

    def test_invalid_ensemble_shape_fails_loudly(self):
        model = _FakeVirtualEnsembleModel(np.zeros((1, 3, 2)))
        with self.assertRaisesRegex(ValueError, "does not match"):
            pgs_predict(model, np.zeros((1, 2)), 2)

    def test_at_least_two_ensembles_are_required(self):
        model = _FakeVirtualEnsembleModel(np.zeros((1, 1, 2)))
        with self.assertRaisesRegex(ValueError, "at least 2"):
            pgs_predict(model, np.zeros((1, 2)), 1)

    def test_tree_budget_is_guarded_before_virtual_ensemble_use(self):
        self.assertEqual(minimum_trees_for_virtual_ensembles(30), 61)
        with self.assertRaisesRegex(ValueError, "retained 60 trees"):
            validate_pgs_model(_FakePGSCheckpoint(60), 30)
        self.assertEqual(validate_pgs_model(_FakePGSCheckpoint(61), 30), 61)

    def test_posterior_sampling_checkpoint_is_required(self):
        with self.assertRaisesRegex(ValueError, "posterior_sampling=true"):
            validate_pgs_model(_FakePGSCheckpoint(100, False), 30)


if __name__ == "__main__":
    unittest.main()
