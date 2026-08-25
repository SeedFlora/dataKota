"""Publication-oriented classification, calibration, and paired statistics."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from hashlib import sha256
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import binomtest
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)

ECE_FAMILY = "top_label"
ECE_BINNING = "equal_width_0_1"
ECE_BIN_INTERVAL_SEMANTICS = "left_closed_right_open_final_closed"


def _validate_ece_protocol(
    *,
    family: str,
    binning: str,
    interval_semantics: str,
) -> None:
    observed = (family, binning, interval_semantics)
    expected = (ECE_FAMILY, ECE_BINNING, ECE_BIN_INTERVAL_SEMANTICS)
    if observed != expected:
        raise ValueError(
            "unsupported ECE protocol; expected top-label confidence with "
            "equal-width [0,1] bins and a closed final boundary"
        )


def predictive_entropy(probabilities: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    probabilities = np.asarray(probabilities, dtype=np.float64)
    return -(probabilities * np.log(np.clip(probabilities, eps, 1.0))).sum(axis=1)


def expected_calibration_error(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 15,
    family: str = ECE_FAMILY,
    binning: str = ECE_BINNING,
    interval_semantics: str = ECE_BIN_INTERVAL_SEMANTICS,
) -> float:
    """Top-label ECE with equal-width confidence bins."""
    _validate_ece_protocol(
        family=family,
        binning=binning,
        interval_semantics=interval_semantics,
    )
    probabilities = np.asarray(probabilities, dtype=np.float64)
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predictions == np.asarray(y_true)
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        if index == bins - 1:
            in_bin = (confidence >= lower) & (confidence <= upper)
        else:
            in_bin = (confidence >= lower) & (confidence < upper)
        if not in_bin.any():
            continue
        weight = in_bin.mean()
        ece += weight * abs(
            float(correct[in_bin].mean()) - float(confidence[in_bin].mean())
        )
    return float(ece)


def reliability_bin_rows(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    bins: int = 15,
    family: str = ECE_FAMILY,
    binning: str = ECE_BINNING,
    interval_semantics: str = ECE_BIN_INTERVAL_SEMANTICS,
) -> list[dict[str, float | int | None]]:
    """Return the exact table needed to reproduce a reliability diagram."""
    _validate_ece_protocol(
        family=family,
        binning=binning,
        interval_semantics=interval_semantics,
    )
    y_true = np.asarray(y_true)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predictions == y_true
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows: list[dict[str, float | int | None]] = []
    for index in range(bins):
        lower, upper = float(edges[index]), float(edges[index + 1])
        if index == bins - 1:
            in_bin = (confidence >= lower) & (confidence <= upper)
        else:
            in_bin = (confidence >= lower) & (confidence < upper)
        count = int(in_bin.sum())
        mean_confidence = float(confidence[in_bin].mean()) if count else None
        empirical_accuracy = float(correct[in_bin].mean()) if count else None
        rows.append(
            {
                "bin": index,
                "lower": lower,
                "upper": upper,
                "count": count,
                "fraction": float(count / len(y_true)),
                "mean_confidence": mean_confidence,
                "empirical_accuracy": empirical_accuracy,
                "absolute_gap": (
                    abs(empirical_accuracy - mean_confidence)
                    if count
                    and empirical_accuracy is not None
                    and mean_confidence is not None
                    else None
                ),
            }
        )
    return rows


def multiclass_brier_score(
    y_true: np.ndarray, probabilities: np.ndarray, num_classes: int
) -> float:
    one_hot = np.eye(num_classes, dtype=np.float64)[np.asarray(y_true, dtype=int)]
    return float(np.square(np.asarray(probabilities) - one_hot).sum(axis=1).mean())


def confusion_matrix_rows(
    y_true: np.ndarray,
    predictions: np.ndarray,
    *,
    num_classes: int,
) -> tuple[list[dict[str, int]], list[dict[str, float | int]]]:
    """Raw and true-row-normalized matrices with explicit class IDs."""
    labels = np.arange(num_classes)
    counts = confusion_matrix(y_true, predictions, labels=labels)
    denominators = counts.sum(axis=1, keepdims=True)
    normalized = np.divide(
        counts,
        denominators,
        out=np.zeros_like(counts, dtype=np.float64),
        where=denominators != 0,
    )
    count_rows: list[dict[str, int]] = []
    normalized_rows: list[dict[str, float | int]] = []
    for true_class in labels:
        count_rows.append(
            {
                "true_class_id": int(true_class),
                **{
                    f"pred_{predicted_class}": int(counts[true_class, predicted_class])
                    for predicted_class in labels
                },
            }
        )
        normalized_rows.append(
            {
                "true_class_id": int(true_class),
                **{
                    f"pred_{predicted_class}": float(
                        normalized[true_class, predicted_class]
                    )
                    for predicted_class in labels
                },
            }
        )
    return count_rows, normalized_rows


def classification_metrics(
    y_true: np.ndarray,
    probabilities: np.ndarray,
    *,
    num_classes: int,
    ece_bins: int,
    ece_family: str = ECE_FAMILY,
    ece_binning: str = ECE_BINNING,
    ece_bin_interval_semantics: str = ECE_BIN_INTERVAL_SEMANTICS,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y_true = np.asarray(y_true, dtype=np.int64)
    probabilities = np.asarray(probabilities, dtype=np.float64)
    if probabilities.shape != (len(y_true), num_classes):
        raise ValueError(
            "probability matrix shape mismatch: "
            f"expected {(len(y_true), num_classes)}, got {probabilities.shape}"
        )
    if not np.isfinite(probabilities).all():
        raise ValueError("probabilities contain NaN or infinity")
    row_sums = probabilities.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-5):
        raise ValueError("probability rows must sum to one")
    predictions = probabilities.argmax(axis=1)
    labels = np.arange(num_classes)
    precision, recall, per_class_f1, support = precision_recall_fscore_support(
        y_true,
        predictions,
        labels=labels,
        zero_division=0,
    )
    metrics: dict[str, Any] = {
        "n_samples": len(y_true),
        "accuracy": float(accuracy_score(y_true, predictions)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predictions)),
        "macro_precision": float(precision.mean()),
        "macro_recall": float(recall.mean()),
        "macro_f1": float(
            f1_score(
                y_true, predictions, labels=labels, average="macro", zero_division=0
            )
        ),
        "weighted_f1": float(
            f1_score(
                y_true, predictions, labels=labels, average="weighted", zero_division=0
            )
        ),
        "nll": float(log_loss(y_true, probabilities, labels=labels)),
        "multiclass_brier": multiclass_brier_score(y_true, probabilities, num_classes),
        "ece": expected_calibration_error(
            y_true,
            probabilities,
            bins=ece_bins,
            family=ece_family,
            binning=ece_binning,
            interval_semantics=ece_bin_interval_semantics,
        ),
        "ece_family": ece_family,
        "ece_binning": ece_binning,
        "ece_bins": int(ece_bins),
        "ece_bin_interval_semantics": ece_bin_interval_semantics,
    }
    try:
        metrics["macro_ovr_roc_auc"] = float(
            roc_auc_score(
                y_true,
                probabilities,
                labels=labels,
                multi_class="ovr",
                average="macro",
            )
        )
    except ValueError:
        metrics["macro_ovr_roc_auc"] = None

    per_class = [
        {
            "class_id": int(class_id),
            "precision": float(precision[class_id]),
            "recall": float(recall[class_id]),
            "f1": float(per_class_f1[class_id]),
            "support": int(support[class_id]),
        }
        for class_id in labels
    ]
    return metrics, per_class


def uncertainty_quality(
    y_true: np.ndarray,
    predictions: np.ndarray,
    uncertainty: np.ndarray,
) -> dict[str, float | None]:
    """Measure whether uncertainty ranks errors above correct predictions."""
    y_true = np.asarray(y_true)
    predictions = np.asarray(predictions)
    uncertainty = np.asarray(uncertainty, dtype=np.float64)
    if (
        y_true.ndim != 1
        or predictions.shape != y_true.shape
        or uncertainty.shape != y_true.shape
        or not len(y_true)
    ):
        raise ValueError("uncertainty metrics require non-empty aligned 1D arrays")
    if not np.isfinite(uncertainty).all():
        raise ValueError("uncertainty values must be finite")
    errors = (predictions != y_true).astype(np.int8)
    # Treat equal scores as an inseparable threshold group.  Each group's risk
    # is evaluated after accepting the entire group and weighted by its share
    # of cases.  This equals the usual empirical AURC when scores are unique,
    # while avoiding arbitrary row-order effects when scores are tied.
    _, inverse, group_sizes = np.unique(
        uncertainty, return_inverse=True, return_counts=True
    )
    group_errors = np.bincount(inverse, weights=errors, minlength=len(group_sizes))
    cumulative_sizes = np.cumsum(group_sizes)
    cumulative_risk = np.cumsum(group_errors) / cumulative_sizes
    result: dict[str, float | None] = {
        "aurc": float(np.sum(cumulative_risk * group_sizes) / len(errors)),
    }
    if len(np.unique(errors)) < 2:
        result.update({"error_detection_auroc": None, "error_detection_aupr": None})
    else:
        result.update(
            {
                "error_detection_auroc": float(roc_auc_score(errors, uncertainty)),
                "error_detection_aupr": float(
                    average_precision_score(errors, uncertainty)
                ),
            }
        )
    return result


def mcnemar_exact(
    y_true: np.ndarray,
    reference_predictions: np.ndarray,
    challenger_predictions: np.ndarray,
) -> dict[str, float | int]:
    """Two-sided exact McNemar test for paired accuracy."""
    y_true = np.asarray(y_true)
    reference_correct = np.asarray(reference_predictions) == y_true
    challenger_correct = np.asarray(challenger_predictions) == y_true
    reference_only = int((reference_correct & ~challenger_correct).sum())
    challenger_only = int((~reference_correct & challenger_correct).sum())
    discordant = reference_only + challenger_only
    p_value = (
        float(binomtest(min(reference_only, challenger_only), discordant, 0.5).pvalue)
        if discordant
        else 1.0
    )
    return {
        "reference_correct_challenger_wrong": reference_only,
        "reference_wrong_challenger_correct": challenger_only,
        "discordant": discordant,
        "accuracy_delta_challenger_minus_reference": float(
            challenger_correct.mean() - reference_correct.mean()
        ),
        "mcnemar_exact_two_sided_p": p_value,
    }


def cluster_paired_accuracy_test(
    y_true: np.ndarray,
    reference_predictions: np.ndarray,
    challenger_predictions: np.ndarray,
    cluster_ids: np.ndarray,
    *,
    monte_carlo_iterations: int,
    random_seed: int,
) -> dict[str, float | int | str]:
    """Paired cluster sign-flip test for an accuracy difference.

    Each leakage group is the independent analysis unit.  All case-level
    correctness deltas inside a group receive the same random sign, retaining
    arbitrary within-group dependence while estimating the case-weighted
    accuracy contrast.  Up to 20 informative groups are enumerated exactly;
    larger families use a preregistered Monte Carlo budget and seed.
    """
    y_true = np.asarray(y_true)
    reference_predictions = np.asarray(reference_predictions)
    challenger_predictions = np.asarray(challenger_predictions)
    cluster_ids = np.asarray(cluster_ids).astype(str)
    if (
        y_true.ndim != 1
        or reference_predictions.shape != y_true.shape
        or challenger_predictions.shape != y_true.shape
        or cluster_ids.shape != y_true.shape
        or not len(y_true)
    ):
        raise ValueError("cluster paired test requires non-empty aligned 1D arrays")
    if monte_carlo_iterations < 1000:
        raise ValueError("monte_carlo_iterations must be >= 1000")

    case_deltas = (challenger_predictions == y_true).astype(np.int64) - (
        reference_predictions == y_true
    ).astype(np.int64)
    unique_clusters, inverse = np.unique(cluster_ids, return_inverse=True)
    cluster_deltas = np.bincount(
        inverse, weights=case_deltas, minlength=len(unique_clusters)
    ).astype(np.int64)
    informative = cluster_deltas[cluster_deltas != 0]
    observed_net = int(cluster_deltas.sum())
    observed_absolute = abs(observed_net)

    if not len(informative):
        p_value = 1.0
        method = "cluster_sign_flip_exact_degenerate"
        draws = 1
    elif len(informative) <= 20:
        null_statistics = np.array([0], dtype=np.int64)
        for contribution in informative:
            null_statistics = np.concatenate(
                (
                    null_statistics + contribution,
                    null_statistics - contribution,
                )
            )
        p_value = float(np.mean(np.abs(null_statistics) >= observed_absolute))
        method = "cluster_sign_flip_exact"
        draws = len(null_statistics)
    else:
        rng = np.random.default_rng(random_seed)
        extreme = 0
        completed = 0
        while completed < monte_carlo_iterations:
            batch_size = min(1000, monte_carlo_iterations - completed)
            signs = (
                rng.integers(
                    0,
                    2,
                    size=(batch_size, len(informative)),
                    dtype=np.int8,
                )
                * 2
                - 1
            )
            null_statistics = signs @ informative
            extreme += int((np.abs(null_statistics) >= observed_absolute).sum())
            completed += batch_size
        p_value = float((extreme + 1) / (monte_carlo_iterations + 1))
        method = "cluster_sign_flip_monte_carlo"
        draws = int(monte_carlo_iterations)

    reference_accuracy = float(np.mean(reference_predictions == y_true))
    challenger_accuracy = float(np.mean(challenger_predictions == y_true))
    return {
        "analysis_unit": "leakage_group_id",
        "n_cases": len(y_true),
        "n_clusters": len(unique_clusters),
        "informative_clusters": len(informative),
        "reference_accuracy": reference_accuracy,
        "challenger_accuracy": challenger_accuracy,
        "accuracy_delta_challenger_minus_reference": float(
            challenger_accuracy - reference_accuracy
        ),
        "observed_net_correct_delta": observed_net,
        "test_method": method,
        "randomization_draws": draws,
        "cluster_paired_two_sided_p": p_value,
    }


def holm_adjusted_pvalues(p_values: list[float]) -> list[float]:
    """Holm family-wise error correction, preserving the input order."""
    if not p_values:
        return []
    values = np.asarray(p_values, dtype=np.float64)
    if ((values < 0.0) | (values > 1.0) | ~np.isfinite(values)).any():
        raise ValueError("p-values must be finite and in [0, 1]")
    order = np.argsort(values, kind="stable")
    adjusted_sorted = np.empty(len(values), dtype=np.float64)
    running_max = 0.0
    for rank, original_index in enumerate(order):
        adjusted = min(1.0, (len(values) - rank) * values[original_index])
        running_max = max(running_max, adjusted)
        adjusted_sorted[rank] = running_max
    result = np.empty(len(values), dtype=np.float64)
    result[order] = adjusted_sorted
    return result.tolist()


def uncertainty_threshold_at_target_coverage(
    uncertainty: np.ndarray,
    target_coverage: float,
) -> tuple[float, float, int]:
    """Choose an uncertainty threshold using a fixed target and whole ties.

    The threshold depends only on the supplied uncertainty distribution, not on
    correctness labels. It is intended to be fitted on validation and frozen
    before evaluating a later partition.
    """
    uncertainty = np.asarray(uncertainty, dtype=np.float64)
    if uncertainty.ndim != 1 or not len(uncertainty):
        raise ValueError("uncertainty threshold fitting requires a non-empty 1D array")
    if not np.isfinite(uncertainty).all():
        raise ValueError("uncertainty values must be finite")
    if not 0.0 < target_coverage <= 1.0:
        raise ValueError("target_coverage must be in (0, 1]")
    thresholds, threshold_counts = np.unique(uncertainty, return_counts=True)
    cumulative_counts = np.cumsum(threshold_counts)
    requested = max(1, int(np.ceil(target_coverage * len(uncertainty) - 1e-12)))
    threshold_index = int(np.searchsorted(cumulative_counts, requested, side="left"))
    threshold = float(thresholds[threshold_index])
    retained = int(np.count_nonzero(uncertainty <= threshold))
    return threshold, float(retained / len(uncertainty)), retained


def risk_at_uncertainty_threshold(
    y_true: np.ndarray,
    predictions: np.ndarray,
    uncertainty: np.ndarray,
    *,
    uncertainty_threshold: float,
    target_coverage: float,
    num_classes: int,
) -> dict[str, float | int]:
    """Evaluate a threshold that was frozen on another partition."""
    y_true = np.asarray(y_true)
    predictions = np.asarray(predictions)
    uncertainty = np.asarray(uncertainty, dtype=np.float64)
    if (
        y_true.ndim != 1
        or predictions.shape != y_true.shape
        or uncertainty.shape != y_true.shape
        or not len(y_true)
    ):
        raise ValueError("risk-coverage requires non-empty aligned 1D arrays")
    if not np.isfinite(uncertainty).all() or not np.isfinite(uncertainty_threshold):
        raise ValueError("uncertainty values and threshold must be finite")
    if not 0.0 < target_coverage <= 1.0:
        raise ValueError("target_coverage must be in (0, 1]")
    indices = np.flatnonzero(uncertainty <= uncertainty_threshold)
    retained = len(indices)
    labels = np.arange(num_classes)
    if retained:
        subset_true = y_true[indices]
        subset_pred = predictions[indices]
        selective_risk = float(1.0 - accuracy_score(subset_true, subset_pred))
        selective_macro_f1 = float(
            f1_score(
                subset_true,
                subset_pred,
                labels=labels,
                average="macro",
                zero_division=0,
            )
        )
    else:
        selective_risk = float("nan")
        selective_macro_f1 = float("nan")
    return {
        "target_coverage": float(target_coverage),
        "realized_coverage": float(retained / len(y_true)),
        "retained": int(retained),
        "selective_risk": selective_risk,
        "selective_macro_f1": selective_macro_f1,
        "uncertainty_threshold": float(uncertainty_threshold),
    }


def risk_at_acceptance_mask(
    y_true: np.ndarray,
    predictions: np.ndarray,
    accepted: np.ndarray,
    *,
    target_coverage: float,
    num_classes: int,
) -> dict[str, float | int]:
    """Evaluate the deployed conjunction of already-frozen review gates."""
    y_true = np.asarray(y_true)
    predictions = np.asarray(predictions)
    accepted = np.asarray(accepted, dtype=bool)
    if (
        y_true.ndim != 1
        or predictions.shape != y_true.shape
        or accepted.shape != y_true.shape
        or not len(y_true)
    ):
        raise ValueError("joint selective risk requires aligned non-empty 1D arrays")
    if not 0.0 < target_coverage <= 1.0:
        raise ValueError("target_coverage must be in (0, 1]")
    retained = int(accepted.sum())
    if retained:
        subset_true = y_true[accepted]
        subset_pred = predictions[accepted]
        risk = float(1.0 - accuracy_score(subset_true, subset_pred))
        macro_f1 = float(
            f1_score(
                subset_true,
                subset_pred,
                labels=np.arange(num_classes),
                average="macro",
                zero_division=0,
            )
        )
    else:
        risk = float("nan")
        macro_f1 = float("nan")
    return {
        "target_coverage": float(target_coverage),
        "realized_coverage": float(retained / len(y_true)),
        "retained": retained,
        "selective_risk": risk,
        "selective_macro_f1": macro_f1,
    }


def risk_coverage_rows(
    y_true: np.ndarray,
    predictions: np.ndarray,
    uncertainty: np.ndarray,
    coverage_points: tuple[float, ...],
    *,
    num_classes: int,
) -> list[dict[str, float | int]]:
    """Selective-classification curve with indivisible uncertainty ties.

    For each requested coverage, the least-uncertain threshold is chosen and
    every case tied at that boundary is retained.  Realized coverage can thus
    exceed the requested value, but never depends on input row order.
    """
    y_true = np.asarray(y_true)
    predictions = np.asarray(predictions)
    uncertainty = np.asarray(uncertainty, dtype=np.float64)
    if (
        y_true.ndim != 1
        or predictions.shape != y_true.shape
        or uncertainty.shape != y_true.shape
        or not len(y_true)
    ):
        raise ValueError("risk-coverage requires non-empty aligned 1D arrays")
    if not np.isfinite(uncertainty).all():
        raise ValueError("uncertainty values must be finite")
    rows: list[dict[str, float | int]] = []
    for coverage in sorted(set(coverage_points), reverse=True):
        threshold, _, _ = uncertainty_threshold_at_target_coverage(
            uncertainty, coverage
        )
        rows.append(
            risk_at_uncertainty_threshold(
                y_true,
                predictions,
                uncertainty,
                uncertainty_threshold=threshold,
                target_coverage=coverage,
                num_classes=num_classes,
            )
        )
    return rows


BOOTSTRAP_STRATIFICATION = "utc_month_x_cluster_majority_label_v1"
BOOTSTRAP_ALGORITHM_ID = (
    "paired_stratified_whole_cluster_fixed_seed_ensemble_percentile_v4"
)
BOOTSTRAP_ALGORITHM = (
    "For every leakage_group_id, assign the earliest UTC calendar month present "
    "in that group and its row-count majority y_true class (smallest class ID "
    "breaks a tie). Form UTC-month x majority-label strata. Hold the deployed "
    "equal-weight probability ensemble fixed: average every preregistered seed "
    "exactly once, then apply argmax with the lowest class ID on an exact tie. "
    "For each replicate, in lexically sorted strata, sample the original number "
    "of group IDs with replacement from lexically sorted IDs. Carry every row of "
    "each selected group, including repeated copies, and use the identical row "
    "multiset and fixed prediction vectors for both paired systems. Compute the "
    "paired metric difference on that shared cluster-row multiset and use "
    "percentile quantiles over the fixed replicate count. Derive the cluster RNG "
    "as SeedSequence(bootstrap_seed).spawn(2)[0]. No seed is resampled in "
    "this primary deployed-model estimand. No model prediction or test score "
    "defines or changes a stratum, seed, or replicate count."
)

TRAINING_SEED_SENSITIVITY_ALGORITHM_ID = (
    "paired_stratified_cluster_training_seed_superpopulation_percentile_v2"
)
TRAINING_SEED_SENSITIVITY_ALGORITHM = (
    "Secondary training-instability sensitivity analysis. Use the same frozen "
    "UTC-month x cluster-majority-label strata and exact paired whole-cluster "
    "replicate sequence as the primary bootstrap by using the same PCG64 child "
    "stream derived from SeedSequence(bootstrap_seed). A second, independently "
    "spawned PCG64 child stream drives training-seed draws. In each replicate, additionally "
    "sample the complete "
    "preregistered training-seed list with replacement to its original length, "
    "average the sampled probability tensors within each system, apply argmax "
    "with the lowest class ID on an exact tie, and score both systems on the same "
    "cluster-row multiset. This targets a hypothetical training-seed "
    "superpopulation and is not the confidence interval for the deployed fixed "
    "five-head ensemble. No prediction or test score tunes the design."
)


def _bootstrap_rng_streams(
    random_seed: int,
    *,
    include_training_seed_stream: bool,
) -> tuple[np.random.Generator, np.random.Generator | None, dict[str, Any]]:
    """Derive reproducible, independent cluster and training-seed RNG streams."""
    root = np.random.SeedSequence(random_seed)
    cluster_sequence, training_seed_sequence = root.spawn(2)
    derivation = {
        "scheme": "numpy_seedsequence_spawn_v1",
        "bit_generator": "PCG64",
        "root_entropy": int(random_seed),
        "cluster_spawn_key": list(cluster_sequence.spawn_key),
        "training_seed_spawn_key": (
            list(training_seed_sequence.spawn_key)
            if include_training_seed_stream
            else None
        ),
    }
    return (
        np.random.default_rng(cluster_sequence),
        (
            np.random.default_rng(training_seed_sequence)
            if include_training_seed_stream
            else None
        ),
        derivation,
    )


def bootstrap_rng_stream_derivation(
    random_seed: int,
    *,
    include_training_seed_stream: bool,
) -> dict[str, Any]:
    """Return the preregistrable RNG-stream derivation without consuming draws."""
    _, _, derivation = _bootstrap_rng_streams(
        random_seed,
        include_training_seed_stream=include_training_seed_stream,
    )
    return derivation


def _cluster_bootstrap_design(
    cluster_ids: np.ndarray,
    y_true: np.ndarray,
    calendar_values: np.ndarray,
    *,
    num_classes: int,
    stratification: str,
) -> tuple[dict[str, np.ndarray], dict[str, Any], list[dict[str, Any]]]:
    """Freeze cluster membership and calendar/majority-label strata."""
    if stratification != BOOTSTRAP_STRATIFICATION:
        raise ValueError(f"unsupported bootstrap stratification {stratification!r}")
    cluster_ids = np.asarray(cluster_ids).astype(str)
    y_true = np.asarray(y_true)
    calendar_values = np.asarray(calendar_values)
    if (
        cluster_ids.ndim != 1
        or y_true.shape != cluster_ids.shape
        or calendar_values.shape != cluster_ids.shape
        or not len(cluster_ids)
    ):
        raise ValueError(
            "cluster_ids, y_true, and calendar_values must be aligned non-empty 1D "
            "arrays"
        )
    if any(not value.strip() for value in cluster_ids):
        raise ValueError("leakage_group_id values must be non-empty")
    integer_labels = y_true.astype(np.int64)
    if not np.array_equal(y_true, integer_labels):
        raise ValueError("bootstrap labels must be integer class IDs")
    if ((integer_labels < 0) | (integer_labels >= num_classes)).any():
        raise ValueError("bootstrap labels fall outside the frozen class map")
    timestamps = pd.to_datetime(calendar_values, errors="coerce", utc=True)
    if pd.isna(timestamps).any():
        raise ValueError("bootstrap calendar values contain missing/invalid timestamps")
    utc_months = np.asarray(timestamps.strftime("%Y-%m"), dtype=str)

    clusters_by_stratum: dict[str, list[str]] = {}
    cluster_rows: list[dict[str, Any]] = []
    for cluster in np.unique(cluster_ids):
        indices = np.flatnonzero(cluster_ids == cluster)
        anchor_month = min(utc_months[indices].tolist())
        labels, counts = np.unique(integer_labels[indices], return_counts=True)
        largest_count = int(counts.max())
        majority_label = int(np.min(labels[counts == largest_count]))
        stratum = f"utc_month={anchor_month}|majority_label={majority_label}"
        clusters_by_stratum.setdefault(stratum, []).append(str(cluster))
        cluster_rows.append(
            {
                "leakage_group_id": str(cluster),
                "utc_anchor_month": anchor_month,
                "majority_label_id": majority_label,
                "row_count": len(indices),
                "class_composition_json": json.dumps(
                    {
                        str(int(label)): int(count)
                        for label, count in zip(labels, counts, strict=True)
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "stratum": stratum,
            }
        )

    frozen_strata = {
        stratum: np.asarray(sorted(clusters), dtype=str)
        for stratum, clusters in sorted(clusters_by_stratum.items())
    }
    canonical_membership = sorted(
        cluster_rows, key=lambda row: str(row["leakage_group_id"])
    )
    membership_sha256 = sha256(
        json.dumps(
            canonical_membership,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    receipt = {
        "bootstrap_algorithm_id": BOOTSTRAP_ALGORITHM_ID,
        "bootstrap_algorithm": BOOTSTRAP_ALGORITHM,
        "bootstrap_stratification": stratification,
        "stratification_calendar_rule": "earliest_utc_calendar_month_in_cluster",
        "stratification_label_rule": (
            "row_count_majority_y_true_with_smallest_class_id_tie_break"
        ),
        "strata_cluster_counts": {
            stratum: len(clusters) for stratum, clusters in frozen_strata.items()
        },
        "cluster_strata_sha256": membership_sha256,
    }
    return frozen_strata, receipt, canonical_membership


def cluster_bootstrap_design_receipt(
    cluster_ids: np.ndarray,
    y_true: np.ndarray,
    calendar_values: np.ndarray,
    *,
    num_classes: int,
    stratification: str = BOOTSTRAP_STRATIFICATION,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the auditable cluster-to-stratum table and its semantic receipt."""
    _, receipt, membership = _cluster_bootstrap_design(
        cluster_ids,
        y_true,
        calendar_values,
        num_classes=num_classes,
        stratification=stratification,
    )
    return membership, receipt


