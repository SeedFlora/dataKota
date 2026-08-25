"""Two-phase validation-selection and one-shot locked-test orchestration."""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crm.deployment import EPISTEMIC_MI_METHOD

from .artifacts import (
    artifact_record,
    create_once_marker,
    environment_manifest,
    object_sha256,
    prediction_frame,
    read_json,
    resolve_artifact_path,
    utc_now,
    write_json,
    write_prediction_csv,
)
from .config import CandidateConfig, ExperimentConfig, load_resolved_config
from .data import (
    EmbeddingStore,
    audit_split_leakage,
    build_input_manifest,
    load_locked_test_splits,
    load_selection_splits,
    sha256_file,
    verify_input_manifest,
)
from .metrics import (
    BOOTSTRAP_ALGORITHM,
    BOOTSTRAP_ALGORITHM_ID,
    TRAINING_SEED_SENSITIVITY_ALGORITHM,
    TRAINING_SEED_SENSITIVITY_ALGORITHM_ID,
    bootstrap_rng_stream_derivation,
    classification_metrics,
    cluster_bootstrap_design_receipt,
    cluster_paired_accuracy_test,
    confusion_matrix_rows,
    hierarchical_paired_bootstrap,
    holm_adjusted_pvalues,
    reliability_bin_rows,
    risk_at_acceptance_mask,
    risk_at_uncertainty_threshold,
    risk_coverage_rows,
    training_seed_superpopulation_sensitivity_bootstrap,
    uncertainty_quality,
    uncertainty_threshold_at_target_coverage,
)
from .models import (
    FittedModel,
    PredictionBundle,
    fit_candidate,
    load_fitted_model,
    predict_candidate,
    predict_native_point_from_posterior_checkpoint,
    save_fitted_model,
)


class ProtocolStateError(RuntimeError):
    """Raised when a run attempts to bypass the frozen two-phase protocol."""


_REQUIRED_UNIT_ARTIFACTS = {
    "checkpoint",
    "predictions",
    "per_class_metrics",
    "risk_coverage",
    "reliability_bins",
    "confusion_matrix_counts",
    "confusion_matrix_row_normalized",
}


def _default_run_dir(config: ExperimentConfig) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return config.output_root / config.experiment_name / timestamp


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)


def _snapshot_path(run_dir: Path) -> Path:
    return run_dir / "resolved_config.json"


def _prepare_selection_run(
    config: ExperimentConfig,
    run_dir: Path | None,
    *,
    resume: bool,
) -> tuple[Path, dict[str, Any]]:
    target = (run_dir or _default_run_dir(config)).resolve()
    snapshot = _snapshot_path(target)
    receipt = target / "selection" / "selection_receipt.json"
    if target.exists():
        if not resume:
            raise ProtocolStateError(
                f"run directory already exists; use --resume only for interrupted "
                f"selection: {target}"
            )
        if receipt.exists():
            raise ProtocolStateError(
                "selection is already frozen; create a new run to change/retrain models"
            )
        if not snapshot.is_file():
            raise ProtocolStateError(f"cannot resume run without {snapshot}")
        frozen = load_resolved_config(snapshot)
        if frozen.protocol_digest() != config.protocol_digest():
            raise ProtocolStateError("resume config differs from the frozen run config")
        manifest = read_json(target / "metadata" / "input_manifest.json")
        verify_input_manifest(manifest)
        return target, manifest

    target.mkdir(parents=True)
    write_json(snapshot, config.resolved_dict())
    write_json(
        target / "metadata" / "environment.json",
        environment_manifest(_project_root()),
    )
    manifest = build_input_manifest(config)
    write_json(target / "metadata" / "input_manifest.json", manifest)
    write_json(
        target / "metadata" / "run_state.json",
        {
            "created_at_utc": utc_now(),
            "phase": "selection_started",
            "protocol_digest": config.protocol_digest(),
            "test_csv_parsed": False,
        },
    )
    return target, manifest


def _feature_pair(
    store: EmbeddingStore,
    candidate: CandidateConfig,
    train: pd.DataFrame,
    evaluation: pd.DataFrame,
    cache: dict[tuple[str, str | None, str | None, str], Any],
    evaluation_name: str,
) -> tuple[Any, Any]:
    key = (candidate.model, candidate.image_encoder, candidate.text_encoder)
    train_key = (*key, "train")
    eval_key = (*key, evaluation_name)

    def build(frame: pd.DataFrame) -> Any:
        if candidate.model == "tfidf_logistic":
            if config_text_column := store.config.text_column:
                return frame[config_text_column].fillna("").astype(str).to_numpy()
            raise ProtocolStateError("tfidf_logistic requires data.text_column")
        if candidate.model == "late_fusion_catboost":
            return store.build_modalities(candidate, frame)
        return store.build(candidate, frame)

    if train_key not in cache:
        cache[train_key] = build(train)
    if eval_key not in cache:
        cache[eval_key] = build(evaluation)
    return cache[train_key], cache[eval_key]


