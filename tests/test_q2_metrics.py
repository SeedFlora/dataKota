from __future__ import annotations

import numpy as np
import pytest

from crm.experiments.metrics import (
    _bootstrap_rng_streams,
    _cluster_bootstrap_design,
    _cluster_resample_indices,
    cluster_paired_accuracy_test,
    hierarchical_paired_bootstrap,
    mcnemar_exact,
    reliability_bin_rows,
    risk_at_uncertainty_threshold,
    risk_coverage_rows,
    training_seed_superpopulation_sensitivity_bootstrap,
    uncertainty_quality,
    uncertainty_threshold_at_target_coverage,
)


def _binary_probabilities(
    predictions: np.ndarray, confidence: float = 0.9
) -> np.ndarray:
    probabilities = np.full((len(predictions), 2), 1.0 - confidence)
    probabilities[np.arange(len(predictions)), predictions] = confidence
    return probabilities


def test_stratified_cluster_draw_never_splits_a_leakage_group() -> None:
    cluster_ids = np.array(["a", "a", "a", "b", "b", "c", "c", "c", "c"])
    y_true = np.array([0, 0, 1, 0, 0, 1, 1, 1, 0])
    calendar = np.array(["2026-01-01T00:00:00Z"] * len(cluster_ids))
    strata, _, _ = _cluster_bootstrap_design(
        cluster_ids,
        y_true,
        calendar,
        num_classes=2,
        stratification="utc_month_x_cluster_majority_label_v1",
    )

    for seed in range(20):
        sampled_indices = _cluster_resample_indices(
            cluster_ids, strata, np.random.default_rng(seed)
        )
        multiplicity: dict[str, int] = {}
        for cluster in np.unique(cluster_ids):
            row_indices = np.flatnonzero(cluster_ids == cluster)
            row_multiplicities = [
                int((sampled_indices == row_index).sum()) for row_index in row_indices
            ]
            assert len(set(row_multiplicities)) == 1
            multiplicity[str(cluster)] = row_multiplicities[0]
        for clusters in strata.values():
            assert sum(multiplicity[str(cluster)] for cluster in clusters) == len(
                clusters
            )


def test_bootstrap_cluster_and_training_seed_rng_streams_are_independent() -> None:
    primary_cluster_rng, primary_seed_rng, primary_receipt = _bootstrap_rng_streams(
        271828, include_training_seed_stream=False
    )
    sensitivity_cluster_rng, sensitivity_seed_rng, sensitivity_receipt = (
        _bootstrap_rng_streams(271828, include_training_seed_stream=True)
    )
    assert primary_seed_rng is None
    assert sensitivity_seed_rng is not None
    np.testing.assert_array_equal(
        primary_cluster_rng.integers(0, 2**31, size=32),
        sensitivity_cluster_rng.integers(0, 2**31, size=32),
    )
    sensitivity_cluster_rng, sensitivity_seed_rng, _ = _bootstrap_rng_streams(
        271828,
        include_training_seed_stream=True,
    )
    assert sensitivity_seed_rng is not None
    assert not np.array_equal(
        sensitivity_cluster_rng.integers(0, 2**31, size=32),
        sensitivity_seed_rng.integers(0, 2**31, size=32),
    )
    assert primary_receipt["cluster_spawn_key"] == [0]
    assert primary_receipt["training_seed_spawn_key"] is None
    assert sensitivity_receipt["cluster_spawn_key"] == [0]
    assert sensitivity_receipt["training_seed_spawn_key"] == [1]


def test_reliability_bins_account_for_every_sample() -> None:
    y_true = np.array([0, 1, 1, 0])
    probabilities = np.array([[0.9, 0.1], [0.4, 0.6], [0.8, 0.2], [0.55, 0.45]])
    rows = reliability_bin_rows(y_true, probabilities, bins=5)
    assert sum(row["count"] for row in rows) == len(y_true)
    assert abs(sum(row["fraction"] for row in rows) - 1.0) < 1e-12


def test_uncertainty_quality_includes_aurc() -> None:
    result = uncertainty_quality(
        np.array([0, 1, 1, 0]),
        np.array([0, 1, 0, 0]),
        np.array([0.1, 0.2, 0.9, 0.3]),
    )
    assert 0.0 <= result["aurc"] <= 1.0
    assert result["error_detection_auroc"] == 1.0