def _cluster_resample_indices(
    cluster_ids: np.ndarray,
    clusters_by_stratum: Mapping[str, np.ndarray],
    rng: np.random.Generator,
) -> np.ndarray:
    sampled_clusters: list[str] = []
    for stratum in sorted(clusters_by_stratum):
        clusters = np.asarray(clusters_by_stratum[stratum]).astype(str)
        sampled_clusters.extend(
            rng.choice(clusters, size=len(clusters), replace=True).tolist()
        )
    return np.concatenate(
        [np.flatnonzero(cluster_ids == cluster) for cluster in sampled_clusters]
    )


def _metric_function(
    name: str, num_classes: int
) -> Callable[[np.ndarray, np.ndarray], float]:
    labels = np.arange(num_classes)
    if name == "accuracy":
        return lambda y, p: float(accuracy_score(y, p))
    if name == "macro_f1":
        return lambda y, p: float(
            f1_score(y, p, labels=labels, average="macro", zero_division=0)
        )
    raise ValueError(f"paired bootstrap does not support metric {name!r}")


def hierarchical_paired_bootstrap(
    reference: Mapping[int, tuple[np.ndarray, np.ndarray]],
    challenger: Mapping[int, tuple[np.ndarray, np.ndarray]],
    *,
    cluster_ids: np.ndarray,
    calendar_values: np.ndarray,
    metric: str,
    num_classes: int,
    iterations: int,
    confidence_level: float,
    random_seed: int,
    stratification: str = BOOTSTRAP_STRATIFICATION,
    _resample_training_seeds: bool = False,
) -> dict[str, Any]:
    """Primary paired cluster bootstrap for the deployed fixed seed ensemble.

    Every draw samples whole leakage groups within frozen UTC-month by
    cluster-majority-label strata and uses the same draw for both models. Every
    preregistered seed is averaged exactly once before argmax, and that deployed
    prediction vector remains fixed across cluster draws. Rows and training seeds
    are never independently resampled in this primary estimand.

    ``_resample_training_seeds`` is private plumbing for the separately named
    secondary sensitivity wrapper below; callers should not use it directly.
    """
    if set(reference) != set(challenger):
        raise ValueError(
            "paired comparison requires identical preregistered seed identities"
        )
    seeds = sorted(reference)
    if not seeds:
        raise ValueError("paired comparison has no common random seeds")
    cluster_ids = np.asarray(cluster_ids).astype(str)
    if cluster_ids.shape != reference[seeds[0]][0].shape:
        raise ValueError("cluster_ids must align with the ordered test cases")
    if len(np.unique(cluster_ids)) < 2:
        raise ValueError("cluster bootstrap requires at least two leakage groups")
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("bootstrap confidence_level must be between 0 and 1")
    reference_probabilities: list[np.ndarray] = []
    challenger_probabilities: list[np.ndarray] = []
    frozen_y_true = np.asarray(reference[seeds[0]][0])
    for seed in seeds:
        ref_y, ref_probabilities = reference[seed]
        alt_y, alt_probabilities = challenger[seed]
        if not np.array_equal(ref_y, alt_y):
            raise ValueError(f"y_true mismatch for paired seed {seed}")
        if not np.array_equal(ref_y, frozen_y_true):
            raise ValueError("all seeds must predict the same ordered test cases")
        ref_probabilities = np.asarray(ref_probabilities, dtype=np.float64)
        alt_probabilities = np.asarray(alt_probabilities, dtype=np.float64)
        expected_shape = (len(frozen_y_true), num_classes)
        if (
            ref_probabilities.shape != expected_shape
            or alt_probabilities.shape != expected_shape
        ):
            raise ValueError(
                f"seed {seed} probability tensors must have shape {expected_shape}"
            )
        for system, probabilities in (
            ("reference", ref_probabilities),
            ("challenger", alt_probabilities),
        ):
            if (
                not np.isfinite(probabilities).all()
                or (probabilities < 0.0).any()
                or (probabilities > 1.0).any()
                or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6)
            ):
                raise ValueError(
                    f"{system} seed {seed} contains invalid class probabilities"
                )
        reference_probabilities.append(ref_probabilities)
        challenger_probabilities.append(alt_probabilities)

    reference_stack = np.stack(reference_probabilities, axis=0)
    challenger_stack = np.stack(challenger_probabilities, axis=0)

    clusters_by_stratum, design_receipt, _ = _cluster_bootstrap_design(
        cluster_ids,
        frozen_y_true,
        calendar_values,
        num_classes=num_classes,
        stratification=stratification,
    )
    if _resample_training_seeds:
        algorithm_id = TRAINING_SEED_SENSITIVITY_ALGORITHM_ID
        algorithm = TRAINING_SEED_SENSITIVITY_ALGORITHM
        analysis_role = "secondary_training_seed_sensitivity"
        estimand = (
            "training_seed_superpopulation_equal_size_probability_ensemble_metric_delta"
        )
        replicate_seed_rule = (
            "sample_preregistered_seed_positions_with_replacement_to_original_size"
        )
    else:
        algorithm_id = BOOTSTRAP_ALGORITHM_ID
        algorithm = BOOTSTRAP_ALGORITHM
        analysis_role = "primary_phase_a_prespecified_interval"
        estimand = "deployed_fixed_preregistered_seed_ensemble_metric_delta"
        replicate_seed_rule = (
            "all_preregistered_seeds_exactly_once_equal_weight_fixed_across_draws"
        )
    design_receipt = {
        **design_receipt,
        "bootstrap_algorithm_id": algorithm_id,
        "bootstrap_algorithm": algorithm,
    }

    score = _metric_function(metric, num_classes)
    reference_point_predictions = reference_stack.mean(axis=0).argmax(axis=1)
    challenger_point_predictions = challenger_stack.mean(axis=0).argmax(axis=1)
    point_delta = score(frozen_y_true, challenger_point_predictions) - score(
        frozen_y_true, reference_point_predictions
    )
    cluster_rng, seed_rng, rng_stream_derivation = _bootstrap_rng_streams(
        random_seed,
        include_training_seed_stream=_resample_training_seeds,
    )
    draws = np.empty(iterations, dtype=np.float64)
    for iteration in range(iterations):
        shared_indices = _cluster_resample_indices(
            cluster_ids, clusters_by_stratum, cluster_rng
        )
        if _resample_training_seeds:
            assert seed_rng is not None
            sampled_seed_positions = seed_rng.integers(0, len(seeds), size=len(seeds))
            reference_draw_predictions = (
                reference_stack[sampled_seed_positions].mean(axis=0).argmax(axis=1)
            )
            challenger_draw_predictions = (
                challenger_stack[sampled_seed_positions].mean(axis=0).argmax(axis=1)
            )
        else:
            reference_draw_predictions = reference_point_predictions
            challenger_draw_predictions = challenger_point_predictions
        draws[iteration] = score(
            frozen_y_true[shared_indices],
            challenger_draw_predictions[shared_indices],
        ) - score(
            frozen_y_true[shared_indices],
            reference_draw_predictions[shared_indices],
        )

    alpha = 1.0 - confidence_level
    lower, upper = np.quantile(draws, [alpha / 2.0, 1.0 - alpha / 2.0])
    probability_nonpositive = float(((draws <= 0.0).sum() + 1) / (iterations + 1))
    probability_nonnegative = float(((draws >= 0.0).sum() + 1) / (iterations + 1))
    return {
        "metric": metric,
        "common_seeds": len(seeds),
        "sampling_unit": "leakage_group_id",
        "n_clusters": len(np.unique(cluster_ids)),
        "iterations": int(iterations),
        "bootstrap_replicates": int(iterations),
        "bootstrap_seed": int(random_seed),
        "bootstrap_rng": (
            "independent numpy.random.Generator(PCG64) child streams derived "
            "by SeedSequence(bootstrap_seed).spawn(2)"
            if _resample_training_seeds
            else "cluster child stream derived by "
            "SeedSequence(bootstrap_seed).spawn(2)[0]"
        ),
        "bootstrap_rng_stream_derivation": rng_stream_derivation,
        "analysis_role": analysis_role,
        "estimand": estimand,
        "probability_aggregation": "arithmetic_mean_before_argmax_and_metric",
        "training_seed_resampling": bool(_resample_training_seeds),
        "replicate_seed_rule": replicate_seed_rule,
        "point_estimate_seed_rule": (
            "all_preregistered_seeds_exactly_once_equal_weight"
        ),
        **design_receipt,
        "strata_cluster_counts_json": json.dumps(
            design_receipt["strata_cluster_counts"],
            sort_keys=True,
            separators=(",", ":"),
        ),
        "delta_challenger_minus_reference": float(point_delta),
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "confidence_level": float(confidence_level),
        "bootstrap_probability_delta_nonpositive": probability_nonpositive,
        "bootstrap_probability_delta_nonnegative": probability_nonnegative,
        "bootstrap_two_sided_tail_probability_descriptive": float(
            min(1.0, 2.0 * min(probability_nonpositive, probability_nonnegative))
        ),
    }


def training_seed_superpopulation_sensitivity_bootstrap(
    reference: Mapping[int, tuple[np.ndarray, np.ndarray]],
    challenger: Mapping[int, tuple[np.ndarray, np.ndarray]],
    *,
    cluster_ids: np.ndarray,
    calendar_values: np.ndarray,
    metric: str,
    num_classes: int,
    iterations: int,
    confidence_level: float,
    random_seed: int,
    stratification: str = BOOTSTRAP_STRATIFICATION,
) -> dict[str, Any]:
    """Secondary seed-superpopulation sensitivity, never the deployed-model CI."""
    return hierarchical_paired_bootstrap(
        reference,
        challenger,
        cluster_ids=cluster_ids,
        calendar_values=calendar_values,
        metric=metric,
        num_classes=num_classes,
        iterations=iterations,
        confidence_level=confidence_level,
        random_seed=random_seed,
        stratification=stratification,
        _resample_training_seeds=True,
    )
