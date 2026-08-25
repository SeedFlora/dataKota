"""Posterior uncertainty from CatBoost virtual ensembles.

CatBoost's ``VirtEnsembles`` output contains one raw approximation for each
virtual ensemble. This module uses one explicit uncertainty definition:

``epistemic_mutual_information = H(E[p(y|x,w)]) - E[H(p(y|x,w))]``

Entropy is measured in nats. Keeping the decomposition makes it impossible to
accidentally relabel probability standard deviation as mutual information in
the serving API.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PGSUncertainty:
    """Posterior predictive probabilities and their entropy decomposition."""

    probabilities: np.ndarray
    epistemic_mutual_information: np.ndarray
    predictive_entropy: np.ndarray
    expected_data_entropy: np.ndarray


def minimum_trees_for_virtual_ensembles(n_virtual_ensembles: int) -> int:
    """Return CatBoost's minimum retained-tree count for VirtEnsembles.

    CatBoost forms virtual ensembles from shrinking prefixes of one posterior-
    sampled model.  The project contract reserves at least ``2 * V + 1`` trees
    so a requested ensemble count cannot silently be reduced at deployment.
    """
    if n_virtual_ensembles < 2:
        raise ValueError("n_virtual_ensembles must be at least 2")
    return 2 * n_virtual_ensembles + 1


def validate_pgs_model(model, n_virtual_ensembles: int) -> int:
    """Validate posterior-sampling and tree-count prerequisites.

    Returns the retained tree count for provenance/health reporting.
    """
    minimum_trees = minimum_trees_for_virtual_ensembles(n_virtual_ensembles)
    params = model.get_all_params()
    if not params.get("posterior_sampling", False):
        raise ValueError("CatBoost model was not trained with posterior_sampling=true")
    retained_trees = int(model.tree_count_)
    if retained_trees < minimum_trees:
        raise ValueError(
            f"CatBoost model retained {retained_trees} trees, but "
            f"{n_virtual_ensembles} virtual ensembles require at least "
            f"{minimum_trees} trees"
        )
    return retained_trees


def pgs_predict(
    model,
    X: np.ndarray,
    n_virtual_ensembles: int = 30,
) -> PGSUncertainty:
    """Predict with CatBoost virtual ensembles.

    ``model`` must be a fitted CatBoost classifier trained with posterior
    sampling enabled. At least two virtual ensembles are required for an
    epistemic comparison; 30 is the project protocol default.
    """
    features = np.asarray(X)
    if features.ndim != 2:
        raise ValueError(f"X must have shape (N, D); got {features.shape}")
    minimum_trees_for_virtual_ensembles(n_virtual_ensembles)

    raw_ensembles = np.asarray(
        model.virtual_ensembles_predict(
            features,
            prediction_type="VirtEnsembles",
            virtual_ensembles_count=n_virtual_ensembles,
            thread_count=-1,
        ),
        dtype=np.float64,
    )
    per_ensemble_probs = _virtual_ensemble_probabilities(
        raw_ensembles,
        expected_rows=features.shape[0],
        expected_ensembles=n_virtual_ensembles,
    )
    mean_probs = per_ensemble_probs.mean(axis=1)
    predictive_entropy = _entropy(mean_probs)
    expected_data_entropy = _entropy(per_ensemble_probs).mean(axis=1)

    # Cancellation can yield a tiny negative value although mutual
    # information is non-negative by definition.
    epistemic = np.maximum(predictive_entropy - expected_data_entropy, 0.0)
    return PGSUncertainty(
        probabilities=mean_probs.astype(np.float32),
        epistemic_mutual_information=epistemic.astype(np.float32),
        predictive_entropy=predictive_entropy.astype(np.float32),
        expected_data_entropy=expected_data_entropy.astype(np.float32),
    )


def pgs_predict_proba(
    model,
    X: np.ndarray,
    n_virtual_ensembles: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """Backward-compatible ``(probabilities, epistemic_mi)`` wrapper.

    The second array is epistemic mutual information in nats. It is not total
    uncertainty and not mean probability standard deviation.
    """
    result = pgs_predict(model, X, n_virtual_ensembles)
    return result.probabilities, result.epistemic_mutual_information


def _virtual_ensemble_probabilities(
    raw: np.ndarray,
    *,
    expected_rows: int,
    expected_ensembles: int,
) -> np.ndarray:
    """Convert CatBoost raw virtual-ensemble approximations to probabilities."""
    if raw.ndim == 2:
        # Some CatBoost binary-classification versions omit the singleton
        # approximation dimension and return (N, V).
        raw = raw[..., None]
    if raw.ndim != 3:
        raise ValueError(f"VirtEnsembles must return shape (N, V, C); got {raw.shape}")
    if raw.shape[0] != expected_rows or raw.shape[1] != expected_ensembles:
        raise ValueError(
            "VirtEnsembles shape does not match the request: "
            f"expected ({expected_rows}, {expected_ensembles}, C), got {raw.shape}"
        )
    if not np.isfinite(raw).all():
        raise ValueError("VirtEnsembles returned NaN or infinite approximations")

    if raw.shape[2] == 1:
        positive = _sigmoid(raw[..., 0])
        return np.stack((1.0 - positive, positive), axis=2)
    return _softmax(raw, axis=2)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid."""
    out = np.empty_like(x, dtype=np.float64)
    positive = x >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1.0 + exp_x)
    return out


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    shifted = x - x.max(axis=axis, keepdims=True)
    ex = np.exp(shifted)
    return ex / ex.sum(axis=axis, keepdims=True)


def _entropy(p: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    clipped = np.clip(p, eps, 1.0)
    return -(p * np.log(clipped)).sum(axis=-1)