def test_uncertainty_ties_are_permutation_invariant_and_never_split() -> None:
    y_true = np.array([0, 0, 1, 1, 0])
    predictions = np.array([0, 1, 1, 0, 1])
    uncertainty = np.array([0.1, 0.2, 0.2, 0.2, 0.9])
    permutation = np.array([3, 0, 4, 2, 1])

    quality = uncertainty_quality(y_true, predictions, uncertainty)
    permuted_quality = uncertainty_quality(
        y_true[permutation], predictions[permutation], uncertainty[permutation]
    )
    assert quality == permuted_quality

    rows = risk_coverage_rows(
        y_true,
        predictions,
        uncertainty,
        (1.0, 0.4),
        num_classes=2,
    )
    permuted_rows = risk_coverage_rows(
        y_true[permutation],
        predictions[permutation],
        uncertainty[permutation],
        (1.0, 0.4),
        num_classes=2,
    )
    assert rows == permuted_rows
    partial_target = next(row for row in rows if row["target_coverage"] == 0.4)
    assert partial_target["retained"] == 4
    assert partial_target["realized_coverage"] == 0.8


def test_validation_threshold_is_applied_unchanged_to_later_partition() -> None:
    validation_uncertainty = np.array([0.1, 0.2, 0.3, 0.4, 0.9])
    threshold, validation_coverage, retained = uncertainty_threshold_at_target_coverage(
        validation_uncertainty, 0.8
    )
    assert threshold == 0.4
    assert validation_coverage == 0.8
    assert retained == 4

    result = risk_at_uncertainty_threshold(
        np.array([0, 1, 0, 1]),
        np.array([0, 1, 1, 1]),
        np.array([0.05, 0.35, 0.45, 0.8]),
        uncertainty_threshold=threshold,
        target_coverage=0.8,
        num_classes=2,
    )
    assert result["uncertainty_threshold"] == 0.4
    assert result["realized_coverage"] == 0.5
    assert result["retained"] == 2


def test_mcnemar_exact_counts_paired_disagreements() -> None:
    result = mcnemar_exact(
        np.array([0, 0, 1, 1]),
        np.array([0, 1, 0, 1]),
        np.array([0, 0, 1, 1]),
    )
    assert result["reference_correct_challenger_wrong"] == 0
    assert result["reference_wrong_challenger_correct"] == 2
    assert result["accuracy_delta_challenger_minus_reference"] == 0.5


def test_cluster_paired_accuracy_uses_leakage_groups_as_units() -> None:
    result = cluster_paired_accuracy_test(
        np.array([0, 0, 1, 1, 0, 0]),
        np.array([0, 1, 1, 0, 0, 1]),
        np.array([0, 0, 1, 1, 0, 0]),
        np.array(["a", "a", "b", "b", "c", "c"]),
        monte_carlo_iterations=1000,
        random_seed=13,
    )
    assert result["analysis_unit"] == "leakage_group_id"
    assert result["n_clusters"] == 3
    assert result["test_method"] == "cluster_sign_flip_exact"
    assert 0.0 <= result["cluster_paired_two_sided_p"] <= 1.0


def test_primary_bootstrap_holds_seed_ensemble_fixed_and_resamples_clusters() -> None:
    y_true = np.array([0, 0, 1, 1, 0, 1])
    reference = {
        1: (y_true, _binary_probabilities(np.array([0, 1, 1, 1, 0, 0]))),
        2: (y_true, _binary_probabilities(np.array([0, 0, 0, 1, 0, 1]))),
    }
    challenger = {
        1: (y_true, _binary_probabilities(np.array([0, 0, 1, 1, 0, 1]))),
        2: (y_true, _binary_probabilities(np.array([0, 0, 1, 1, 0, 1]))),
    }
    result = hierarchical_paired_bootstrap(
        reference,
        challenger,
        cluster_ids=np.array(["a", "a", "b", "b", "c", "c"]),
        calendar_values=np.array(
            [
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
                "2026-01-03T00:00:00Z",
                "2026-01-04T00:00:00Z",
                "2026-01-05T00:00:00Z",
                "2026-01-06T00:00:00Z",
            ]
        ),
        metric="accuracy",
        num_classes=2,
        iterations=100,
        confidence_level=0.95,
        random_seed=7,
    )
    assert result["delta_challenger_minus_reference"] > 0
    assert result["common_seeds"] == 2
    assert result["sampling_unit"] == "leakage_group_id"
    assert result["n_clusters"] == 3
    assert result["bootstrap_replicates"] == 100
    assert result["bootstrap_seed"] == 7
    assert result["bootstrap_stratification"] == (
        "utc_month_x_cluster_majority_label_v1"
    )
    assert result["strata_cluster_counts"] == {
        "utc_month=2026-01|majority_label=0": 2,
        "utc_month=2026-01|majority_label=1": 1,
    }
    assert len(result["cluster_strata_sha256"]) == 64
    assert "Carry every row" in result["bootstrap_algorithm"]
    assert result["probability_aggregation"] == (
        "arithmetic_mean_before_argmax_and_metric"
    )
    assert result["analysis_role"] == "primary_phase_a_prespecified_interval"
    assert result["training_seed_resampling"] is False
    assert result["replicate_seed_rule"] == (
        "all_preregistered_seeds_exactly_once_equal_weight_fixed_across_draws"
    )


