"""Pure helpers that define the deployment prediction contract.

The functions live outside ``serve_model.py`` so probability parsing, review
rules, and parity gates can be unit-tested without loading multi-gigabyte ONNX
artifacts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np

ONNX_SEED_ENSEMBLE_METHOD = "onnx_equal_weight_seed_ensemble"
PGS_SEED_ENSEMBLE_METHOD = "catboost_virtual_ensemble_seed_ensemble"
EPISTEMIC_MI_METHOD = "joint_training_seed_pgs_component_mutual_information_nats"


def normalize_probability_output(
    raw_output,
    class_ids: Sequence[int],
) -> np.ndarray:
    """Return a validated ``(N, C)`` probability matrix from ONNX output.

    CatBoost's ONNX ``ZipMap`` output is commonly a list of dictionaries, but
    ONNX Runtime versions may expose a numeric ndarray instead. Class columns
    are always ordered by ``class_ids`` rather than dictionary iteration order.
    """
    expected_ids = tuple(int(class_id) for class_id in class_ids)
    if len(expected_ids) == 0 or len(set(expected_ids)) != len(expected_ids):
        raise ValueError("class_ids must be non-empty and unique")

    rows = _mapping_rows(raw_output)
    if rows is not None:
        matrix = np.asarray(
            [
                [_mapping_probability(row, class_id) for class_id in expected_ids]
                for row in rows
            ],
            dtype=np.float64,
        )
    else:
        matrix = np.asarray(raw_output, dtype=np.float64)
        if matrix.ndim == 1:
            matrix = matrix[None, :]

    return validate_probability_matrix(matrix, len(expected_ids))


def validate_probability_matrix(
    probabilities: np.ndarray,
    class_count: int,
    *,
    sum_tolerance: float = 1e-5,
) -> np.ndarray:
    """Validate a probability matrix and normalize only rounding-level drift."""
    matrix = np.asarray(probabilities, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != class_count:
        raise ValueError(
            f"expected probability shape (N, {class_count}); got {matrix.shape}"
        )
    if matrix.shape[0] == 0:
        raise ValueError("probability matrix must contain at least one row")
    if not np.isfinite(matrix).all():
        raise ValueError("probabilities contain NaN or infinite values")
    if (matrix < -sum_tolerance).any() or (matrix > 1 + sum_tolerance).any():
        raise ValueError("classifier output is outside the probability range [0, 1]")

    row_sums = matrix.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=sum_tolerance, rtol=0.0):
        raise ValueError(
            "classifier output does not sum to one; raw logits must not be "
            "reported as probabilities"
        )
    matrix = np.clip(matrix, 0.0, 1.0)
    matrix /= matrix.sum(axis=1, keepdims=True)
    return matrix.astype(np.float32)


def equal_weight_probability_mean(
    member_probabilities: Sequence[np.ndarray],
    class_count: int,
    *,
    expected_members: int | None = None,
) -> np.ndarray:
    """Validate and average frozen ensemble members with exactly equal weights."""
    members = list(member_probabilities)
    if not members:
        raise ValueError("seed ensemble must contain at least one probability matrix")
    if expected_members is not None and len(members) != expected_members:
        raise ValueError(
            f"expected {expected_members} seed heads, received {len(members)}"
        )
    validated = [
        validate_probability_matrix(probabilities, class_count)
        for probabilities in members
    ]
    shapes = {probabilities.shape for probabilities in validated}
    if len(shapes) != 1:
        raise ValueError("seed-ensemble probability matrices must share shape")
    return validate_probability_matrix(
        np.mean(np.stack(validated, axis=0), axis=0), class_count
    )


def determine_review_reasons(
    *,
    predicted_label: str,
    confidence: float,
    confidence_threshold: float,
    catch_all_label: str | None = None,
    epistemic_uncertainty: float | None = None,
    epistemic_uncertainty_threshold: float | None = None,
) -> list[str]:
    """Return stable machine-readable reasons for routing to human review."""
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_threshold must be between 0 and 1")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if (
        epistemic_uncertainty_threshold is not None
        and epistemic_uncertainty_threshold < 0.0
    ):
        raise ValueError("epistemic_uncertainty_threshold must be non-negative")

    reasons: list[str] = []
    if confidence < confidence_threshold:
        reasons.append("low_confidence")
    if catch_all_label is not None and predicted_label == catch_all_label:
        reasons.append("catch_all_class")
    if epistemic_uncertainty_threshold is not None:
        if epistemic_uncertainty is None:
            raise ValueError(
                "an epistemic threshold requires uncertainty-enabled inference"
            )
        if epistemic_uncertainty > epistemic_uncertainty_threshold:
            reasons.append("high_epistemic_uncertainty")
    return reasons


@dataclass(frozen=True)
class ParityReport:
    samples: int
    classes: int
    max_absolute_probability_error: float
    mean_absolute_probability_error: float
    p50_absolute_probability_error: float
    p95_absolute_probability_error: float
    p99_absolute_probability_error: float
    top1_agreement: float
    probability_tolerance: float
    minimum_top1_agreement: float
    passed: bool

    def to_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)


def classifier_parity_report(
    reference_probabilities: np.ndarray,
    deployed_probabilities: np.ndarray,
    *,
    probability_tolerance: float = 1e-5,
    minimum_top1_agreement: float = 1.0,
) -> ParityReport:
    """Compare native and deployed classifier predictions with explicit gates."""
    reference = np.asarray(reference_probabilities, dtype=np.float64)
    deployed = np.asarray(deployed_probabilities, dtype=np.float64)
    if reference.shape != deployed.shape or reference.ndim != 2:
        raise ValueError(
            "reference and deployed probabilities must share shape (N, C); "
            f"got {reference.shape} and {deployed.shape}"
        )
    if not 0.0 <= minimum_top1_agreement <= 1.0:
        raise ValueError("minimum_top1_agreement must be between 0 and 1")
    if probability_tolerance < 0.0:
        raise ValueError("probability_tolerance must be non-negative")
    reference = validate_probability_matrix(reference, reference.shape[1])
    deployed = validate_probability_matrix(deployed, deployed.shape[1])

    absolute_error = np.abs(reference - deployed)
    top1_agreement = float(
        np.mean(np.argmax(reference, axis=1) == np.argmax(deployed, axis=1))
    )
    maximum_error = float(absolute_error.max())
    return ParityReport(
        samples=int(reference.shape[0]),
        classes=int(reference.shape[1]),
        max_absolute_probability_error=maximum_error,
        mean_absolute_probability_error=float(absolute_error.mean()),
        p50_absolute_probability_error=float(np.percentile(absolute_error, 50)),
        p95_absolute_probability_error=float(np.percentile(absolute_error, 95)),
        p99_absolute_probability_error=float(np.percentile(absolute_error, 99)),
        top1_agreement=top1_agreement,
        probability_tolerance=float(probability_tolerance),
        minimum_top1_agreement=float(minimum_top1_agreement),
        passed=(
            maximum_error <= probability_tolerance
            and top1_agreement >= minimum_top1_agreement
        ),
    )


def _mapping_rows(raw_output) -> list[Mapping] | None:
    if isinstance(raw_output, Mapping):
        return [raw_output]
    if (
        isinstance(raw_output, (list, tuple))
        and raw_output
        and all(isinstance(row, Mapping) for row in raw_output)
    ):
        return list(raw_output)
    if isinstance(raw_output, np.ndarray) and raw_output.dtype == object:
        flat = raw_output.reshape(-1).tolist()
        if flat and all(isinstance(row, Mapping) for row in flat):
            return flat
    return None


def _mapping_probability(row: Mapping, class_id: int) -> float:
    if class_id in row:
        return float(row[class_id])
    string_id = str(class_id)
    if string_id in row:
        return float(row[string_id])
    raise ValueError(f"classifier probability map is missing class id {class_id}")
