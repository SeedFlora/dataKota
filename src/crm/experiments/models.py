"""Matched-budget model fitting and prediction adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import joblib
import numpy as np
from catboost import CatBoostClassifier
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from crm.fusion import class_weights
from crm.pgs import minimum_trees_for_virtual_ensembles, pgs_predict

from .config import CandidateConfig, ExperimentConfig
from .metrics import predictive_entropy


@dataclass
class FittedModel:
    estimator: Any
    candidate: CandidateConfig
    seed: int
    fit_seconds: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PredictionBundle:
    probabilities: np.ndarray
    predictions: np.ndarray
    uncertainty: dict[str, np.ndarray]
    probability_semantics: str


@dataclass
class LateFusionCatBoost:
    image_model: CatBoostClassifier
    text_model: CatBoostClassifier
    image_weight: float

    def predict_proba(self, features: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
        if not isinstance(features, tuple) or len(features) != 2:
            raise ValueError("late fusion requires (image_features, text_features)")
        image_features, text_features = features
        image_probabilities = self.image_model.predict_proba(image_features)
        text_probabilities = self.text_model.predict_proba(text_features)
        return (
            self.image_weight * image_probabilities
            + (1.0 - self.image_weight) * text_probabilities
        )


def catboost_parameters(
    config: ExperimentConfig,
    candidate: CandidateConfig,
    seed: int,
) -> dict[str, Any]:
    """Build the fixed budget; only the declared training treatment may differ."""
    budget = config.catboost
    parameters: dict[str, Any] = {
        "iterations": budget.iterations,
        "learning_rate": budget.learning_rate,
        "depth": budget.depth,
        "l2_leaf_reg": budget.l2_leaf_reg,
        "loss_function": "MultiClass",
        "eval_metric": budget.eval_metric,
        "task_type": "CPU",
        "thread_count": budget.thread_count,
        "random_seed": seed,
        "posterior_sampling": candidate.posterior_sampling,
        "allow_writing_files": False,
        "verbose": False,
    }
    if candidate.model == "catboost":
        parameters.update(candidate.params)
    return parameters


def fit_candidate(
    config: ExperimentConfig,
    candidate: CandidateConfig,
    seed: int,
    X_train: Any,
    y_train: np.ndarray,
    X_val: Any,
    y_val: np.ndarray,
) -> FittedModel:
    """Fit on train and use validation only for early stopping/selection."""
    started = perf_counter()
    metadata: dict[str, Any]
    if candidate.model == "catboost":
        weights = class_weights(y_train, config.expected_num_classes)
        parameters = catboost_parameters(config, candidate, seed)
        parameters["class_weights"] = [
            weights[index] for index in range(config.expected_num_classes)
        ]
        estimator = CatBoostClassifier(**parameters)
        estimator.fit(
            X_train,
            y_train,
            eval_set=(X_val, y_val),
            # Keep the identical post-best patience trajectory and the complete
            # resulting checkpoint for both treatments. PGS needs the trailing
            # trees as virtual posterior samples; trimming only the point model
            # would introduce a second, avoidable inference-tree treatment.
            use_best_model=False,
            early_stopping_rounds=config.catboost.early_stopping_rounds,
            verbose=False,
        )
        best_iteration = int(estimator.get_best_iteration())
        trained_tree_count = int(estimator.tree_count_)
        metadata = {
            "parameters": parameters,
            "early_stopping_rounds": config.catboost.early_stopping_rounds,
            "use_best_model_during_fit": False,
            "best_iteration": best_iteration,
            "trained_tree_count": trained_tree_count,
            "inference_tree_count": int(estimator.tree_count_),
            "checkpoint_tree_policy": config.catboost.checkpoint_tree_policy,
            "point_model_trimmed_to_validation_best": False,
            "best_score": estimator.get_best_score(),
        }
    elif candidate.model == "late_fusion_catboost":
        if not isinstance(X_train, tuple) or not isinstance(X_val, tuple):
            raise ValueError("late_fusion_catboost requires modality feature tuples")
        image_train, text_train = X_train
        image_val, text_val = X_val
        weights = class_weights(y_train, config.expected_num_classes)
        parameters = catboost_parameters(config, candidate, seed)
        parameters["class_weights"] = [
            weights[index] for index in range(config.expected_num_classes)
        ]

        def fit_modality(features_train, features_val):
            model = CatBoostClassifier(**parameters)
            model.fit(
                features_train,
                y_train,
                eval_set=(features_val, y_val),
                use_best_model=True,
                early_stopping_rounds=config.catboost.early_stopping_rounds,
                verbose=False,
            )
            return model

        image_model = fit_modality(image_train, image_val)
        text_model = fit_modality(text_train, text_val)
        params = dict(candidate.params)
        alpha_grid = tuple(
            float(value)
            for value in params.pop("image_weight_grid", [0.0, 0.25, 0.5, 0.75, 1.0])
        )
        _reject_unknown_params(candidate, params)
        if not alpha_grid or any(not 0.0 <= value <= 1.0 for value in alpha_grid):
            raise ValueError("image_weight_grid values must lie in [0, 1]")
        image_probabilities = image_model.predict_proba(image_val)
        text_probabilities = text_model.predict_proba(text_val)
        grid_scores: list[dict[str, float]] = []
        for image_weight in sorted(set(alpha_grid)):
            probabilities = (
                image_weight * image_probabilities
                + (1.0 - image_weight) * text_probabilities
            )
            score = f1_score(
                y_val,
                probabilities.argmax(axis=1),
                labels=np.arange(config.expected_num_classes),
                average="macro",
                zero_division=0,
            )
            grid_scores.append(
                {
                    "image_weight": float(image_weight),
                    "validation_macro_f1": float(score),
                }
            )
        selected = min(
            grid_scores,
            key=lambda item: (
                -item["validation_macro_f1"],
                abs(item["image_weight"] - 0.5),
                item["image_weight"],
            ),
        )
        estimator = LateFusionCatBoost(
            image_model=image_model,
            text_model=text_model,
            image_weight=selected["image_weight"],
        )
        metadata = {
            "parameters": parameters,
            "image_weight_selection_split": "validation",
            "selected_image_weight": selected["image_weight"],
            "weight_grid_results": grid_scores,
            "image_best_iteration": int(image_model.get_best_iteration()),
            "text_best_iteration": int(text_model.get_best_iteration()),
            "image_tree_count": int(image_model.tree_count_),
            "text_tree_count": int(text_model.tree_count_),
        }
    elif candidate.model == "logistic_regression":
        params = dict(candidate.params)
        resolved_params = {
            "C": float(params.pop("C", 1.0)),
            "max_iter": int(params.pop("max_iter", 2000)),
            "tol": float(params.pop("tol", 1e-4)),
            "solver": str(params.pop("solver", "lbfgs")),
            "class_weight": "balanced",
            "random_state": seed,
            "scale_with_mean": False,
        }
        estimator = Pipeline(
            [
                ("scale", StandardScaler(with_mean=False)),
                (
                    "classifier",
                    LogisticRegression(
                        C=resolved_params["C"],
                        max_iter=resolved_params["max_iter"],
                        tol=resolved_params["tol"],
                        solver=resolved_params["solver"],
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        )
        _reject_unknown_params(candidate, params)
        estimator.fit(X_train, y_train)
        metadata = {"parameters": resolved_params}
    elif candidate.model == "tfidf_logistic":
        params = dict(candidate.params)
        resolved_params = {
            "ngram_min": int(params.pop("ngram_min", 1)),
            "ngram_max": int(params.pop("ngram_max", 2)),
            "min_df": int(params.pop("min_df", 2)),
            "max_features": int(params.pop("max_features", 100_000)),
            "sublinear_tf": bool(params.pop("sublinear_tf", True)),
            "C": float(params.pop("C", 1.0)),
            "max_iter": int(params.pop("max_iter", 2000)),
            "class_weight": "balanced",
            "random_state": seed,
        }
        _reject_unknown_params(candidate, params)
        estimator = Pipeline(
            [
                (
                    "tfidf",
                    TfidfVectorizer(
                        analyzer="word",
                        ngram_range=(
                            resolved_params["ngram_min"],
                            resolved_params["ngram_max"],
                        ),
                        min_df=resolved_params["min_df"],
                        max_features=resolved_params["max_features"],
                        sublinear_tf=resolved_params["sublinear_tf"],
                        lowercase=True,
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        C=resolved_params["C"],
                        max_iter=resolved_params["max_iter"],
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        )
        estimator.fit(X_train, y_train)
        metadata = {"parameters": resolved_params}
    elif candidate.model == "sgd_logistic":
        params = dict(candidate.params)
        resolved_params = {
            "loss": "log_loss",
            "alpha": float(params.pop("alpha", 1e-4)),
            "max_iter": int(params.pop("max_iter", 2000)),
            "tol": float(params.pop("tol", 1e-4)),
            "average": bool(params.pop("average", True)),
            "class_weight": "balanced",
            "early_stopping": False,
            "random_state": seed,
            "scale_with_mean": False,
        }
        estimator = Pipeline(
            [
                ("scale", StandardScaler(with_mean=False)),
                (
                    "classifier",
                    SGDClassifier(
                        loss=resolved_params["loss"],
                        alpha=resolved_params["alpha"],
                        max_iter=resolved_params["max_iter"],
                        tol=resolved_params["tol"],
                        average=resolved_params["average"],
                        class_weight="balanced",
                        early_stopping=False,
                        random_state=seed,
                    ),
                ),
            ]
        )
        _reject_unknown_params(candidate, params)
        estimator.fit(X_train, y_train)
        metadata = {"parameters": resolved_params}
    elif candidate.model == "dummy_prior":
        params = dict(candidate.params)
        _reject_unknown_params(candidate, params)
        estimator = DummyClassifier(strategy="prior", random_state=seed)
        estimator.fit(X_train, y_train)
        metadata = {"parameters": {"strategy": "prior"}}
    elif candidate.model == "dummy_stratified":
        params = dict(candidate.params)
        _reject_unknown_params(candidate, params)
        estimator = DummyClassifier(strategy="stratified", random_state=seed)
        estimator.fit(X_train, y_train)
        metadata = {"parameters": {"strategy": "stratified", "random_state": seed}}
    else:  # guarded by config validation
        raise ValueError(f"unsupported model kind {candidate.model!r}")
    return FittedModel(
        estimator=estimator,
        candidate=candidate,
        seed=seed,
        fit_seconds=float(perf_counter() - started),
        metadata=metadata,
    )


def _reject_unknown_params(
    candidate: CandidateConfig, remaining: dict[str, Any]
) -> None:
    if remaining:
        raise ValueError(
            f"candidate {candidate.name!r} has unsupported params: {sorted(remaining)}"
        )


def predict_candidate(
    fitted: FittedModel,
    X: Any,
    *,
    virtual_ensembles: int,
) -> PredictionBundle:
    if fitted.candidate.model == "catboost" and fitted.candidate.posterior_sampling:
        minimum_trees = minimum_trees_for_virtual_ensembles(virtual_ensembles)
        retained_trees = int(fitted.estimator.tree_count_)
        if retained_trees < minimum_trees:
            raise RuntimeError(
                f"PGS candidate {fitted.candidate.name!r} retained {retained_trees} "
                f"trees, but {virtual_ensembles} preregistered virtual ensembles "
                f"require at least {minimum_trees}. Start a new selection run with "
                "a larger matched iteration/early-stopping budget; do not lower the "
                "ensemble count after seeing results."
            )
        posterior = pgs_predict(
            fitted.estimator,
            X,
            n_virtual_ensembles=virtual_ensembles,
        )
        probabilities = np.asarray(posterior.probabilities, dtype=np.float64)
        expected_data_entropy = np.asarray(
            posterior.expected_data_entropy, dtype=np.float64
        )
        semantics = "posterior_mean_virtual_ensemble_probability"
    else:
        probabilities = np.asarray(fitted.estimator.predict_proba(X), dtype=np.float64)
        semantics = (
            "validation_weighted_probability_late_fusion"
            if fitted.candidate.model == "late_fusion_catboost"
            else "point_model_probability"
        )
    probabilities = _normalized_probability_matrix(probabilities)
    entropy = predictive_entropy(probabilities)
    if fitted.candidate.model == "catboost" and fitted.candidate.posterior_sampling:
        uncertainty = {
            "predictive_entropy": entropy,
            "expected_data_entropy": expected_data_entropy,
            "epistemic_mutual_information": np.maximum(
                entropy - expected_data_entropy,
                0.0,
            ),
        }
    else:
        uncertainty = {
            "predictive_entropy": entropy,
            "one_minus_confidence": 1.0 - probabilities.max(axis=1),
        }
    predictions = probabilities.argmax(axis=1).astype(np.int64)
    return PredictionBundle(
        probabilities=probabilities,
        predictions=predictions,
        uncertainty=uncertainty,
        probability_semantics=semantics,
    )


def predict_native_point_from_posterior_checkpoint(
    fitted: FittedModel,
    X: Any,
) -> PredictionBundle:
    """Run native point inference on the exact posterior-trained checkpoint.

    This adapter exists only for the matched-checkpoint inference ablation.  It
    deliberately reuses the already loaded posterior-sampling estimator, so the
    native and VirtEnsembles arms cannot differ in training data, random seed,
    serialized checkpoint, or retained tree count.
    """
    if fitted.candidate.model != "catboost" or not fitted.candidate.posterior_sampling:
        raise ValueError(
            "matched-checkpoint native inference requires a posterior-sampling "
            "CatBoost checkpoint"
        )
    checkpoint_tree_count = int(fitted.estimator.tree_count_)
    recorded_tree_count = fitted.metadata.get("inference_tree_count")
    if (
        isinstance(recorded_tree_count, bool)
        or not isinstance(recorded_tree_count, int)
        or recorded_tree_count != checkpoint_tree_count
    ):
        raise RuntimeError(
            "loaded posterior checkpoint tree count differs from its frozen "
            "selection metadata"
        )
    probabilities = _normalized_probability_matrix(
        np.asarray(fitted.estimator.predict_proba(X), dtype=np.float64)
    )
    return PredictionBundle(
        probabilities=probabilities,
        predictions=probabilities.argmax(axis=1).astype(np.int64),
        uncertainty={
            "predictive_entropy": predictive_entropy(probabilities),
            "one_minus_confidence": 1.0 - probabilities.max(axis=1),
        },
        probability_semantics=(
            "native_point_probability_from_same_posterior_sampling_checkpoint"
        ),
    )


def _normalized_probability_matrix(probabilities: np.ndarray) -> np.ndarray:
    if probabilities.ndim != 2 or not np.isfinite(probabilities).all():
        raise RuntimeError("classifier returned a non-finite probability matrix")
    if (probabilities < -1e-8).any() or (probabilities > 1.0 + 1e-8).any():
        raise RuntimeError("classifier returned probabilities outside [0, 1]")
    normalized = np.clip(probabilities, 0.0, 1.0)
    row_sums = normalized.sum(axis=1, keepdims=True)
    if (row_sums <= 0.0).any():
        raise RuntimeError("classifier returned a zero-sum probability row")
    return normalized / row_sums


def save_fitted_model(fitted: FittedModel, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fitted.candidate.model == "catboost":
        target = path.with_suffix(".cbm")
        fitted.estimator.save_model(target)
    else:
        target = path.with_suffix(".joblib")
        joblib.dump(fitted.estimator, target)
    return target


def load_fitted_model(
    candidate: CandidateConfig,
    seed: int,
    path: Path,
    metadata: dict[str, Any],
) -> FittedModel:
    if candidate.model == "catboost":
        estimator = CatBoostClassifier()
        estimator.load_model(path)
    else:
        estimator = joblib.load(path)
    return FittedModel(
        estimator=estimator,
        candidate=candidate,
        seed=seed,
        fit_seconds=float(metadata.get("fit_seconds", 0.0)),
        metadata=metadata.get("model_metadata", {}),
    )