def _evaluate_prediction(
    config: ExperimentConfig,
    y_true: np.ndarray,
    prediction: PredictionBundle,
    *,
    derive_risk_thresholds: bool,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    metrics, per_class = classification_metrics(
        y_true,
        prediction.probabilities,
        num_classes=config.expected_num_classes,
        ece_bins=config.ece_bins,
        ece_family=config.ece_family,
        ece_binning=config.ece_binning,
        ece_bin_interval_semantics=config.ece_bin_interval_semantics,
    )
    risk_rows: list[dict[str, Any]] = []
    for uncertainty_name, values in prediction.uncertainty.items():
        quality = uncertainty_quality(y_true, prediction.predictions, values)
        for metric_name, value in quality.items():
            metrics[f"{uncertainty_name}_{metric_name}"] = value
        if derive_risk_thresholds:
            for row in risk_coverage_rows(
                y_true,
                prediction.predictions,
                values,
                config.coverage_points,
                num_classes=config.expected_num_classes,
            ):
                risk_rows.append({"uncertainty": uncertainty_name, **row})
    metrics["probability_semantics"] = prediction.probability_semantics
    reliability = reliability_bin_rows(
        y_true,
        prediction.probabilities,
        bins=config.ece_bins,
        family=config.ece_family,
        binning=config.ece_binning,
        interval_semantics=config.ece_bin_interval_semantics,
    )
    return metrics, per_class, risk_rows, reliability


def _unit_paths(
    run_dir: Path, phase: str, candidate: str, seed: int
) -> dict[str, Path]:
    directory = run_dir / phase / candidate / f"seed_{seed}"
    return {
        "directory": directory,
        "receipt": directory / "unit_receipt.json",
        "predictions": directory / "predictions.csv.gz",
        "per_class": directory / "per_class_metrics.csv",
        "risk_coverage": directory / "risk_coverage.csv",
        "reliability_bins": directory / "reliability_bins.csv",
        "confusion_counts": directory / "confusion_matrix_counts.csv",
        "confusion_row_normalized": directory / "confusion_matrix_row_normalized.csv",
        "model_base": directory / "model",
    }


def _write_evaluation_unit(
    config: ExperimentConfig,
    *,
    run_dir: Path,
    phase: str,
    candidate: CandidateConfig,
    seed: int,
    split: pd.DataFrame,
    prediction: PredictionBundle,
    fitted: FittedModel | None,
    checkpoint: Path,
    class_map_digest: str,
) -> dict[str, Any]:
    paths = _unit_paths(run_dir, phase, candidate.name, seed)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    y_true = split[config.label_column].to_numpy(dtype=np.int64)
    metrics, per_class, risk_rows, reliability = _evaluate_prediction(
        config,
        y_true,
        prediction,
        derive_risk_thresholds=phase == "selection",
    )
    predictions = prediction_frame(
        split,
        id_column=config.id_column,
        label_column=config.label_column,
        prediction=prediction,
        metadata_columns=(
            config.embedding_index_column,
            config.label_name_column,
            *config.group_columns,
        ),
    )
    write_prediction_csv(paths["predictions"], predictions)
    pd.DataFrame(per_class).to_csv(paths["per_class"], index=False)
    pd.DataFrame(
        risk_rows,
        columns=(
            "uncertainty",
            "target_coverage",
            "realized_coverage",
            "retained",
            "selective_risk",
            "selective_macro_f1",
            "uncertainty_threshold",
        ),
    ).to_csv(paths["risk_coverage"], index=False)
    pd.DataFrame(reliability).to_csv(paths["reliability_bins"], index=False)
    confusion_counts, confusion_normalized = confusion_matrix_rows(
        y_true,
        prediction.predictions,
        num_classes=config.expected_num_classes,
    )
    pd.DataFrame(confusion_counts).to_csv(paths["confusion_counts"], index=False)
    pd.DataFrame(confusion_normalized).to_csv(
        paths["confusion_row_normalized"], index=False
    )
    model_metadata = fitted.metadata if fitted is not None else {}
    fit_seconds = fitted.fit_seconds if fitted is not None else None
    receipt = {
        "schema_version": 1,
        "phase": phase,
        "completed_at_utc": utc_now(),
        "protocol_digest": config.protocol_digest(),
        "class_map_sha256": class_map_digest,
        "candidate": candidate.name,
        "model": candidate.model,
        "image_encoder": candidate.image_encoder,
        "text_encoder": candidate.text_encoder,
        "posterior_sampling": candidate.posterior_sampling,
        "seed": seed,
        "fit_seconds": fit_seconds,
        "model_metadata": model_metadata,
        "metrics": metrics,
        "risk_coverage_threshold_source": (
            "evaluation_split_descriptive"
            if phase == "selection"
            else "none_test_threshold_fitting_forbidden"
        ),
        "artifacts": {
            "checkpoint": artifact_record(checkpoint, base_dir=run_dir),
            "predictions": artifact_record(paths["predictions"], base_dir=run_dir),
            "per_class_metrics": artifact_record(paths["per_class"], base_dir=run_dir),
            "risk_coverage": artifact_record(paths["risk_coverage"], base_dir=run_dir),
            "reliability_bins": artifact_record(
                paths["reliability_bins"], base_dir=run_dir
            ),
            "confusion_matrix_counts": artifact_record(
                paths["confusion_counts"], base_dir=run_dir
            ),
            "confusion_matrix_row_normalized": artifact_record(
                paths["confusion_row_normalized"], base_dir=run_dir
            ),
        },
    }
    receipt["receipt_digest"] = object_sha256(receipt)
    write_json(paths["receipt"], receipt)
    return receipt


def _completed_selection_unit(
    config: ExperimentConfig,
    run_dir: Path,
    candidate: CandidateConfig,
    seed: int,
    *,
    class_map_digest: str,
) -> dict[str, Any] | None:
    receipt_path = _unit_paths(run_dir, "selection", candidate.name, seed)["receipt"]
    if not receipt_path.is_file():
        return None
    receipt = read_json(receipt_path)
    stored_digest = receipt.pop("receipt_digest", None)
    if stored_digest != object_sha256(receipt):
        raise ProtocolStateError(
            f"existing selection unit receipt digest mismatch: {receipt_path}"
        )
    receipt["receipt_digest"] = stored_digest
    expected_identity = {
        "phase": "selection",
        "protocol_digest": config.protocol_digest(),
        "class_map_sha256": class_map_digest,
        "candidate": candidate.name,
        "model": candidate.model,
        "image_encoder": candidate.image_encoder,
        "text_encoder": candidate.text_encoder,
        "posterior_sampling": candidate.posterior_sampling,
        "seed": seed,
    }
    mismatched = {
        key: {"expected": expected, "observed": receipt.get(key)}
        for key, expected in expected_identity.items()
        if receipt.get(key) != expected
    }
    if mismatched:
        raise ProtocolStateError(
            f"existing selection unit has incompatible identity: {mismatched}"
        )
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or not _REQUIRED_UNIT_ARTIFACTS.issubset(
        artifacts
    ):
        missing = sorted(
            _REQUIRED_UNIT_ARTIFACTS.difference(
                artifacts if isinstance(artifacts, dict) else {}
            )
        )
        raise ProtocolStateError(
            f"existing selection unit receipt lacks required artifacts: {missing}"
        )
    for artifact in artifacts.values():
        path = resolve_artifact_path(artifact, base_dir=run_dir)
        if not path.is_file() or sha256_file(path) != artifact["sha256"]:
            raise ProtocolStateError(
                f"existing selection unit artifact changed: {path}"
            )
    return receipt


def _write_unit_index(
    run_dir: Path,
    phase: str,
    unit_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    for receipt in sorted(
        unit_receipts, key=lambda item: (item["candidate"], int(item["seed"]))
    ):
        receipt_path = _unit_paths(
            run_dir, phase, receipt["candidate"], int(receipt["seed"])
        )["receipt"]
        units.append(
            {
                "candidate": receipt["candidate"],
                "seed": int(receipt["seed"]),
                "unit_receipt": artifact_record(receipt_path, base_dir=run_dir),
                "unit_artifacts": receipt["artifacts"],
            }
        )
    index = {
        "schema_version": 1,
        "phase": phase,
        "created_at_utc": utc_now(),
        "units": units,
    }
    index["content_digest"] = object_sha256(index)
    index_path = run_dir / phase / "unit_artifact_index.json"
    write_json(index_path, index)
    return artifact_record(index_path, base_dir=run_dir)


def _verify_unit_index(run_dir: Path, record: dict[str, Any]) -> None:
    index_path = resolve_artifact_path(record, base_dir=run_dir)
    if not index_path.is_file() or sha256_file(index_path) != record["sha256"]:
        raise ProtocolStateError(f"unit artifact index changed: {index_path}")
    index = read_json(index_path)
    stored_digest = index.pop("content_digest", None)
    if stored_digest != object_sha256(index):
        raise ProtocolStateError("unit artifact index content digest mismatch")
    for unit in index.get("units", []):
        receipt_record = unit["unit_receipt"]
        receipt_path = resolve_artifact_path(receipt_record, base_dir=run_dir)
        for artifact in [receipt_record, *unit["unit_artifacts"].values()]:
            path = resolve_artifact_path(artifact, base_dir=run_dir)
            if not path.is_file() or sha256_file(path) != artifact["sha256"]:
                raise ProtocolStateError(f"indexed unit artifact changed: {path}")
        receipt = read_json(receipt_path)
        unit_digest = receipt.pop("receipt_digest", None)
        if unit_digest != object_sha256(receipt):
            raise ProtocolStateError(
                f"indexed unit receipt digest mismatch: {receipt_path}"
            )
        if (
            receipt.get("candidate") != unit.get("candidate")
            or receipt.get("seed") != unit.get("seed")
            or receipt.get("phase") != index.get("phase")
            or receipt.get("artifacts") != unit.get("unit_artifacts")
        ):
            raise ProtocolStateError(
                f"unit index identity/artifact mirror mismatch: {receipt_path}"
            )
        artifacts = receipt.get("artifacts", {})
        if not _REQUIRED_UNIT_ARTIFACTS.issubset(artifacts):
            raise ProtocolStateError(
                f"indexed unit receipt lacks required artifacts: {receipt_path}"
            )


def _load_unit_prediction(
    config: ExperimentConfig,
    run_dir: Path,
    split: pd.DataFrame,
    receipt: dict[str, Any],
) -> PredictionBundle:
    """Load one frozen unit's ordered prediction bundle from its hashed CSV.

    Selection is deliberately reconstructed from persisted predictions, including
    after an interrupted/resumed run.  This avoids an in-memory/non-resume branch
    that could produce a different winner because of serialization or row order.
    """
    record = receipt.get("artifacts", {}).get("predictions")
    if not isinstance(record, dict):
        raise ProtocolStateError("unit receipt lacks its predictions artifact")
    path = resolve_artifact_path(record, base_dir=run_dir)
    if (
        not path.is_file()
        or path.stat().st_size != record.get("size_bytes")
        or sha256_file(path) != record.get("sha256")
    ):
        raise ProtocolStateError(f"frozen prediction artifact changed: {path}")
    frame = pd.read_csv(path)
    expected_ids = split[config.id_column].astype(str).tolist()
    observed_ids = frame.get(config.id_column)
    if observed_ids is None or observed_ids.astype(str).tolist() != expected_ids:
        raise ProtocolStateError(
            f"prediction row order differs from the frozen validation split: {path}"
        )
    expected_y = split[config.label_column].to_numpy(dtype=np.int64)
    if "y_true" not in frame or not np.array_equal(
        frame["y_true"].to_numpy(dtype=np.int64), expected_y
    ):
        raise ProtocolStateError(f"prediction labels differ from validation: {path}")
    probability_columns = [
        f"prob_{class_id}" for class_id in range(config.expected_num_classes)
    ]
    if any(column not in frame for column in probability_columns):
        raise ProtocolStateError(f"prediction probabilities are incomplete: {path}")
    probabilities = frame[probability_columns].to_numpy(dtype=np.float64)
    if (
        probabilities.shape != (len(split), config.expected_num_classes)
        or not np.isfinite(probabilities).all()
        or (probabilities < -1e-8).any()
        or (probabilities > 1.0 + 1e-8).any()
        or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0)
    ):
        raise ProtocolStateError(f"invalid probability matrix in {path}")
    probabilities = np.clip(probabilities, 0.0, 1.0)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    predictions = probabilities.argmax(axis=1).astype(np.int64)
    if "y_pred" not in frame or not np.array_equal(
        frame["y_pred"].to_numpy(dtype=np.int64), predictions
    ):
        raise ProtocolStateError(
            f"prediction argmax differs from probabilities: {path}"
        )
    uncertainty: dict[str, np.ndarray] = {}
    prefix = "uncertainty_"
    for column in frame.columns:
        if not column.startswith(prefix):
            continue
        values = frame[column].to_numpy(dtype=np.float64)
        if values.shape != (len(split),) or not np.isfinite(values).all():
            raise ProtocolStateError(f"invalid uncertainty column {column!r} in {path}")
        uncertainty[column.removeprefix(prefix)] = values
    expected_uncertainty = (
        {
            "predictive_entropy",
            "expected_data_entropy",
            "epistemic_mutual_information",
        }
        if receipt.get("posterior_sampling")
        else {"predictive_entropy", "one_minus_confidence"}
    )
    if set(uncertainty) != expected_uncertainty:
        raise ProtocolStateError(
            f"prediction uncertainty columns differ from the frozen inference "
            f"contract in {path}: expected {sorted(expected_uncertainty)}, got "
            f"{sorted(uncertainty)}"
        )
    return PredictionBundle(
        probabilities=probabilities,
        predictions=predictions,
        uncertainty=uncertainty,
        probability_semantics=str(
            receipt.get("metrics", {}).get("probability_semantics", "")
        ),
    )


def _load_unit_probabilities(
    config: ExperimentConfig,
    run_dir: Path,
    split: pd.DataFrame,
    receipt: dict[str, Any],
) -> np.ndarray:
    """Backward-compatible probability-only view of a frozen prediction unit."""
    return _load_unit_prediction(config, run_dir, split, receipt).probabilities


def _seed_ensemble_prediction(
    member_predictions: list[PredictionBundle],
    *,
    posterior_sampling: bool,
) -> PredictionBundle:
    """Build the evaluated/deployed equal-weight mixture and its uncertainty."""
    if not member_predictions:
        raise ProtocolStateError("seed ensemble has no prediction members")
    probability_stack = np.stack(
        [prediction.probabilities for prediction in member_predictions], axis=0
    )
    mean_probabilities = probability_stack.mean(axis=0)
    mean_probabilities /= mean_probabilities.sum(axis=1, keepdims=True)
    predictive_entropy = -np.sum(
        mean_probabilities * np.log(np.clip(mean_probabilities, 1e-12, 1.0)), axis=1
    )
    uncertainty = {
        "predictive_entropy": predictive_entropy,
        "one_minus_confidence": 1.0 - mean_probabilities.max(axis=1),
    }
    if posterior_sampling:
        try:
            expected_data_entropy = np.mean(
                np.stack(
                    [
                        prediction.uncertainty["expected_data_entropy"]
                        for prediction in member_predictions
                    ],
                    axis=0,
                ),
                axis=0,
            )
        except KeyError as exc:
            raise ProtocolStateError(
                "PGS seed member lacks expected-data entropy"
            ) from exc
        uncertainty["expected_data_entropy"] = expected_data_entropy
        uncertainty["epistemic_mutual_information"] = np.maximum(
            predictive_entropy - expected_data_entropy, 0.0
        )
    return PredictionBundle(
        probabilities=mean_probabilities,
        predictions=mean_probabilities.argmax(axis=1).astype(np.int64),
        uncertainty=uncertainty,
        probability_semantics=(
            "equal_weight_mean_over_training_seed_x_pgs_virtual_member_components"
            if posterior_sampling
            else "equal_weight_seed_mean_of_point_probabilities"
        ),
    )


def _aggregate_validation(
    config: ExperimentConfig,
    run_dir: Path,
    validation_split: pd.DataFrame,
    unit_receipts: list[dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    for receipt in unit_receipts:
        row = {
            "candidate": receipt["candidate"],
            "seed": receipt["seed"],
            "model": receipt["model"],
            "image_encoder": receipt["image_encoder"],
            "text_encoder": receipt["text_encoder"],
            "posterior_sampling": receipt["posterior_sampling"],
            "fit_seconds": receipt["fit_seconds"],
        }
        row.update(receipt["metrics"])
        rows.append(row)
    by_seed = pd.DataFrame(rows)
    aggregate_rows: list[dict[str, Any]] = []
    ensemble_frames: list[pd.DataFrame] = []
    numeric_metrics = _numeric_metric_columns(by_seed)
    for candidate in config.candidates:
        subset = by_seed[by_seed["candidate"] == candidate.name]
        candidate_receipts = {
            int(receipt["seed"]): receipt
            for receipt in unit_receipts
            if receipt["candidate"] == candidate.name
        }
        missing_seeds = sorted(set(config.seeds).difference(candidate_receipts))
        if missing_seeds:
            raise ProtocolStateError(
                f"{candidate.name} lacks validation probabilities for seeds "
                f"{missing_seeds}"
            )
        member_predictions = [
            _load_unit_prediction(
                config,
                run_dir,
                validation_split,
                candidate_receipts[seed],
            )
            for seed in config.seeds
        ]
        ensemble_prediction = _seed_ensemble_prediction(
            member_predictions,
            posterior_sampling=candidate.posterior_sampling,
        )
        ensemble_metrics, _, _, _ = _evaluate_prediction(
            config,
            validation_split[config.label_column].to_numpy(dtype=np.int64),
            ensemble_prediction,
            derive_risk_thresholds=True,
        )
        ensemble_frame = prediction_frame(
            validation_split,
            id_column=config.id_column,
            label_column=config.label_column,
            prediction=ensemble_prediction,
            metadata_columns=(
                config.embedding_index_column,
                config.label_name_column,
                *config.group_columns,
            ),
        )
        ensemble_frame.insert(0, "candidate", candidate.name)
        ensemble_frame.insert(1, "seed_count", len(config.seeds))
        ensemble_frames.append(ensemble_frame)
        row: dict[str, Any] = {
            "candidate": candidate.name,
            "model": candidate.model,
            "image_encoder": candidate.image_encoder,
            "text_encoder": candidate.text_encoder,
            "posterior_sampling": candidate.posterior_sampling,
            "seeds_completed": len(subset),
            "probability_aggregation": "equal_weight_arithmetic_mean",
            "total_checkpoint_size_bytes": sum(
                int(candidate_receipts[seed]["artifacts"]["checkpoint"]["size_bytes"])
                for seed in config.seeds
            ),
        }
        for metric in numeric_metrics:
            values = pd.to_numeric(subset.get(metric), errors="coerce").dropna()
            row[f"per_seed_{metric}_mean"] = (
                float(values.mean()) if len(values) else np.nan
            )
            row[f"per_seed_{metric}_std"] = (
                float(values.std(ddof=1)) if len(values) > 1 else 0.0
            )
        for metric, value in ensemble_metrics.items():
            row[f"ensemble_{metric}"] = value
        aggregate_rows.append(row)
    aggregate = pd.DataFrame(aggregate_rows)
    primary = f"ensemble_{config.selection_metric}"
    aggregate = aggregate.sort_values(
        [primary, "ensemble_nll", "total_checkpoint_size_bytes", "candidate"],
        ascending=[False, True, True, True],
        kind="stable",
    ).reset_index(drop=True)
    ensemble_predictions = pd.concat(ensemble_frames, ignore_index=True)
    return by_seed, aggregate, ensemble_predictions


def _deployment_eligible_leaderboard(
    config: ExperimentConfig,
    leaderboard: pd.DataFrame,
) -> pd.DataFrame:
    """Restrict primary selection to the preregistered exportable-system family."""
    eligible_names = list(config.deployment_eligible_candidates)
    candidate_names = leaderboard["candidate"].astype(str)
    eligible = leaderboard[candidate_names.isin(eligible_names)].copy()
    observed = set(eligible["candidate"].astype(str))
    if observed != set(eligible_names) or len(eligible) != len(eligible_names):
        missing = sorted(set(eligible_names).difference(observed))
        raise ProtocolStateError(
            "deployment-eligible validation leaderboard is incomplete; missing "
            f"candidates: {missing}"
        )
    eligible.insert(1, "global_validation_rank", eligible.index.to_numpy() + 1)
    return eligible.reset_index(drop=True)


def _numeric_metric_columns(frame: pd.DataFrame) -> list[str]:
    metadata_columns = {
        "candidate",
        "seed",
        "model",
        "image_encoder",
        "text_encoder",
        "posterior_sampling",
        "probability_semantics",
        "n_samples",
    }
    metrics: list[str] = []
    for column in frame.columns:
        if column in metadata_columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.notna().any():
            metrics.append(column)
    return metrics


def _calibration_protocol(config: ExperimentConfig) -> dict[str, Any]:
    """Return the explicit no-claim calibration/evaluation contract."""
    return {
        "family": config.calibration_family,
        "fitting_objective": config.calibration_fitting_objective,
        "probability_scope": config.calibration_probability_scope,
        "claim": config.calibration_claim,
        "ece": {
            "family": config.ece_family,
            "binning": config.ece_binning,
            "bins": config.ece_bins,
            "bin_interval_semantics": config.ece_bin_interval_semantics,
        },
    }


def _predicted_routable_mask(
    predictions: np.ndarray,
    class_labels: list[str],
) -> np.ndarray:
    """Return predictions eligible for confidence/uncertainty auto-acceptance."""
    predictions = np.asarray(predictions, dtype=np.int64)
    if predictions.ndim != 1 or not len(predictions):
        raise ProtocolStateError("review policy requires non-empty 1D predictions")
    if len(class_labels) == 0 or len(class_labels) != len(set(class_labels)):
        raise ProtocolStateError("review policy requires distinct ordered class labels")
    if np.any((predictions < 0) | (predictions >= len(class_labels))):
        raise ProtocolStateError("review policy prediction is outside the class map")
    if "Instansi lain" not in class_labels:
        return np.ones(len(predictions), dtype=bool)
    catch_all_index = class_labels.index("Instansi lain")
    return predictions != catch_all_index


def _risk_at_frozen_threshold_in_population(
    y_true: np.ndarray,
    predictions: np.ndarray,
    uncertainty: np.ndarray,
    population_mask: np.ndarray,
    *,
    uncertainty_threshold: float,
    target_coverage: float,
    num_classes: int,
) -> dict[str, float | int]:
    """Apply a frozen gate within its declared target population."""
    if not np.any(population_mask):
        return {
            "target_coverage": float(target_coverage),
            "realized_coverage": float("nan"),
            "retained": 0,
            "selective_risk": float("nan"),
            "selective_macro_f1": float("nan"),
            "uncertainty_threshold": float(uncertainty_threshold),
        }
    return risk_at_uncertainty_threshold(
        y_true[population_mask],
        predictions[population_mask],
        uncertainty[population_mask],
        uncertainty_threshold=uncertainty_threshold,
        target_coverage=target_coverage,
        num_classes=num_classes,
    )


def _risk_at_acceptance_in_population(
    y_true: np.ndarray,
    predictions: np.ndarray,
    accepted: np.ndarray,
    population_mask: np.ndarray,
    *,
    target_coverage: float,
    num_classes: int,
) -> dict[str, float | int]:
    """Evaluate a joint acceptance mask within its declared population."""
    if not np.any(population_mask):
        return {
            "target_coverage": float(target_coverage),
            "realized_coverage": float("nan"),
            "retained": 0,
            "selective_risk": float("nan"),
            "selective_macro_f1": float("nan"),
        }
    return risk_at_acceptance_mask(
        y_true[population_mask],
        predictions[population_mask],
        accepted[population_mask],
        target_coverage=target_coverage,
        num_classes=num_classes,
    )


def _validation_review_operating_points(
    config: ExperimentConfig,
    ensemble_predictions: pd.DataFrame,
    class_labels: list[str],
) -> pd.DataFrame:
    """Fit the deployed conjunction of review gates on validation only.

    PGS has two gates (confidence and epistemic MI). Their marginal quantile is
    increased together, deterministically, until the *jointly* accepted set
    reaches the preregistered target. This avoids pretending two independent
    80% gates imply an 80% deployed operating point.
    """
    rows: list[dict[str, Any]] = []
    for candidate in config.candidates:
        subset = ensemble_predictions[
            ensemble_predictions["candidate"] == candidate.name
        ]
        if subset.empty:
            raise ProtocolStateError(
                f"validation ensemble predictions missing for {candidate.name}"
            )
        y_true = subset["y_true"].to_numpy(dtype=np.int64)
        y_pred = subset["y_pred"].to_numpy(dtype=np.int64)
        routable_mask = _predicted_routable_mask(y_pred, class_labels)
        routable_count = int(routable_mask.sum())
        if routable_count == 0:
            raise ProtocolStateError(
                f"validation ensemble {candidate.name} predicts only unconditional "
                "review labels; no selective threshold can be fitted"
            )
        measures = ["one_minus_confidence"]
        if candidate.posterior_sampling:
            measures.append("epistemic_mutual_information")
        uncertainty_by_measure: dict[str, np.ndarray] = {}
        for measure in measures:
            column = f"uncertainty_{measure}"
            if column not in subset:
                raise ProtocolStateError(
                    f"validation ensemble {candidate.name} lacks {measure}"
                )
            uncertainty_by_measure[measure] = subset[column].to_numpy(dtype=np.float64)
        routable_uncertainty = {
            measure: uncertainty[routable_mask]
            for measure, uncertainty in uncertainty_by_measure.items()
        }
        target_retained = max(
            1,
            int(np.ceil(config.review_target_coverage * routable_count - 1e-12)),
        )
        chosen_quantile = 1.0
        chosen_thresholds: dict[str, float] = {}
        chosen_routable_acceptance = np.ones(routable_count, dtype=bool)
        for retained_rank in range(target_retained, routable_count + 1):
            marginal_quantile = retained_rank / routable_count
            thresholds = {
                measure: uncertainty_threshold_at_target_coverage(
                    uncertainty, marginal_quantile
                )[0]
                for measure, uncertainty in routable_uncertainty.items()
            }
            accepted = np.logical_and.reduce(
                [
                    routable_uncertainty[measure] <= threshold
                    for measure, threshold in thresholds.items()
                ]
            )
            if int(accepted.sum()) >= target_retained:
                chosen_quantile = float(marginal_quantile)
                chosen_thresholds = thresholds
                chosen_routable_acceptance = accepted
                break

        for measure, uncertainty in uncertainty_by_measure.items():
            threshold = chosen_thresholds[measure]
            risk = risk_at_uncertainty_threshold(
                y_true[routable_mask],
                y_pred[routable_mask],
                uncertainty[routable_mask],
                uncertainty_threshold=threshold,
                target_coverage=config.review_target_coverage,
                num_classes=config.expected_num_classes,
            )
            overall_acceptance = routable_mask & (uncertainty <= threshold)
            overall_risk = risk_at_acceptance_mask(
                y_true,
                y_pred,
                overall_acceptance,
                target_coverage=config.review_target_coverage,
                num_classes=config.expected_num_classes,
            )
            rows.append(
                {
                    "candidate": candidate.name,
                    "uncertainty": measure,
                    "threshold_source": config.review_threshold_source,
                    "operating_criterion": config.review_operating_criterion,
                    "target_population": config.review_target_population,
                    "tie_policy": config.review_tie_policy,
                    "policy_component": "gate",
                    "policy_scope": (
                        "model_review_gates_plus_unconditional_labels_excluding_registry"
                    ),
                    "marginal_quantile_coverage": chosen_quantile,
                    "target_population_count": routable_count,
                    "unconditionally_reviewed_count": int(len(y_true) - routable_count),
                    "overall_realized_coverage": overall_risk["realized_coverage"],
                    "overall_retained": overall_risk["retained"],
                    **risk,
                }
            )
        joint_risk = risk_at_acceptance_mask(
            y_true[routable_mask],
            y_pred[routable_mask],
            chosen_routable_acceptance,
            target_coverage=config.review_target_coverage,
            num_classes=config.expected_num_classes,
        )
        overall_joint_acceptance = np.zeros(len(y_true), dtype=bool)
        overall_joint_acceptance[routable_mask] = chosen_routable_acceptance
        overall_joint_risk = risk_at_acceptance_mask(
            y_true,
            y_pred,
            overall_joint_acceptance,
            target_coverage=config.review_target_coverage,
            num_classes=config.expected_num_classes,
        )
        rows.append(
            {
                "candidate": candidate.name,
                "uncertainty": "joint_deployed_review_policy",
                "threshold_source": config.review_threshold_source,
                "operating_criterion": config.review_operating_criterion,
                "target_population": config.review_target_population,
                "tie_policy": config.review_tie_policy,
                "policy_component": "joint",
                "policy_scope": (
                    "model_review_gates_plus_unconditional_labels_excluding_registry"
                ),
                "marginal_quantile_coverage": chosen_quantile,
                "uncertainty_threshold": None,
                "target_population_count": routable_count,
                "unconditionally_reviewed_count": int(len(y_true) - routable_count),
                "overall_realized_coverage": overall_joint_risk["realized_coverage"],
                "overall_retained": overall_joint_risk["retained"],
                **joint_risk,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        raise ProtocolStateError("validation produced no review operating points")
    return result


def _selected_review_policy(
    config: ExperimentConfig,
    selected: str,
    operating_points: pd.DataFrame,
    class_labels: list[str],
) -> dict[str, Any]:
    candidate = config.candidate(selected)
    subset = operating_points[operating_points["candidate"] == selected]
    by_measure = {str(row["uncertainty"]): row for _, row in subset.iterrows()}
    confidence_row = by_measure.get("one_minus_confidence")
    joint_row = by_measure.get("joint_deployed_review_policy")
    if confidence_row is None or joint_row is None:
        raise ProtocolStateError(
            "selected validation ensemble lacks confidence/joint operating points"
        )
    max_one_minus_confidence = float(confidence_row["uncertainty_threshold"])
    epistemic_row = by_measure.get("epistemic_mutual_information")
    if candidate.posterior_sampling and epistemic_row is None:
        raise ProtocolStateError(
            "selected PGS ensemble lacks an epistemic operating point"
        )
    if not candidate.posterior_sampling and epistemic_row is not None:
        raise ProtocolStateError(
            "point ensemble unexpectedly declared an epistemic operating point"
        )
    return {
        "candidate": selected,
        "threshold_source": config.review_threshold_source,
        "selection_split": "validation",
        "operating_criterion": config.review_operating_criterion,
        "target_coverage": config.review_target_coverage,
        "target_population": config.review_target_population,
        "tie_policy": config.review_tie_policy,
        "policy_scope": str(joint_row["policy_scope"]),
        "marginal_quantile_coverage": float(joint_row["marginal_quantile_coverage"]),
        "minimum_confidence": float(1.0 - max_one_minus_confidence),
        "maximum_one_minus_confidence": max_one_minus_confidence,
        "maximum_epistemic_mutual_information": (
            float(epistemic_row["uncertainty_threshold"])
            if epistemic_row is not None
            else None
        ),
        "epistemic_uncertainty_semantics": (
            EPISTEMIC_MI_METHOD if candidate.posterior_sampling else None
        ),
        "epistemic_component_axis": (
            "training_seed_x_pgs_virtual_member"
            if candidate.posterior_sampling
            else None
        ),
        "epistemic_component_count": (
            len(config.seeds) * config.virtual_ensembles
            if candidate.posterior_sampling
            else None
        ),
        "epistemic_training_seed_count": (
            len(config.seeds) if candidate.posterior_sampling else None
        ),
        "epistemic_virtual_ensembles_per_seed": (
            config.virtual_ensembles if candidate.posterior_sampling else None
        ),
        "validation_realized_confidence_coverage": float(
            confidence_row["realized_coverage"]
        ),
        "validation_confidence_selective_risk": float(confidence_row["selective_risk"]),
        "validation_realized_epistemic_coverage": (
            float(epistemic_row["realized_coverage"])
            if epistemic_row is not None
            else None
        ),
        "validation_epistemic_selective_risk": (
            float(epistemic_row["selective_risk"])
            if epistemic_row is not None
            else None
        ),
        "validation_joint_realized_coverage": float(joint_row["realized_coverage"]),
        "validation_joint_overall_realized_coverage": float(
            joint_row["overall_realized_coverage"]
        ),
        "validation_joint_selective_risk": float(joint_row["selective_risk"]),
        "validation_target_population_count": int(joint_row["target_population_count"]),
        "validation_unconditionally_reviewed_count": int(
            joint_row["unconditionally_reviewed_count"]
        ),
        "unconditionally_reviewed_labels": (
            ["Instansi lain"] if "Instansi lain" in class_labels else []
        ),
        "routable_labels": [
            label for label in class_labels if label != "Instansi lain"
        ],
    }


def _test_plan(config: ExperimentConfig, selected: str) -> list[str]:
    names: list[str] = []
    if config.test.include_selected:
        names.append(selected)
    names.extend(config.test.fixed_candidates)
    if config.test.paired_reference is not None:
        names.append(config.test.paired_reference)
    for reference, challenger, _ in config.test.paired_comparisons:
        names.extend((reference, challenger))
    names.extend(
        candidate for candidate, _ in config.test.matched_checkpoint_inference_ablations
    )
    return list(dict.fromkeys(names))


def _matched_checkpoint_inference_ablation_plan(
    config: ExperimentConfig,
) -> dict[str, Any]:
    return {
        "analysis_role": "prespecified_inference_only_ablation",
        "estimand": (
            "virtual_ensemble_minus_native_point_inference_on_identical_"
            "posterior_trained_checkpoints"
        ),
        "reference_inference": (
            "native_predict_proba_using_all_trees_from_posterior_checkpoint"
        ),
        "challenger_inference": (
            "catboost_virtual_ensembles_posterior_mean_using_same_checkpoint"
        ),
        "checkpoint_identity_rule": (
            "same serialized posterior-sampling checkpoint SHA-256 and retained "
            "tree count within every candidate-seed pair"
        ),
        "training_intervention": "none_within_ablation_pair",
        "probability_aggregation": (
            "equal_weight_arithmetic_mean_across_all_preregistered_training_seeds"
        ),
        "virtual_ensembles_per_seed": config.virtual_ensembles,
        "ablations": [
            {"candidate": candidate, "label": label}
            for candidate, label in config.test.matched_checkpoint_inference_ablations
        ],
    }


def _prespecified_phase_a_inference_plan(config: ExperimentConfig) -> dict[str, Any]:
    return {
        "cluster_column": "leakage_group_id",
        "seed_ensemble_prediction_rule": (
            "equal-weight arithmetic mean of class probabilities across all "
            "preregistered seeds; argmax with lowest class ID on an exact tie"
        ),
        "seed_order": list(config.seeds),
        "paired_bootstrap": (
            "primary stratified shared whole-cluster resampling with the "
            "deployed preregistered-seed probability ensemble held fixed"
        ),
        "paired_bootstrap_algorithm_id": BOOTSTRAP_ALGORITHM_ID,
        "paired_bootstrap_algorithm": BOOTSTRAP_ALGORITHM,
        "paired_bootstrap_estimand": (
            "deployed_fixed_preregistered_seed_ensemble_metric_delta"
        ),
        "paired_bootstrap_probability_aggregation": (
            "arithmetic_mean_before_argmax_and_metric"
        ),
        "paired_bootstrap_point_estimate_seed_rule": (
            "all_preregistered_seeds_exactly_once_equal_weight"
        ),
        "paired_bootstrap_replicate_seed_rule": (
            "all_preregistered_seeds_exactly_once_equal_weight_fixed_across_draws"
        ),
        "paired_bootstrap_training_seed_resampling": False,
        "paired_bootstrap_iterations": config.test.bootstrap_iterations,
        "paired_bootstrap_seed": config.test.bootstrap_seed,
        "paired_bootstrap_rng_stream_derivation": (
            bootstrap_rng_stream_derivation(
                config.test.bootstrap_seed,
                include_training_seed_stream=False,
            )
        ),
        "paired_bootstrap_stratification": config.test.bootstrap_stratification,
        "paired_bootstrap_configuration_timing": (
            "frozen_in_selection_receipt_before_locked_test_access"
        ),
        "training_seed_sensitivity": (
            "secondary stratified whole-cluster bootstrap crossed with replacement "
            "resampling of the preregistered training-seed list; not the deployed-"
            "ensemble confidence interval"
        ),
        "training_seed_sensitivity_algorithm_id": (
            TRAINING_SEED_SENSITIVITY_ALGORITHM_ID
        ),
        "training_seed_sensitivity_algorithm": (TRAINING_SEED_SENSITIVITY_ALGORITHM),
        "training_seed_sensitivity_estimand": (
            "training_seed_superpopulation_equal_size_probability_ensemble_metric_delta"
        ),
        "training_seed_sensitivity_probability_aggregation": (
            "arithmetic_mean_before_argmax_and_metric"
        ),
        "training_seed_sensitivity_point_estimate_seed_rule": (
            "all_preregistered_seeds_exactly_once_equal_weight"
        ),
        "training_seed_sensitivity_replicate_seed_rule": (
            "sample_preregistered_seed_positions_with_replacement_to_original_size"
        ),
        "training_seed_sensitivity_iterations": (
            config.test.training_seed_sensitivity_iterations
        ),
        "training_seed_sensitivity_seed": config.test.training_seed_sensitivity_seed,
        "training_seed_sensitivity_rng_stream_derivation": (
            bootstrap_rng_stream_derivation(
                config.test.training_seed_sensitivity_seed,
                include_training_seed_stream=True,
            )
        ),
        "paired_accuracy_test": "cluster-level paired sign-flip on seed ensemble",
        "cluster_permutation_iterations": config.test.cluster_permutation_iterations,
        "cluster_permutation_seed": config.test.cluster_permutation_seed,
        "multiplicity_family": "all frozen model-pair accuracy comparisons",
        "multiplicity_correction": "Holm family-wise error control",
    }


def run_selection(
    config: ExperimentConfig,
    *,
    run_dir: Path | None = None,
    resume: bool = False,
) -> Path:
    """Fit every candidate and select exclusively on validation metrics."""
    run_dir, input_manifest = _prepare_selection_run(config, run_dir, resume=resume)
    splits = load_selection_splits(config)
    selection_audit = audit_split_leakage(config, splits)
    write_json(run_dir / "metadata" / "selection_split_audit.json", selection_audit)

    store = EmbeddingStore(config)
    feature_cache: dict[tuple[str, str | None, str | None, str], Any] = {}
    y_train = splits.train[config.label_column].to_numpy(dtype=np.int64)
    y_val = splits.val[config.label_column].to_numpy(dtype=np.int64)
    unit_receipts: list[dict[str, Any]] = []

    for candidate in config.candidates:
        X_train, X_val = _feature_pair(
            store,
            candidate,
            splits.train,
            splits.val,
            feature_cache,
            "val",
        )
        for seed in config.seeds:
            completed = _completed_selection_unit(
                config,
                run_dir,
                candidate,
                seed,
                class_map_digest=input_manifest["class_map_sha256"],
            )
            if completed is not None:
                unit_receipts.append(completed)
                continue
            _set_seed(seed)
            fitted = fit_candidate(
                config,
                candidate,
                seed,
                X_train,
                y_train,
                X_val,
                y_val,
            )
            prediction = predict_candidate(
                fitted, X_val, virtual_ensembles=config.virtual_ensembles
            )
            paths = _unit_paths(run_dir, "selection", candidate.name, seed)
            checkpoint = save_fitted_model(fitted, paths["model_base"])
            receipt = _write_evaluation_unit(
                config,
                run_dir=run_dir,
                phase="selection",
                candidate=candidate,
                seed=seed,
                split=splits.val,
                prediction=prediction,
                fitted=fitted,
                checkpoint=checkpoint,
                class_map_digest=input_manifest["class_map_sha256"],
            )
            unit_receipts.append(receipt)

    by_seed, leaderboard, ensemble_predictions = _aggregate_validation(
        config,
        run_dir,
        splits.val,
        unit_receipts,
    )
    expected_units = len(config.candidates) * len(config.seeds)
    if len(by_seed) != expected_units:
        raise ProtocolStateError(
            f"selection incomplete: expected {expected_units} units, found {len(by_seed)}"
        )
    deployment_leaderboard = _deployment_eligible_leaderboard(config, leaderboard)
    selected = str(deployment_leaderboard.iloc[0]["candidate"])
    selection_dir = run_dir / "selection"
    class_labels = [
        str(item["label_name"]) for item in input_manifest["class_map"]["classes"]
    ]
    review_operating_points = _validation_review_operating_points(
        config,
        ensemble_predictions,
        class_labels,
    )
    selected_review_policy = _selected_review_policy(
        config,
        selected,
        review_operating_points,
        class_labels,
    )
    by_seed.to_csv(selection_dir / "validation_metrics_by_seed.csv", index=False)
    leaderboard.to_csv(selection_dir / "validation_leaderboard.csv", index=False)
    deployment_leaderboard.to_csv(
        selection_dir / "validation_deployment_eligible_leaderboard.csv",
        index=False,
    )
    write_prediction_csv(
        selection_dir / "validation_seed_ensemble_predictions.csv.gz",
        ensemble_predictions,
    )
    leaderboard.to_csv(
        selection_dir / "validation_seed_ensemble_metrics.csv", index=False
    )
    review_operating_points.to_csv(
        selection_dir / "validation_review_operating_points.csv", index=False
    )
    unit_index_record = _write_unit_index(run_dir, "selection", unit_receipts)

    planned = _test_plan(config, selected)
    model_records: dict[str, dict[str, Any]] = defaultdict(dict)
    for receipt in unit_receipts:
        if receipt["candidate"] in planned:
            model_records[receipt["candidate"]][str(receipt["seed"])] = receipt[
                "artifacts"
            ]["checkpoint"]
    receipt = {
        "schema_version": 1,
        "phase": "selection_complete",
        "completed_at_utc": utc_now(),
        "protocol_digest": config.protocol_digest(),
        "input_manifest_digest": object_sha256(input_manifest),
        "class_map_sha256": input_manifest["class_map_sha256"],
        "selection_split_names": ["train", "val"],
        "test_csv_parsed": False,
        "selection_metric": config.selection_metric,
        "selection_rule": (
            "among the preregistered deployment-eligible candidates: highest "
            f"validation ensemble_{config.selection_metric} computed from the "
            "equal-weight arithmetic mean of probabilities across every "
            "preregistered seed; lower validation ensemble_nll; smaller summed "
            "checkpoint size in bytes; lexical candidate name"
        ),
        "selection_eligibility_rule": (
            "only candidates listed in protocol.deployment_eligible_candidates "
            "may define the primary selected/deployed system; all other evaluated "
            "candidates are secondary baselines or ablations"
        ),
        "deployment_eligible_candidates": list(config.deployment_eligible_candidates),
        "secondary_baseline_candidates": [
            candidate.name
            for candidate in config.candidates
            if candidate.name not in config.deployment_eligible_candidates
        ],
        "primary_system": "equal_weight_preregistered_seed_ensemble",
        "calibration_protocol": _calibration_protocol(config),
        "review_policy": selected_review_policy,
        "selected_candidate": selected,
        "planned_test_candidates": planned,
        "paired_reference": config.test.paired_reference or selected,
        "prespecified_phase_a_inference_plan": (
            _prespecified_phase_a_inference_plan(config)
        ),
        "matched_checkpoint_inference_ablation_plan": (
            _matched_checkpoint_inference_ablation_plan(config)
        ),
        "explicit_paired_comparisons": [
            {
                "reference": reference,
                "challenger": challenger,
                "label": label,
            }
            for reference, challenger, label in config.test.paired_comparisons
        ],
        "seeds": list(config.seeds),
        "model_records": model_records,
        "artifacts": {
            "validation_metrics_by_seed": artifact_record(
                selection_dir / "validation_metrics_by_seed.csv", base_dir=run_dir
            ),
            "validation_leaderboard": artifact_record(
                selection_dir / "validation_leaderboard.csv", base_dir=run_dir
            ),
            "validation_deployment_eligible_leaderboard": artifact_record(
                selection_dir / "validation_deployment_eligible_leaderboard.csv",
                base_dir=run_dir,
            ),
            "validation_seed_ensemble_predictions": artifact_record(
                selection_dir / "validation_seed_ensemble_predictions.csv.gz",
                base_dir=run_dir,
            ),
            "validation_seed_ensemble_metrics": artifact_record(
                selection_dir / "validation_seed_ensemble_metrics.csv",
                base_dir=run_dir,
            ),
            "validation_review_operating_points": artifact_record(
                selection_dir / "validation_review_operating_points.csv",
                base_dir=run_dir,
            ),
            "unit_artifact_index": unit_index_record,
        },
    }
    receipt["receipt_digest"] = object_sha256(receipt)
    write_json(selection_dir / "selection_receipt.json", receipt)
    write_json(
        run_dir / "metadata" / "run_state.json",
        {
            "updated_at_utc": utc_now(),
            "phase": "selection_complete",
            "protocol_digest": config.protocol_digest(),
            "test_csv_parsed": False,
            "selected_candidate": selected,
        },
    )
    return run_dir


def _verify_selection_receipt(
    config: ExperimentConfig,
    run_dir: Path,
    input_manifest: dict[str, Any],
) -> dict[str, Any]:
    path = run_dir / "selection" / "selection_receipt.json"
    if not path.is_file():
        raise ProtocolStateError("locked test requires a completed selection receipt")
    receipt = read_json(path)
    stored_digest = receipt.pop("receipt_digest", None)
    if stored_digest != object_sha256(receipt):
        raise ProtocolStateError("selection receipt digest mismatch")
    receipt["receipt_digest"] = stored_digest
    if receipt.get("protocol_digest") != config.protocol_digest():
        raise ProtocolStateError("selection receipt config digest mismatch")
    if receipt.get("input_manifest_digest") != object_sha256(input_manifest):
        raise ProtocolStateError("selection receipt input digest mismatch")
    if receipt.get("class_map_sha256") != input_manifest.get("class_map_sha256"):
        raise ProtocolStateError("selection receipt class-map digest mismatch")
    if receipt.get("test_csv_parsed") is not False:
        raise ProtocolStateError(
            "selection receipt does not attest an unopened test set"
        )
    if receipt.get("deployment_eligible_candidates") != list(
        config.deployment_eligible_candidates
    ):
        raise ProtocolStateError(
            "selection receipt deployment-eligible candidate set mismatch"
        )
    if "protocol.deployment_eligible_candidates" not in str(
        receipt.get("selection_eligibility_rule", "")
    ) or "secondary baselines or ablations" not in str(
        receipt.get("selection_eligibility_rule", "")
    ):
        raise ProtocolStateError("selection eligibility rule is incomplete")
    selected_name = str(receipt.get("selected_candidate", ""))
    if selected_name not in config.deployment_eligible_candidates:
        raise ProtocolStateError(
            "selected candidate was not preregistered as deployment eligible"
        )
    expected_secondary = [
        candidate.name
        for candidate in config.candidates
        if candidate.name not in config.deployment_eligible_candidates
    ]
    if receipt.get("secondary_baseline_candidates") != expected_secondary:
        raise ProtocolStateError("selection receipt secondary-baseline set mismatch")
    if receipt.get(
        "prespecified_phase_a_inference_plan"
    ) != _prespecified_phase_a_inference_plan(config):
        raise ProtocolStateError("selection receipt inference plan mismatch")
    if receipt.get(
        "matched_checkpoint_inference_ablation_plan"
    ) != _matched_checkpoint_inference_ablation_plan(config):
        raise ProtocolStateError(
            "selection receipt matched-checkpoint inference ablation plan mismatch"
        )
    if receipt.get("calibration_protocol") != _calibration_protocol(config):
        raise ProtocolStateError("selection receipt calibration protocol mismatch")
    review_policy = receipt.get("review_policy")
    expected_labels = [
        str(item["label_name"]) for item in input_manifest["class_map"]["classes"]
    ]
    if (
        not isinstance(review_policy, dict)
        or review_policy.get("candidate") != receipt.get("selected_candidate")
        or review_policy.get("threshold_source") != config.review_threshold_source
        or review_policy.get("selection_split") != "validation"
        or review_policy.get("operating_criterion") != config.review_operating_criterion
        or review_policy.get("target_coverage") != config.review_target_coverage
        or review_policy.get("target_population") != config.review_target_population
        or review_policy.get("tie_policy") != config.review_tie_policy
        or review_policy.get("policy_scope")
        != "model_review_gates_plus_unconditional_labels_excluding_registry"
        or review_policy.get("unconditionally_reviewed_labels")
        != (["Instansi lain"] if "Instansi lain" in expected_labels else [])
        or review_policy.get("routable_labels")
        != [label for label in expected_labels if label != "Instansi lain"]
    ):
        raise ProtocolStateError("selection receipt review policy mismatch")
    confidence_threshold = review_policy.get("minimum_confidence")
    maximum_one_minus = review_policy.get("maximum_one_minus_confidence")
    if (
        not isinstance(confidence_threshold, (int, float))
        or isinstance(confidence_threshold, bool)
        or not np.isfinite(confidence_threshold)
        or not 0.0 <= confidence_threshold <= 1.0
        or not isinstance(maximum_one_minus, (int, float))
        or isinstance(maximum_one_minus, bool)
        or not np.isclose(float(confidence_threshold) + float(maximum_one_minus), 1.0)
    ):
        raise ProtocolStateError("selection confidence review threshold is invalid")
    selected_candidate = config.candidate(str(receipt.get("selected_candidate")))
    epistemic_threshold = review_policy.get("maximum_epistemic_mutual_information")
    if selected_candidate.posterior_sampling:
        if (
            not isinstance(epistemic_threshold, (int, float))
            or isinstance(epistemic_threshold, bool)
            or not np.isfinite(epistemic_threshold)
            or epistemic_threshold < 0.0
            or review_policy.get("epistemic_uncertainty_semantics")
            != EPISTEMIC_MI_METHOD
            or review_policy.get("epistemic_component_axis")
            != "training_seed_x_pgs_virtual_member"
            or review_policy.get("epistemic_component_count")
            != len(config.seeds) * config.virtual_ensembles
            or review_policy.get("epistemic_training_seed_count") != len(config.seeds)
            or review_policy.get("epistemic_virtual_ensembles_per_seed")
            != config.virtual_ensembles
        ):
            raise ProtocolStateError("selection epistemic threshold is invalid")
    elif any(
        review_policy.get(field) is not None
        for field in (
            "maximum_epistemic_mutual_information",
            "epistemic_uncertainty_semantics",
            "epistemic_component_axis",
            "epistemic_component_count",
            "epistemic_training_seed_count",
            "epistemic_virtual_ensembles_per_seed",
        )
    ):
        raise ProtocolStateError(
            "point selection must not bind epistemic uncertainty metadata"
        )
    marginal_quantile = review_policy.get("marginal_quantile_coverage")
    joint_coverage = review_policy.get("validation_joint_realized_coverage")
    overall_joint_coverage = review_policy.get(
        "validation_joint_overall_realized_coverage"
    )
    joint_risk = review_policy.get("validation_joint_selective_risk")
    target_population_count = review_policy.get("validation_target_population_count")
    unconditional_count = review_policy.get("validation_unconditionally_reviewed_count")
    if (
        not isinstance(marginal_quantile, (int, float))
        or isinstance(marginal_quantile, bool)
        or not config.review_target_coverage <= marginal_quantile <= 1.0
        or not isinstance(joint_coverage, (int, float))
        or isinstance(joint_coverage, bool)
        or not config.review_target_coverage <= joint_coverage <= 1.0
        or not isinstance(joint_risk, (int, float))
        or isinstance(joint_risk, bool)
        or not 0.0 <= joint_risk <= 1.0
        or not isinstance(overall_joint_coverage, (int, float))
        or isinstance(overall_joint_coverage, bool)
        or not 0.0 <= overall_joint_coverage <= joint_coverage
        or type(target_population_count) is not int
        or target_population_count < 1
        or type(unconditional_count) is not int
        or unconditional_count < 0
    ):
        raise ProtocolStateError("selection joint review operating point is invalid")
    if "validation_review_operating_points" not in receipt.get("artifacts", {}):
        raise ProtocolStateError(
            "selection receipt lacks validation review operating points"
        )
    if "validation_deployment_eligible_leaderboard" not in receipt.get("artifacts", {}):
        raise ProtocolStateError(
            "selection receipt lacks deployment-eligible validation leaderboard"
        )
    for record in receipt.get("artifacts", {}).values():
        artifact_path = resolve_artifact_path(record, base_dir=run_dir)
        if (
            not artifact_path.is_file()
            or sha256_file(artifact_path) != record["sha256"]
        ):
            raise ProtocolStateError(
                f"frozen selection artifact changed: {artifact_path}"
            )
    operating_points = pd.read_csv(
        resolve_artifact_path(
            receipt["artifacts"]["validation_review_operating_points"],
            base_dir=run_dir,
        )
    )
    deployment_leaderboard = pd.read_csv(
        resolve_artifact_path(
            receipt["artifacts"]["validation_deployment_eligible_leaderboard"],
            base_dir=run_dir,
        )
    )
    full_leaderboard = pd.read_csv(
        resolve_artifact_path(
            receipt["artifacts"]["validation_seed_ensemble_metrics"],
            base_dir=run_dir,
        )
    )
    expected_eligible_order = (
        full_leaderboard[
            full_leaderboard["candidate"]
            .astype(str)
            .isin(config.deployment_eligible_candidates)
        ]["candidate"]
        .astype(str)
        .tolist()
    )
    if (
        deployment_leaderboard.empty
        or deployment_leaderboard["candidate"].astype(str).tolist()
        != expected_eligible_order
        or set(expected_eligible_order) != set(config.deployment_eligible_candidates)
        or str(deployment_leaderboard.iloc[0]["candidate"]) != selected_name
    ):
        raise ProtocolStateError(
            "selected candidate is not first in the frozen deployment-eligible "
            "validation leaderboard"
        )
    selected_points = operating_points[
        operating_points["candidate"] == receipt["selected_candidate"]
    ]
    confidence_points = selected_points[
        selected_points["uncertainty"] == "one_minus_confidence"
    ]
    epistemic_points = selected_points[
        selected_points["uncertainty"] == "epistemic_mutual_information"
    ]
    joint_points = selected_points[
        selected_points["uncertainty"] == "joint_deployed_review_policy"
    ]
    if len(confidence_points) != 1 or not np.isclose(
        float(confidence_points.iloc[0]["uncertainty_threshold"]),
        float(maximum_one_minus),
    ):
        raise ProtocolStateError(
            "selection review policy differs from its validation confidence row"
        )
    if selected_candidate.posterior_sampling:
        if len(epistemic_points) != 1 or not np.isclose(
            float(epistemic_points.iloc[0]["uncertainty_threshold"]),
            float(epistemic_threshold),
        ):
            raise ProtocolStateError(
                "selection review policy differs from its validation epistemic row"
            )
    elif not epistemic_points.empty:
        raise ProtocolStateError(
            "point selection has an unexpected validation epistemic row"
        )
    if (
        len(joint_points) != 1
        or str(joint_points.iloc[0]["policy_component"]) != "joint"
        or str(joint_points.iloc[0]["target_population"])
        != config.review_target_population
        or str(joint_points.iloc[0]["policy_scope"])
        != "model_review_gates_plus_unconditional_labels_excluding_registry"
        or not np.isclose(
            float(joint_points.iloc[0]["realized_coverage"]),
            float(joint_coverage),
        )
        or not np.isclose(
            float(joint_points.iloc[0]["selective_risk"]), float(joint_risk)
        )
        or not np.isclose(
            float(joint_points.iloc[0]["overall_realized_coverage"]),
            float(overall_joint_coverage),
        )
        or int(joint_points.iloc[0]["target_population_count"])
        != target_population_count
        or int(joint_points.iloc[0]["unconditionally_reviewed_count"])
        != unconditional_count
    ):
        raise ProtocolStateError(
            "selection review policy differs from its validation joint row"
        )
    unit_index_record = receipt.get("artifacts", {}).get("unit_artifact_index")
    if not isinstance(unit_index_record, dict):
        raise ProtocolStateError("selection receipt has no unit artifact index")
    _verify_unit_index(run_dir, unit_index_record)
    for seeds in receipt.get("model_records", {}).values():
        for record in seeds.values():
            path = resolve_artifact_path(record, base_dir=run_dir)
            if not path.is_file() or sha256_file(path) != record["sha256"]:
                raise ProtocolStateError(f"frozen checkpoint changed: {path}")
    return receipt


def _aggregate_phase_a(by_seed: pd.DataFrame, order: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for candidate in order:
        subset = by_seed[by_seed["candidate"] == candidate]
        row: dict[str, Any] = {
            "candidate": candidate,
            "seeds_completed": len(subset),
        }
        for metric in _numeric_metric_columns(by_seed):
            values = pd.to_numeric(subset.get(metric), errors="coerce").dropna()
            row[f"{metric}_mean"] = float(values.mean()) if len(values) else np.nan
            row[f"{metric}_std"] = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        rows.append(row)
    # Preserve the preregistered order; never rank/sort candidates by test score.
    return pd.DataFrame(rows)


def run_locked_test(run_dir: Path) -> Path:
    """Evaluate the frozen, preregistered models exactly once on test.csv."""
    run_dir = Path(run_dir).resolve()
    config = load_resolved_config(_snapshot_path(run_dir))
    input_manifest = read_json(run_dir / "metadata" / "input_manifest.json")
    verify_input_manifest(input_manifest)
    selection_receipt = _verify_selection_receipt(config, run_dir, input_manifest)
    marker = run_dir / "test" / "TEST_SET_OPENED.json"
    create_once_marker(
        marker,
        {
            "opened_at_utc": utc_now(),
            "selection_receipt_digest": selection_receipt["receipt_digest"],
            "class_map_sha256": input_manifest["class_map_sha256"],
            "warning": "A second test evaluation requires a new selection run.",
        },
    )

    splits = load_locked_test_splits(config)
    assert splits.test is not None
    test_audit = audit_split_leakage(config, splits)
    test_audit["locked_test_statistics"] = {
        "rows": len(splits.test),
        "label_distribution": {
            str(label): int(count)
            for label, count in splits.test[config.label_column]
            .value_counts()
            .sort_index()
            .items()
        },
    }
    write_json(run_dir / "metadata" / "locked_test_split_audit.json", test_audit)

    store = EmbeddingStore(config)
    feature_cache: dict[tuple[str, str | None, str | None, str], Any] = {}
    test_receipts: list[dict[str, Any]] = []
    paired_probabilities: dict[str, dict[int, tuple[np.ndarray, np.ndarray]]] = (
        defaultdict(dict)
    )
    matched_checkpoint_native_probabilities: dict[
        str, dict[int, tuple[np.ndarray, np.ndarray]]
    ] = defaultdict(dict)
    matched_checkpoint_prediction_frames: list[pd.DataFrame] = []
    matched_checkpoint_bindings: list[dict[str, Any]] = []
    matched_checkpoint_labels = dict(config.test.matched_checkpoint_inference_ablations)
    seed_predictions: dict[str, dict[int, PredictionBundle]] = defaultdict(dict)
    y_true = splits.test[config.label_column].to_numpy(dtype=np.int64)
    class_labels = [
        str(item["label_name"]) for item in input_manifest["class_map"]["classes"]
    ]
    planned = list(selection_receipt["planned_test_candidates"])

    for candidate_name in planned:
        candidate = config.candidate(candidate_name)
        _, X_test = _feature_pair(
            store,
            candidate,
            splits.train,
            splits.test,
            feature_cache,
            "test",
        )
        for seed in config.seeds:
            model_record = selection_receipt["model_records"][candidate_name][str(seed)]
            selection_unit = read_json(
                _unit_paths(run_dir, "selection", candidate_name, seed)["receipt"]
            )
            fitted = load_fitted_model(
                candidate,
                seed,
                resolve_artifact_path(model_record, base_dir=run_dir),
                selection_unit,
            )
            prediction = predict_candidate(
                fitted, X_test, virtual_ensembles=config.virtual_ensembles
            )
            if candidate_name in matched_checkpoint_labels:
                native_point = predict_native_point_from_posterior_checkpoint(
                    fitted,
                    X_test,
                )
                matched_checkpoint_native_probabilities[candidate_name][seed] = (
                    y_true.copy(),
                    native_point.probabilities.copy(),
                )
                checkpoint_sha256 = str(model_record["sha256"])
                checkpoint_tree_count = int(fitted.estimator.tree_count_)
                for inference_mode, ablation_prediction in (
                    ("native_point_same_posterior_checkpoint", native_point),
                    ("virtual_ensemble_same_posterior_checkpoint", prediction),
                ):
                    frame = prediction_frame(
                        splits.test,
                        id_column=config.id_column,
                        label_column=config.label_column,
                        prediction=ablation_prediction,
                        metadata_columns=(
                            config.embedding_index_column,
                            config.label_name_column,
                            *config.group_columns,
                        ),
                    )
                    frame.insert(0, "candidate", candidate_name)
                    frame.insert(
                        1, "ablation_label", matched_checkpoint_labels[candidate_name]
                    )
                    frame.insert(2, "seed", seed)
                    frame.insert(3, "inference_mode", inference_mode)
                    frame.insert(4, "checkpoint_sha256", checkpoint_sha256)
                    frame.insert(5, "checkpoint_tree_count", checkpoint_tree_count)
                    matched_checkpoint_prediction_frames.append(frame)
                matched_checkpoint_bindings.append(
                    {
                        "candidate": candidate_name,
                        "ablation_label": matched_checkpoint_labels[candidate_name],
                        "seed": seed,
                        "checkpoint_sha256": checkpoint_sha256,
                        "checkpoint_tree_count": checkpoint_tree_count,
                        "reference_probability_semantics": (
                            native_point.probability_semantics
                        ),
                        "challenger_probability_semantics": (
                            prediction.probability_semantics
                        ),
                        "same_checkpoint_object_used_for_both_inference_modes": True,
                    }
                )
            receipt = _write_evaluation_unit(
                config,
                run_dir=run_dir,
                phase="test",
                candidate=candidate,
                seed=seed,
                split=splits.test,
                prediction=prediction,
                fitted=None,
                checkpoint=resolve_artifact_path(model_record, base_dir=run_dir),
                class_map_digest=input_manifest["class_map_sha256"],
            )
            test_receipts.append(receipt)
            paired_probabilities[candidate_name][seed] = (
                y_true.copy(),
                prediction.probabilities.copy(),
            )
            seed_predictions[candidate_name][seed] = PredictionBundle(
                probabilities=prediction.probabilities.copy(),
                predictions=prediction.predictions.copy(),
                uncertainty={
                    name: values.copy()
                    for name, values in prediction.uncertainty.items()
                },
                probability_semantics=prediction.probability_semantics,
            )

    rows: list[dict[str, Any]] = []
    for receipt in test_receipts:
        row = {"candidate": receipt["candidate"], "seed": receipt["seed"]}
        row.update(receipt["metrics"])
        rows.append(row)
    by_seed = pd.DataFrame(rows)
    aggregate = _aggregate_phase_a(by_seed, planned)
    test_dir = run_dir / "test"
    by_seed.to_csv(test_dir / "phase_a_metrics_by_seed.csv", index=False)
    aggregate.to_csv(test_dir / "phase_a_metrics_aggregate.csv", index=False)

    # One primary test prediction vector per candidate is fixed by averaging
    # probabilities equally across every preregistered training seed.  This is
    # computed before any pairwise hypothesis test and is never test-optimized.
    seed_ensemble_predictions: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    ensemble_prediction_frames: list[pd.DataFrame] = []
    ensemble_metric_rows: list[dict[str, Any]] = []
    ensemble_risk_rows: list[dict[str, Any]] = []
    validation_operating_points = pd.read_csv(
        resolve_artifact_path(
            selection_receipt["artifacts"]["validation_review_operating_points"],
            base_dir=run_dir,
        )
    )
    for candidate_name in planned:
        missing_seeds = sorted(
            set(config.seeds).difference(seed_predictions[candidate_name])
        )
        if missing_seeds:
            raise ProtocolStateError(
                f"{candidate_name} lacks test probabilities for seeds {missing_seeds}"
            )
        candidate = config.candidate(candidate_name)
        ensemble_bundle = _seed_ensemble_prediction(
            [seed_predictions[candidate_name][seed] for seed in config.seeds],
            posterior_sampling=candidate.posterior_sampling,
        )
        ensemble_frame = prediction_frame(
            splits.test,
            id_column=config.id_column,
            label_column=config.label_column,
            prediction=ensemble_bundle,
            metadata_columns=(
                config.embedding_index_column,
                config.label_name_column,
                *config.group_columns,
            ),
        )
        ensemble_frame.insert(0, "candidate", candidate_name)
        ensemble_frame.insert(1, "seed_count", len(config.seeds))
        ensemble_prediction_frames.append(ensemble_frame)
        ensemble_metrics, _, _, _ = _evaluate_prediction(
            config,
            y_true,
            ensemble_bundle,
            derive_risk_thresholds=False,
        )
        ensemble_metric_rows.append(
            {
                "candidate": candidate_name,
                "seed_count": len(config.seeds),
                "probability_aggregation": "equal_weight_arithmetic_mean",
                **ensemble_metrics,
            }
        )
        seed_ensemble_predictions[candidate_name] = (
            y_true.copy(),
            ensemble_bundle.predictions.copy(),
        )
        frozen_rows = validation_operating_points[
            validation_operating_points["candidate"] == candidate_name
        ]
        gate_rows = frozen_rows[frozen_rows["policy_component"] == "gate"]
        frozen_joint_rows = frozen_rows[frozen_rows["policy_component"] == "joint"]
        if len(frozen_joint_rows) != 1:
            raise ProtocolStateError(
                f"validation joint review operating point missing for {candidate_name}"
            )
        routable_mask = _predicted_routable_mask(
            ensemble_bundle.predictions,
            class_labels,
        )
        jointly_accepted = routable_mask.copy()
        for _, frozen in gate_rows.iterrows():
            uncertainty_name = str(frozen["uncertainty"])
            if uncertainty_name not in ensemble_bundle.uncertainty:
                raise ProtocolStateError(
                    f"test ensemble {candidate_name} lacks frozen uncertainty "
                    f"measure {uncertainty_name}"
                )
            uncertainty = ensemble_bundle.uncertainty[uncertainty_name]
            applied = _risk_at_frozen_threshold_in_population(
                y_true,
                ensemble_bundle.predictions,
                uncertainty,
                routable_mask,
                uncertainty_threshold=float(frozen["uncertainty_threshold"]),
                target_coverage=float(frozen["target_coverage"]),
                num_classes=config.expected_num_classes,
            )
            gate_acceptance = routable_mask & (
                uncertainty <= float(frozen["uncertainty_threshold"])
            )
            overall_applied = risk_at_acceptance_mask(
                y_true,
                ensemble_bundle.predictions,
                gate_acceptance,
                target_coverage=float(frozen["target_coverage"]),
                num_classes=config.expected_num_classes,
            )
            ensemble_risk_rows.append(
                {
                    "candidate": candidate_name,
                    "uncertainty": uncertainty_name,
                    "threshold_source": "validation_seed_ensemble",
                    "operating_criterion": str(frozen["operating_criterion"]),
                    "target_population": str(frozen["target_population"]),
                    "tie_policy": str(frozen["tie_policy"]),
                    "policy_component": "gate",
                    "policy_scope": str(frozen["policy_scope"]),
                    "marginal_quantile_coverage": float(
                        frozen["marginal_quantile_coverage"]
                    ),
                    "target_population_count": int(routable_mask.sum()),
                    "unconditionally_reviewed_count": int(
                        len(y_true) - routable_mask.sum()
                    ),
                    "overall_realized_coverage": overall_applied["realized_coverage"],
                    "overall_retained": overall_applied["retained"],
                    **applied,
                }
            )
            jointly_accepted &= gate_acceptance
        joint_applied = _risk_at_acceptance_in_population(
            y_true,
            ensemble_bundle.predictions,
            jointly_accepted,
            routable_mask,
            target_coverage=float(frozen_joint_rows.iloc[0]["target_coverage"]),
            num_classes=config.expected_num_classes,
        )
        overall_joint_applied = risk_at_acceptance_mask(
            y_true,
            ensemble_bundle.predictions,
            jointly_accepted,
            target_coverage=float(frozen_joint_rows.iloc[0]["target_coverage"]),
            num_classes=config.expected_num_classes,
        )
        ensemble_risk_rows.append(
            {
                "candidate": candidate_name,
                "uncertainty": "joint_deployed_review_policy",
                "threshold_source": "validation_seed_ensemble",
                "operating_criterion": str(
                    frozen_joint_rows.iloc[0]["operating_criterion"]
                ),
                "target_population": str(
                    frozen_joint_rows.iloc[0]["target_population"]
                ),
                "tie_policy": str(frozen_joint_rows.iloc[0]["tie_policy"]),
                "policy_component": "joint",
                "policy_scope": str(frozen_joint_rows.iloc[0]["policy_scope"]),
                "marginal_quantile_coverage": float(
                    frozen_joint_rows.iloc[0]["marginal_quantile_coverage"]
                ),
                "uncertainty_threshold": None,
                "target_population_count": int(routable_mask.sum()),
                "unconditionally_reviewed_count": int(
                    len(y_true) - routable_mask.sum()
                ),
                "overall_realized_coverage": overall_joint_applied["realized_coverage"],
                "overall_retained": overall_joint_applied["retained"],
                **joint_applied,
            }
        )
    write_prediction_csv(
        test_dir / "seed_ensemble_predictions.csv.gz",
        pd.concat(ensemble_prediction_frames, ignore_index=True),
    )
    pd.DataFrame(ensemble_metric_rows).to_csv(
        test_dir / "seed_ensemble_metrics.csv", index=False
    )
    pd.DataFrame(ensemble_risk_rows).to_csv(
        test_dir / "seed_ensemble_risk_coverage_at_validation_thresholds.csv",
        index=False,
    )
    matched_checkpoint_predictions_path: Path | None = None
    if matched_checkpoint_labels:
        expected_binding_count = len(matched_checkpoint_labels) * len(config.seeds)
        if (
            len(matched_checkpoint_bindings) != expected_binding_count
            or len(matched_checkpoint_prediction_frames) != 2 * expected_binding_count
        ):
            raise ProtocolStateError(
                "matched-checkpoint inference ablation is missing a frozen "
                "candidate-seed arm"
            )
        matched_checkpoint_predictions_path = (
            test_dir / "matched_checkpoint_inference_predictions.csv.gz"
        )
        write_prediction_csv(
            matched_checkpoint_predictions_path,
            pd.concat(matched_checkpoint_prediction_frames, ignore_index=True),
        )

    reference = str(selection_receipt["paired_reference"])
    comparison_rows: list[dict[str, Any]] = []
    training_seed_sensitivity_rows: list[dict[str, Any]] = []
    comparison_pairs: dict[tuple[str, str], str] = {
        (reference, challenger): f"{challenger}_minus_{reference}"
        for challenger in planned
        if challenger != reference
    }
    for explicit in selection_receipt.get("explicit_paired_comparisons", []):
        comparison_pairs[(explicit["reference"], explicit["challenger"])] = explicit[
            "label"
        ]
    cluster_ids = splits.test["leakage_group_id"].astype(str).to_numpy(copy=True)
    calendar_values = splits.test[config.time_column].to_numpy(copy=True)
    bootstrap_strata_rows, bootstrap_design = cluster_bootstrap_design_receipt(
        cluster_ids,
        y_true,
        calendar_values,
        num_classes=config.expected_num_classes,
        stratification=config.test.bootstrap_stratification,
    )
    bootstrap_strata_path = test_dir / "bootstrap_cluster_strata.csv"
    pd.DataFrame(bootstrap_strata_rows).to_csv(bootstrap_strata_path, index=False)
    cluster_test_rows: list[dict[str, Any]] = []
    matched_checkpoint_comparison_rows: list[dict[str, Any]] = []
    bootstrap_execution: dict[str, Any] | None = None
    training_seed_sensitivity_execution: dict[str, Any] | None = None

    def _bootstrap_execution_record(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "bootstrap_algorithm_id": result["bootstrap_algorithm_id"],
            "bootstrap_algorithm": result["bootstrap_algorithm"],
            "bootstrap_replicates": result["bootstrap_replicates"],
            "bootstrap_seed": result["bootstrap_seed"],
            "bootstrap_rng": result["bootstrap_rng"],
            "bootstrap_rng_stream_derivation": result[
                "bootstrap_rng_stream_derivation"
            ],
            "analysis_role": result["analysis_role"],
            "estimand": result["estimand"],
            "probability_aggregation": result["probability_aggregation"],
            "training_seed_resampling": result["training_seed_resampling"],
            "replicate_seed_rule": result["replicate_seed_rule"],
            "point_estimate_seed_rule": result["point_estimate_seed_rule"],
            "bootstrap_stratification": result["bootstrap_stratification"],
            "stratification_calendar_rule": result["stratification_calendar_rule"],
            "stratification_label_rule": result["stratification_label_rule"],
            "strata_cluster_counts": result["strata_cluster_counts"],
            "cluster_strata_sha256": result["cluster_strata_sha256"],
        }

    for (pair_reference, challenger), comparison_label in comparison_pairs.items():
        for metric in ("accuracy", "macro_f1"):
            comparison = hierarchical_paired_bootstrap(
                paired_probabilities[pair_reference],
                paired_probabilities[challenger],
                cluster_ids=cluster_ids,
                calendar_values=calendar_values,
                metric=metric,
                num_classes=config.expected_num_classes,
                iterations=config.test.bootstrap_iterations,
                confidence_level=config.test.confidence_level,
                random_seed=config.test.bootstrap_seed,
                stratification=config.test.bootstrap_stratification,
            )
            execution = _bootstrap_execution_record(comparison)
            if bootstrap_execution is None:
                bootstrap_execution = execution
            elif bootstrap_execution != execution:
                raise ProtocolStateError(
                    "paired bootstrap design changed across frozen comparisons"
                )
            if any(
                execution.get(key) != bootstrap_design.get(key)
                for key in (
                    "bootstrap_algorithm_id",
                    "bootstrap_algorithm",
                    "bootstrap_stratification",
                    "stratification_calendar_rule",
                    "stratification_label_rule",
                    "strata_cluster_counts",
                    "cluster_strata_sha256",
                )
            ):
                raise ProtocolStateError(
                    "paired bootstrap draw does not match its archived strata table"
                )
            comparison_rows.append(
                {
                    "comparison": comparison_label,
                    "reference": pair_reference,
                    "challenger": challenger,
                    **comparison,
                }
            )
            sensitivity = training_seed_superpopulation_sensitivity_bootstrap(
                paired_probabilities[pair_reference],
                paired_probabilities[challenger],
                cluster_ids=cluster_ids,
                calendar_values=calendar_values,
                metric=metric,
                num_classes=config.expected_num_classes,
                iterations=config.test.training_seed_sensitivity_iterations,
                confidence_level=config.test.confidence_level,
                random_seed=config.test.training_seed_sensitivity_seed,
                stratification=config.test.bootstrap_stratification,
            )
            sensitivity_execution = _bootstrap_execution_record(sensitivity)
            if training_seed_sensitivity_execution is None:
                training_seed_sensitivity_execution = sensitivity_execution
            elif training_seed_sensitivity_execution != sensitivity_execution:
                raise ProtocolStateError(
                    "training-seed sensitivity design changed across comparisons"
                )
            if any(
                sensitivity_execution.get(key) != bootstrap_design.get(key)
                for key in (
                    "bootstrap_stratification",
                    "stratification_calendar_rule",
                    "stratification_label_rule",
                    "strata_cluster_counts",
                    "cluster_strata_sha256",
                )
            ):
                raise ProtocolStateError(
                    "training-seed sensitivity does not reuse the archived strata"
                )
            training_seed_sensitivity_rows.append(
                {
                    "comparison": comparison_label,
                    "reference": pair_reference,
                    "challenger": challenger,
                    **sensitivity,
                }
            )
        pair_y, reference_predictions = seed_ensemble_predictions[pair_reference]
        challenger_y, challenger_predictions = seed_ensemble_predictions[challenger]
        if not np.array_equal(pair_y, challenger_y):
            raise ProtocolStateError(
                f"seed-ensemble labels differ for {comparison_label}"
            )
        cluster_test_rows.append(
            {
                "comparison": comparison_label,
                "reference": pair_reference,
                "challenger": challenger,
                "prediction_vector": "equal_weight_mean_probability_over_all_seeds",
                **cluster_paired_accuracy_test(
                    pair_y,
                    reference_predictions,
                    challenger_predictions,
                    cluster_ids,
                    monte_carlo_iterations=(config.test.cluster_permutation_iterations),
                    random_seed=config.test.cluster_permutation_seed,
                ),
            }
        )
    for (
        candidate_name,
        ablation_label,
    ) in config.test.matched_checkpoint_inference_ablations:
        native_by_seed = matched_checkpoint_native_probabilities[candidate_name]
        pgs_by_seed = paired_probabilities[candidate_name]
        missing_native = sorted(set(config.seeds).difference(native_by_seed))
        missing_pgs = sorted(set(config.seeds).difference(pgs_by_seed))
        if missing_native or missing_pgs:
            raise ProtocolStateError(
                f"matched-checkpoint ablation {ablation_label} lacks native seeds "
                f"{missing_native} or PGS seeds {missing_pgs}"
            )
        for seed in config.seeds:
            if not np.array_equal(native_by_seed[seed][0], pgs_by_seed[seed][0]):
                raise ProtocolStateError(
                    f"matched-checkpoint labels differ for {ablation_label}, "
                    f"seed {seed}"
                )
        for metric in ("accuracy", "macro_f1"):
            comparison = hierarchical_paired_bootstrap(
                native_by_seed,
                pgs_by_seed,
                cluster_ids=cluster_ids,
                calendar_values=calendar_values,
                metric=metric,
                num_classes=config.expected_num_classes,
                iterations=config.test.bootstrap_iterations,
                confidence_level=config.test.confidence_level,
                random_seed=config.test.bootstrap_seed,
                stratification=config.test.bootstrap_stratification,
            )
            execution = _bootstrap_execution_record(comparison)
            if bootstrap_execution is None:
                bootstrap_execution = execution
            elif bootstrap_execution != execution:
                raise ProtocolStateError(
                    "matched-checkpoint bootstrap differs from the frozen Phase-A "
                    "inference design"
                )
            matched_checkpoint_comparison_rows.append(
                {
                    "comparison": ablation_label,
                    "candidate": candidate_name,
                    "reference": ("native_point_same_posterior_checkpoint"),
                    "challenger": ("virtual_ensemble_same_posterior_checkpoint"),
                    "same_checkpoint_within_seed": True,
                    "training_intervention": "none_within_ablation_pair",
                    **comparison,
                }
            )
        native_mean_probabilities = np.mean(
            np.stack([native_by_seed[seed][1] for seed in config.seeds], axis=0),
            axis=0,
        )
        pgs_mean_probabilities = np.mean(
            np.stack([pgs_by_seed[seed][1] for seed in config.seeds], axis=0),
            axis=0,
        )
        cluster_test_rows.append(
            {
                "comparison": ablation_label,
                "reference": "native_point_same_posterior_checkpoint",
                "challenger": "virtual_ensemble_same_posterior_checkpoint",
                "prediction_vector": (
                    "equal_weight_mean_probability_over_all_seeds_same_"
                    "posterior_checkpoints"
                ),
                "same_checkpoint_within_seed": True,
                **cluster_paired_accuracy_test(
                    y_true,
                    native_mean_probabilities.argmax(axis=1).astype(np.int64),
                    pgs_mean_probabilities.argmax(axis=1).astype(np.int64),
                    cluster_ids,
                    monte_carlo_iterations=(config.test.cluster_permutation_iterations),
                    random_seed=config.test.cluster_permutation_seed,
                ),
            }
        )
    comparisons = pd.DataFrame(comparison_rows)
    comparisons.to_csv(test_dir / "paired_bootstrap_comparisons.csv", index=False)
    pd.DataFrame(training_seed_sensitivity_rows).to_csv(
        test_dir / "training_seed_sensitivity_bootstrap.csv", index=False
    )
    matched_checkpoint_comparisons_path: Path | None = None
    if matched_checkpoint_labels:
        matched_checkpoint_comparisons_path = (
            test_dir / "matched_checkpoint_inference_ablations.csv"
        )
        pd.DataFrame(matched_checkpoint_comparison_rows).to_csv(
            matched_checkpoint_comparisons_path,
            index=False,
        )
    cluster_tests = pd.DataFrame(cluster_test_rows)
    if not cluster_tests.empty:
        cluster_tests["multiplicity_family"] = (
            "all_frozen_model_pair_accuracy_comparisons"
        )
        cluster_tests["holm_adjusted_cluster_p"] = holm_adjusted_pvalues(
            cluster_tests["cluster_paired_two_sided_p"].astype(float).tolist()
        )
    cluster_tests.to_csv(test_dir / "cluster_paired_accuracy_tests.csv", index=False)
    test_unit_index_record = _write_unit_index(run_dir, "test", test_receipts)

    matched_checkpoint_artifacts: dict[str, dict[str, Any]] = {}
    if matched_checkpoint_labels:
        if (
            matched_checkpoint_predictions_path is None
            or matched_checkpoint_comparisons_path is None
        ):
            raise ProtocolStateError(
                "matched-checkpoint inference ablation artifacts were not written"
            )
        matched_checkpoint_artifacts = {
            "matched_checkpoint_inference_predictions": artifact_record(
                matched_checkpoint_predictions_path,
                base_dir=run_dir,
            ),
            "matched_checkpoint_inference_ablations": artifact_record(
                matched_checkpoint_comparisons_path,
                base_dir=run_dir,
            ),
        }

    final_receipt = {
        "schema_version": 1,
        "phase": "locked_test_complete",
        "completed_at_utc": utc_now(),
        "protocol_digest": config.protocol_digest(),
        "selection_receipt_digest": selection_receipt["receipt_digest"],
        "input_manifest_digest": object_sha256(input_manifest),
        "class_map_sha256": input_manifest["class_map_sha256"],
        "test_candidates_in_preregistered_order": planned,
        "test_ranking_performed": False,
        "paired_reference": reference,
        "calibration_protocol": selection_receipt["calibration_protocol"],
        "review_policy_applied_unchanged": selection_receipt["review_policy"],
        "prespecified_phase_a_inference_plan": selection_receipt[
            "prespecified_phase_a_inference_plan"
        ],
        "matched_checkpoint_inference_ablation_plan": selection_receipt[
            "matched_checkpoint_inference_ablation_plan"
        ],
        "matched_checkpoint_inference_ablation_execution": {
            "analysis_role": "prespecified_inference_only_ablation",
            "same_loaded_checkpoint_object_used_within_each_seed_pair": True,
            "checkpoint_bindings": sorted(
                matched_checkpoint_bindings,
                key=lambda item: (item["candidate"], int(item["seed"])),
            ),
            "comparison_rows": len(matched_checkpoint_comparison_rows),
            "cluster_accuracy_rows": len(matched_checkpoint_labels),
        },
        "prespecified_phase_a_inference_execution": {
            "paired_bootstrap": bootstrap_execution,
            "training_seed_sensitivity": training_seed_sensitivity_execution,
        },
        "inference_notes": {
            "bootstrap_tail_probabilities": (
                "descriptive fixed-ensemble whole-cluster bootstrap sign/tail "
                "frequencies, not null-hypothesis p-values"
            ),
            "training_seed_sensitivity": (
                "secondary hypothetical training-seed-superpopulation analysis; "
                "not the confidence interval for the deployed fixed five-head "
                "ensemble"
            ),
            "primary_paired_accuracy_test": (
                "one equal-weight seed-mean probability prediction vector per model; "
                "whole leakage_group_id sign flips; Holm correction across the frozen "
                "model-pair family"
            ),
        },
        "seeds": list(config.seeds),
        "artifacts": {
            "metrics_by_seed": artifact_record(
                test_dir / "phase_a_metrics_by_seed.csv", base_dir=run_dir
            ),
            "aggregate_metrics": artifact_record(
                test_dir / "phase_a_metrics_aggregate.csv", base_dir=run_dir
            ),
            "paired_comparisons": artifact_record(
                test_dir / "paired_bootstrap_comparisons.csv", base_dir=run_dir
            ),
            "training_seed_sensitivity": artifact_record(
                test_dir / "training_seed_sensitivity_bootstrap.csv",
                base_dir=run_dir,
            ),
            "bootstrap_cluster_strata": artifact_record(
                bootstrap_strata_path, base_dir=run_dir
            ),
            "cluster_paired_accuracy_tests": artifact_record(
                test_dir / "cluster_paired_accuracy_tests.csv", base_dir=run_dir
            ),
            "seed_ensemble_predictions": artifact_record(
                test_dir / "seed_ensemble_predictions.csv.gz", base_dir=run_dir
            ),
            "seed_ensemble_metrics": artifact_record(
                test_dir / "seed_ensemble_metrics.csv", base_dir=run_dir
            ),
            "seed_ensemble_risk_coverage_at_validation_thresholds": artifact_record(
                test_dir / "seed_ensemble_risk_coverage_at_validation_thresholds.csv",
                base_dir=run_dir,
            ),
            "unit_artifact_index": test_unit_index_record,
            "environment_manifest": artifact_record(
                run_dir / "metadata" / "environment.json", base_dir=run_dir
            ),
            "locked_test_split_audit": artifact_record(
                run_dir / "metadata" / "locked_test_split_audit.json",
                base_dir=run_dir,
            ),
            **matched_checkpoint_artifacts,
        },
    }
    final_receipt["receipt_digest"] = object_sha256(final_receipt)
    write_json(test_dir / "TEST_EVALUATION_COMPLETE.json", final_receipt)
    write_json(
        run_dir / "metadata" / "run_state.json",
        {
            "updated_at_utc": utc_now(),
            "phase": "locked_test_complete",
            "protocol_digest": config.protocol_digest(),
            "test_csv_parsed": True,
            "test_ranking_performed": False,
        },
    )
    return run_dir