def test_bootstrap_targets_probability_ensemble_not_mean_hard_seed_metrics() -> None:
    y_true = np.array([0, 1, 0, 1])
    reference = {
        1: (y_true, _binary_probabilities(np.array([0, 0, 0, 0]), 0.9)),
        2: (y_true, _binary_probabilities(np.array([1, 1, 1, 1]), 0.9)),
    }
    challenger = {
        1: (y_true, _binary_probabilities(y_true, 0.9)),
        2: (y_true, _binary_probabilities(1 - y_true, 0.51)),
    }

    result = hierarchical_paired_bootstrap(
        reference,
        challenger,
        cluster_ids=np.array(["a", "b", "c", "d"]),
        calendar_values=np.array(["2026-01-01T00:00:00Z"] * 4),
        metric="macro_f1",
        num_classes=2,
        iterations=100,
        confidence_level=0.95,
        random_seed=19,
    )

    old_mean_of_hard_seed_deltas = 1.0 / 6.0
    assert result["delta_challenger_minus_reference"] == pytest.approx(2.0 / 3.0)
    assert result["delta_challenger_minus_reference"] != pytest.approx(
        old_mean_of_hard_seed_deltas
    )
    assert result["estimand"] == (
        "deployed_fixed_preregistered_seed_ensemble_metric_delta"
    )


def test_seed_resampling_is_secondary_and_not_the_fixed_ensemble_ci() -> None:
    y_true = np.array([0, 0, 0, 0])
    fixed_reference = _binary_probabilities(np.array([0, 0, 0, 0]), 0.9)
    reference = {
        1: (y_true, fixed_reference),
        2: (y_true, fixed_reference),
    }
    challenger = {
        1: (y_true, _binary_probabilities(np.array([0, 0, 0, 0]), 0.9)),
        2: (y_true, _binary_probabilities(np.array([1, 1, 1, 1]), 0.9)),
    }
    common = {
        "cluster_ids": np.array(["a", "b", "c", "d"]),
        "calendar_values": np.array(["2026-01-01T00:00:00Z"] * 4),
        "metric": "accuracy",
        "num_classes": 2,
        "iterations": 1000,
        "confidence_level": 0.95,
        "random_seed": 41,
    }

    primary = hierarchical_paired_bootstrap(reference, challenger, **common)
    sensitivity = training_seed_superpopulation_sensitivity_bootstrap(
        reference, challenger, **common
    )

    assert primary["delta_challenger_minus_reference"] == 0.0
    assert primary["ci_lower"] == 0.0
    assert primary["ci_upper"] == 0.0
    assert primary["training_seed_resampling"] is False
    assert sensitivity["training_seed_resampling"] is True
    assert sensitivity["analysis_role"] == "secondary_training_seed_sensitivity"
    assert sensitivity["bootstrap_rng_stream_derivation"] == {
        "scheme": "numpy_seedsequence_spawn_v1",
        "bit_generator": "PCG64",
        "root_entropy": 41,
        "cluster_spawn_key": [0],
        "training_seed_spawn_key": [1],
    }
    assert sensitivity["estimand"] == (
        "training_seed_superpopulation_equal_size_probability_ensemble_metric_delta"
    )
    assert sensitivity["ci_lower"] < primary["ci_lower"]
