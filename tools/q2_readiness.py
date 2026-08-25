#!/usr/bin/env python3
"""Fail-closed audit of the evidence package required for a Q2 submission.

This command checks that evidence exists and is internally consistent. It does
not predict journal acceptance and cannot replace an editor, ethics board, data
owner, domain expert, or independent reviewer.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import f1_score, log_loss

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm import TARGET_CLASSES
from crm.experiments.metrics import (
    BOOTSTRAP_ALGORITHM_ID,
    TRAINING_SEED_SENSITIVITY_ALGORITHM_ID,
    bootstrap_rng_stream_derivation,
    cluster_paired_accuracy_test,
    hierarchical_paired_bootstrap,
    holm_adjusted_pvalues,
    risk_at_acceptance_mask,
    risk_at_uncertainty_threshold,
    uncertainty_threshold_at_target_coverage,
)
from crm.export_contract import (
    CLASSIFIER_PARITY_TOLERANCES,
    ENCODER_TENSOR_PARITY_TOLERANCES,
    RAW_PIPELINE_PARITY_TOLERANCES,
    ExportContractError,
    validate_export_manifest,
)
from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
    validate_preprocessing_contract,
)


@dataclass(frozen=True)
class Gate:
    name: str
    category: str
    passed: bool
    evidence: str | None
    detail: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _object_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _class_map_sha256(class_map: dict[str, Any]) -> str:
    payload = {
        "schema_version": class_map.get("schema_version"),
        "label_id_column": class_map.get("label_id_column"),
        "label_name_column": class_map.get("label_name_column"),
        "classes": class_map.get("classes"),
    }
    return _object_sha256(payload)


def _resolved_protocol_digest(config: dict[str, Any]) -> str:
    payload = dict(config)
    payload.pop("source_sha256", None)
    payload.pop("source_path", None)
    # ExperimentConfig.protocol_digest intentionally uses json.dumps defaults
    # (ASCII escaping) in addition to sorted compact separators.
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _resolve_record_path(raw: str, receipt: Path) -> Path:
    path = Path(raw)
    if path.is_absolute() and path.is_file():
        return path

    # Evidence packages are expected to remain verifiable after being moved.
    # Prefer paths relative to the receipt, then the nearest run root; for old
    # absolute receipts, fall back only to the artifact basename beside its
    # receipt instead of trusting another arbitrary host path.
    candidates: list[Path] = []
    if not path.is_absolute() and ".." not in path.parts:
        candidates.append((receipt.parent / path).resolve())
        for parent in receipt.parents:
            if (parent / "resolved_config.json").is_file():
                candidates.append((parent / path).resolve())
                break
    candidates.append((receipt.parent / path.name).resolve())
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return path if path.is_absolute() else candidates[0]


def _load_ordered_ids(path: Path, *, id_column: str) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        raw = value if isinstance(value, list) else value.get("ids")
        if not isinstance(raw, list):
            raise ValueError("JSON test IDs must be a list or contain an ids list")
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or id_column not in reader.fieldnames:
                raise ValueError(f"CSV test IDs lack {id_column!r}")
            raw = [row[id_column] for row in reader]
    elif suffix == ".npy":
        import numpy as np

        array = np.load(path, allow_pickle=False)
        if array.ndim != 1:
            raise ValueError("NumPy test IDs must be one-dimensional")
        raw = array.tolist()
    else:
        raw = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    ids = [str(value) for value in raw]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("ordered test IDs must be non-empty and unique")
    return ids


def _ordered_ids_sha256(ids: list[str]) -> str:
    encoded = json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_locked_test_ids(report: dict[str, Any], report_path: Path) -> None:
    manifest_path = _resolve_record_path(str(report["split_manifest"]), report_path)
    manifest = _read_json(manifest_path)
    id_column = manifest.get("parameters", {}).get("id_column")
    test_record = manifest.get("outputs", {}).get("test", {})
    if not isinstance(id_column, str) or not test_record.get("path"):
        raise ValueError("split manifest lacks test-ID contract")
    test_csv = _resolve_record_path(str(test_record["path"]), manifest_path)
    ok, detail = _verify_artifact(test_record, manifest_path)
    if not ok:
        raise ValueError(f"manifested test CSV: {detail}")
    supplied_path = _resolve_record_path(str(report["test_ids"]), report_path)
    supplied = _load_ordered_ids(supplied_path, id_column=id_column)
    manifested = _load_ordered_ids(test_csv, id_column=id_column)
    if supplied != manifested:
        raise ValueError(
            "parity IDs do not exactly equal the manifested locked test order"
        )
    if report.get("ordered_test_ids_sha256") != _ordered_ids_sha256(manifested):
        raise ValueError("ordered test-ID semantic digest mismatch")


def _verify_artifact(record: Any, receipt: Path) -> tuple[bool, str]:
    if (
        not isinstance(record, dict)
        or not record.get("path")
        or not record.get("sha256")
    ):
        return False, "artifact record lacks path/sha256"
    path = _resolve_record_path(str(record["path"]), receipt)
    if not path.is_file():
        return False, f"artifact missing: {path}"
    actual = _sha256(path)
    if actual != record["sha256"]:
        return False, f"artifact hash mismatch: {path}"
    if "rows" in record:
        try:
            row_count = max(sum(1 for _ in path.open(encoding="utf-8-sig")) - 1, 0)
        except UnicodeDecodeError:
            return False, f"row-counted artifact is not UTF-8 text: {path}"
        if row_count != int(record["rows"]):
            return False, f"artifact row count mismatch: {path}"
    return True, str(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("JSON root must be an object")
    return value


def _failed(name: str, category: str, path: Path | None, detail: str) -> Gate:
    return Gate(name, category, False, str(path) if path else None, detail)


def _check_split_manifest(path: Path) -> Gate:
    name, category = "group_temporal_split", "data"
    if not path.is_file():
        return _failed(name, category, path, "split manifest is missing")
    try:
        manifest = _read_json(path)
        if manifest.get("strategy") != "grouped_strict_temporal_holdout":
            raise ValueError("strategy is not grouped_strict_temporal_holdout")
        if manifest.get("near_text_grouping", {}).get("method") not in {
            "simhash_bktree",
            "simhash_lsh",
            "minhash_lsh",
        }:
            raise ValueError("near-text grouping method is absent")
        if not manifest.get("near_image_grouping", {}).get("method"):
            raise ValueError("near-image grouping method is absent")
        if "leakage_group_id" not in manifest.get("group_columns", []):
            raise ValueError("leakage_group_id is not attested")
        grouping = manifest.get("grouping", {})
        if (
            int(grouping.get("missing_images", 0)) != 0
            or int(grouping.get("unreadable_images", 0)) != 0
        ):
            raise ValueError(
                "prespecified Phase-A multimodal split contains missing/unreadable images"
            )
        if manifest.get("parameters", {}).get("allow_missing_images") is not False:
            raise ValueError("allow_missing_images must be false")
        if manifest.get("test_statistics_withheld") is not True:
            raise ValueError("test statistics are not declared withheld")
        if "test" in manifest.get("label_distribution", {}):
            raise ValueError(
                "selection-visible manifest contains test-label statistics"
            )
        class_map = manifest.get("class_map")
        if not isinstance(class_map, dict):
            raise TypeError("canonical class map is missing")
        classes = class_map.get("classes")
        if not isinstance(classes, list) or not classes:
            raise ValueError("canonical class list is empty")
        if [item.get("label_id") for item in classes] != list(range(len(classes))):
            raise ValueError("class IDs/order are not contiguous from zero")
        if class_map.get("sha256") != _class_map_sha256(class_map):
            raise ValueError("class-map semantic digest mismatch")
        preregistration = manifest.get("cutoff_preregistration", {})
        declaration = preregistration.get("declaration")
        if not isinstance(declaration, dict):
            raise TypeError("pre-label cutoff preregistration is missing")
        if declaration.get("test_labels_inspected") is not False:
            raise ValueError(
                "cutoff preregistration does not attest blinded test labels"
            )
        if not declaration.get("data_custodian") or not declaration.get("rationale"):
            raise ValueError("cutoff custodian/rationale is missing")
        if not declaration.get("attempt_log"):
            raise ValueError("cutoff preregistration attempt log is empty")
        if preregistration.get("declaration_sha256") != _object_sha256(declaration):
            raise ValueError("cutoff preregistration declaration digest mismatch")
        if declaration.get("source_snapshot_sha256") != manifest.get("source", {}).get(
            "sha256"
        ):
            raise ValueError(
                "cutoff preregistration targets a different source snapshot"
            )
        outputs = manifest.get("outputs", {})
        verified: list[str] = []
        for split in ("train", "val", "test"):
            ok, detail = _verify_artifact(outputs.get(split), path)
            if not ok:
                raise ValueError(f"{split}: {detail}")
            verified.append(split)
        ranges = manifest.get("strict_temporal_ranges", {})
        train_max = datetime.fromisoformat(ranges["train"]["max"])
        val_min = datetime.fromisoformat(ranges["val"]["min"])
        val_max = datetime.fromisoformat(ranges["val"]["max"])
        test_min = datetime.fromisoformat(ranges["test"]["min"])
        if not train_max < val_min or not val_max < test_min:
            raise ValueError("manifest temporal ranges are not strictly ordered")
        return Gate(
            name,
            category,
            True,
            str(path),
            "verified hashed train/val/test outputs, group isolation attestation, and strict chronology",
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, path, str(exc))


def _verify_records(records: Any, receipt_path: Path) -> tuple[bool, str]:
    if not isinstance(records, dict) or not records:
        return False, "no artifact records"
    for key, record in records.items():
        ok, detail = _verify_artifact(record, receipt_path)
        if not ok:
            return False, f"{key}: {detail}"
    return True, f"{len(records)} artifacts verified"


def _verify_unit_index(
    record: Any,
    *,
    parent_receipt: Path,
    phase: str,
    expected_units: set[tuple[str, int]],
    protocol_digest: str,
    class_map_digest: str,
    candidate_configs: dict[str, dict[str, Any]],
) -> None:
    ok, detail = _verify_artifact(record, parent_receipt)
    if not ok:
        raise ValueError(f"{phase} unit index: {detail}")
    index_path = _resolve_record_path(str(record["path"]), parent_receipt)
    index = _read_json(index_path)
    digest_copy = dict(index)
    stored_digest = digest_copy.pop("content_digest", None)
    if stored_digest != _object_sha256(digest_copy):
        raise ValueError(f"{phase} unit-index content digest mismatch")
    if index.get("phase") != phase:
        raise ValueError(f"{phase} unit-index phase mismatch")
    observed: set[tuple[str, int]] = set()
    for unit in index.get("units", []):
        identity = (str(unit.get("candidate")), int(unit.get("seed", -1)))
        if identity in observed:
            raise ValueError(f"duplicate {phase} unit in index: {identity}")
        observed.add(identity)
        receipt_record = unit.get("unit_receipt")
        ok, detail = _verify_artifact(receipt_record, index_path)
        if not ok:
            raise ValueError(f"{phase} unit {identity}: {detail}")
        unit_receipt_path = _resolve_record_path(
            str(receipt_record["path"]), index_path
        )
        unit_receipt = _read_json(unit_receipt_path)
        candidate = candidate_configs.get(identity[0], {})
        expected_identity = {
            "phase": phase,
            "candidate": identity[0],
            "seed": identity[1],
            "protocol_digest": protocol_digest,
            "class_map_sha256": class_map_digest,
            "model": candidate.get("model"),
            "image_encoder": candidate.get("image_encoder"),
            "text_encoder": candidate.get("text_encoder"),
            "posterior_sampling": candidate.get("posterior_sampling", False),
        }
        mismatched = {
            key: {"expected": expected, "observed": unit_receipt.get(key)}
            for key, expected in expected_identity.items()
            if unit_receipt.get(key) != expected
        }
        if mismatched:
            raise ValueError(f"{phase} unit {identity} identity mismatch: {mismatched}")
        if phase == "selection" and candidate.get("model") == "catboost":
            model_metadata = unit_receipt.get("model_metadata")
            if (
                not isinstance(model_metadata, dict)
                or model_metadata.get("checkpoint_tree_policy")
                != "full_early_stopped_trajectory_for_both_point_and_pgs"
                or model_metadata.get("point_model_trimmed_to_validation_best")
                is not False
                or type(model_metadata.get("trained_tree_count")) is not int
                or model_metadata["trained_tree_count"] < 1
                or model_metadata.get("inference_tree_count")
                != model_metadata["trained_tree_count"]
            ):
                raise ValueError(
                    f"{phase} unit {identity} does not bind the matched point/PGS "
                    "full-trajectory checkpoint policy"
                )
        indexed_artifacts = unit.get("unit_artifacts")
        if indexed_artifacts != unit_receipt.get("artifacts"):
            raise ValueError(f"{phase} unit {identity} index/artifact mismatch")
        ok, detail = _verify_records(indexed_artifacts, unit_receipt_path)
        if not ok:
            raise ValueError(f"{phase} unit {identity}: {detail}")
    if observed != expected_units:
        raise ValueError(
            f"{phase} unit index differs from frozen plan: expected "
            f"{len(expected_units)}, observed {len(observed)}"
        )


def _expected_matched_checkpoint_ablation_plan(
    config: dict[str, Any],
) -> dict[str, Any]:
    ablations = config.get("test", {}).get("matched_checkpoint_inference_ablations")
    if not isinstance(ablations, list) or not ablations:
        raise ValueError(
            "frozen test plan lacks a matched-checkpoint PGS inference ablation"
        )
    normalized_ablations: list[dict[str, str]] = []
    for item in ablations:
        if isinstance(item, dict):
            candidate = item.get("candidate")
            label = item.get("label")
        elif isinstance(item, list) and len(item) == 2:
            candidate, label = item
        else:
            raise TypeError("matched-checkpoint inference ablation plan is invalid")
        if (
            not isinstance(candidate, str)
            or not candidate
            or not isinstance(label, str)
            or not label
        ):
            raise TypeError("matched-checkpoint inference ablation plan is invalid")
        normalized_ablations.append({"candidate": candidate, "label": label})
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
        "virtual_ensembles_per_seed": config.get("virtual_ensembles"),
        "ablations": normalized_ablations,
    }


def _strict_csv_boolean(value: Any, field: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"{field} must be an exact CSV boolean")


def _strict_integer(value: Any, field: str) -> int:
    if isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{field} must be an exact integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an exact integer") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError(f"{field} must be an exact integer")
    return int(numeric)


def _strict_integer_array(values: Any, field: str) -> np.ndarray:
    return np.asarray(
        [_strict_integer(value, field) for value in values],
        dtype=np.int64,
    )


def _numbers_match(observed: Any, expected: Any, *, atol: float = 1e-8) -> bool:
    if expected is None:
        if observed is None:
            return True
        try:
            return math.isnan(float(observed))
        except (TypeError, ValueError):
            return False
    try:
        observed_float = float(observed)
        expected_float = float(expected)
    except (TypeError, ValueError):
        return False
    if math.isnan(expected_float):
        return math.isnan(observed_float)
    return math.isclose(
        observed_float,
        expected_float,
        abs_tol=atol,
        rel_tol=0.0,
    )


def _recompute_validation_review_rows(
    config: dict[str, Any],
    candidate_configs: dict[str, dict[str, Any]],
    aggregate_predictions: dict[str, dict[str, np.ndarray]],
    class_labels: list[str],
) -> list[dict[str, Any]]:
    target_coverage = float(config.get("review_target_coverage", 0.0))
    class_count = int(config.get("expected_num_classes", 0))
    catch_all_index = (
        class_labels.index("Instansi lain") if "Instansi lain" in class_labels else None
    )
    rows: list[dict[str, Any]] = []
    for candidate_name, candidate in candidate_configs.items():
        bundle = aggregate_predictions[candidate_name]
        y_true = bundle["y_true"].astype(np.int64)
        y_pred = bundle["y_pred"].astype(np.int64)
        routable_mask = (
            y_pred != catch_all_index
            if catch_all_index is not None
            else np.ones(len(y_pred), dtype=bool)
        )
        routable_count = int(routable_mask.sum())
        if routable_count < 1:
            raise ValueError(
                f"validation candidate {candidate_name} predicts no routable labels"
            )
        uncertainty_by_measure = {
            "one_minus_confidence": bundle["one_minus_confidence"]
        }
        if candidate.get("posterior_sampling") is True:
            uncertainty_by_measure["epistemic_mutual_information"] = bundle[
                "epistemic_mutual_information"
            ]
        target_retained = max(
            1,
            int(np.ceil(target_coverage * routable_count - 1e-12)),
        )
        routable_uncertainty = {
            measure: uncertainty[routable_mask]
            for measure, uncertainty in uncertainty_by_measure.items()
        }
        chosen_quantile: float | None = None
        chosen_thresholds: dict[str, float] | None = None
        chosen_acceptance: np.ndarray | None = None
        for retained_rank in range(target_retained, routable_count + 1):
            marginal_quantile = retained_rank / routable_count
            thresholds = {
                measure: uncertainty_threshold_at_target_coverage(
                    uncertainty,
                    marginal_quantile,
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
                chosen_acceptance = accepted
                break
        if (
            chosen_quantile is None
            or chosen_thresholds is None
            or chosen_acceptance is None
        ):
            raise ValueError(
                f"validation review threshold search failed for {candidate_name}"
            )
        common = {
            "candidate": candidate_name,
            "threshold_source": config.get("review_threshold_source"),
            "operating_criterion": config.get("review_operating_criterion"),
            "target_population": config.get("review_target_population"),
            "tie_policy": config.get("review_tie_policy"),
            "policy_scope": (
                "model_review_gates_plus_unconditional_labels_excluding_registry"
            ),
            "marginal_quantile_coverage": chosen_quantile,
            "target_population_count": routable_count,
            "unconditionally_reviewed_count": int(len(y_true) - routable_count),
        }
        for measure, uncertainty in uncertainty_by_measure.items():
            threshold = chosen_thresholds[measure]
            conditional = risk_at_uncertainty_threshold(
                y_true[routable_mask],
                y_pred[routable_mask],
                uncertainty[routable_mask],
                uncertainty_threshold=threshold,
                target_coverage=target_coverage,
                num_classes=class_count,
            )
            overall_acceptance = routable_mask & (uncertainty <= threshold)
            overall = risk_at_acceptance_mask(
                y_true,
                y_pred,
                overall_acceptance,
                target_coverage=target_coverage,
                num_classes=class_count,
            )
            rows.append(
                {
                    **common,
                    "uncertainty": measure,
                    "policy_component": "gate",
                    "overall_realized_coverage": overall["realized_coverage"],
                    "overall_retained": overall["retained"],
                    **conditional,
                }
            )
        joint = risk_at_acceptance_mask(
            y_true[routable_mask],
            y_pred[routable_mask],
            chosen_acceptance,
            target_coverage=target_coverage,
            num_classes=class_count,
        )
        overall_joint_acceptance = np.zeros(len(y_true), dtype=bool)
        overall_joint_acceptance[routable_mask] = chosen_acceptance
        overall_joint = risk_at_acceptance_mask(
            y_true,
            y_pred,
            overall_joint_acceptance,
            target_coverage=target_coverage,
            num_classes=class_count,
        )
        rows.append(
            {
                **common,
                "uncertainty": "joint_deployed_review_policy",
                "policy_component": "joint",
                "uncertainty_threshold": None,
                "overall_realized_coverage": overall_joint["realized_coverage"],
                "overall_retained": overall_joint["retained"],
                **joint,
            }
        )
    return rows


def _validate_validation_selection_semantics(
    config: dict[str, Any],
    inputs: dict[str, Any],
    selection: dict[str, Any],
    *,
    input_manifest_path: Path,
    selection_receipt_path: Path,
) -> None:
    import pandas as pd

    seeds = [
        _strict_integer(seed, "preregistered selection seed")
        for seed in config.get("seeds", [])
    ]
    candidates = [
        item for item in config.get("candidates", []) if isinstance(item, dict)
    ]
    candidate_configs = {str(item.get("name")): item for item in candidates}
    candidate_order = list(candidate_configs)
    if not candidate_order or len(candidate_configs) != len(candidates):
        raise ValueError("resolved candidate family is empty or duplicated")
    class_count = _strict_integer(
        config.get("expected_num_classes"),
        "expected class count",
    )
    id_column = str(config.get("id_column", ""))
    label_column = str(config.get("label_column", ""))
    if class_count < 2 or not id_column or not label_column:
        raise ValueError("validation reconstruction config is incomplete")
    probability_columns = [f"prob_{index}" for index in range(class_count)]
    class_map = inputs.get("class_map", {})
    class_labels = [
        str(item.get("label_name")) for item in class_map.get("classes", [])
    ]
    if len(class_labels) != class_count or len(set(class_labels)) != class_count:
        raise ValueError("class map is invalid for validation reconstruction")
    validation_record = inputs.get("splits", {}).get("val")
    if not isinstance(validation_record, dict):
        raise TypeError("input manifest lacks the validation split record")
    validation_path = _resolve_record_path(
        str(validation_record.get("path", "")),
        input_manifest_path,
    )
    validation = pd.read_csv(validation_path)
    if (
        validation.empty
        or id_column not in validation
        or label_column not in validation
    ):
        raise ValueError("validation split lacks required selection columns")
    expected_ids = validation[id_column].astype(str).tolist()
    expected_y = _strict_integer_array(
        validation[label_column],
        "validation label",
    )
    if (
        len(set(expected_ids)) != len(expected_ids)
        or (expected_y < 0).any()
        or (expected_y >= class_count).any()
    ):
        raise ValueError("validation IDs or labels are invalid")

    selection_artifacts = selection.get("artifacts", {})
    unit_index_record = selection_artifacts.get("unit_artifact_index")
    aggregate_record = selection_artifacts.get("validation_seed_ensemble_predictions")
    leaderboard_record = selection_artifacts.get("validation_leaderboard")
    ensemble_metrics_record = selection_artifacts.get(
        "validation_seed_ensemble_metrics"
    )
    eligible_record = selection_artifacts.get(
        "validation_deployment_eligible_leaderboard"
    )
    review_record = selection_artifacts.get("validation_review_operating_points")
    if any(
        not isinstance(record, dict)
        for record in (
            unit_index_record,
            aggregate_record,
            leaderboard_record,
            ensemble_metrics_record,
            eligible_record,
            review_record,
        )
    ):
        raise TypeError("selection receipt lacks validation reconstruction artifacts")
    unit_index_path = _resolve_record_path(
        str(unit_index_record["path"]), selection_receipt_path
    )
    unit_index = _read_json(unit_index_path)
    units = unit_index.get("units")
    if not isinstance(units, list):
        raise TypeError("selection unit index is invalid")
    expected_unit_identities = {
        (candidate, seed) for candidate in candidate_order for seed in seeds
    }
    observed_unit_identities: list[tuple[str, int]] = []
    for unit in units:
        if not isinstance(unit, dict):
            raise TypeError("selection unit index contains a non-object row")
        observed_unit_identities.append(
            (
                str(unit.get("candidate", "")),
                _strict_integer(unit.get("seed"), "selection unit seed"),
            )
        )
    if set(observed_unit_identities) != expected_unit_identities or len(
        observed_unit_identities
    ) != len(expected_unit_identities):
        raise ValueError("selection unit index differs from the candidate/seed plan")

    unit_probabilities: dict[tuple[str, int], np.ndarray] = {}
    unit_expected_entropy: dict[tuple[str, int], np.ndarray] = {}
    unit_checkpoint_records: dict[tuple[str, int], dict[str, Any]] = {}
    unit_checkpoint_sizes: dict[tuple[str, int], int] = {}
    metadata_columns = list(
        dict.fromkeys(
            [
                str(config.get("embedding_index_column", "")),
                str(config.get("label_name_column", "")),
                *[str(column) for column in config.get("group_columns", [])],
            ]
        )
    )
    metadata_columns = [
        column
        for column in metadata_columns
        if column and column not in {id_column, label_column}
    ]
    missing_validation_metadata = [
        column for column in metadata_columns if column not in validation
    ]
    if missing_validation_metadata:
        raise ValueError(
            "validation split lacks frozen metadata columns: "
            f"{missing_validation_metadata}"
        )
    label_name_column = str(config.get("label_name_column", ""))
    if label_name_column:
        expected_label_names = [class_labels[index] for index in expected_y]
        if validation[label_name_column].astype(str).tolist() != expected_label_names:
            raise ValueError("validation label-name metadata differs from class map")

    for unit in units:
        candidate_name = str(unit["candidate"])
        seed = _strict_integer(unit["seed"], "selection unit seed")
        unit_artifacts = unit.get("unit_artifacts")
        if not isinstance(unit_artifacts, dict):
            raise TypeError(
                f"selection unit {candidate_name}/{seed} lacks artifact records"
            )
        prediction_record = unit_artifacts.get("predictions")
        checkpoint_record = unit_artifacts.get("checkpoint")
        if not isinstance(prediction_record, dict):
            raise TypeError(f"selection unit {candidate_name}/{seed} lacks predictions")
        if not isinstance(checkpoint_record, dict):
            raise TypeError(f"selection unit {candidate_name}/{seed} lacks checkpoint")
        checkpoint_path = _resolve_record_path(
            str(checkpoint_record.get("path", "")),
            selection_receipt_path,
        )
        if not checkpoint_path.is_file():
            raise ValueError(
                f"selection unit {candidate_name}/{seed} checkpoint is missing"
            )
        actual_checkpoint_size = checkpoint_path.stat().st_size
        recorded_checkpoint_size = _strict_integer(
            checkpoint_record.get("size_bytes"),
            f"selection unit {candidate_name}/{seed} checkpoint size",
        )
        if (
            actual_checkpoint_size < 1
            or recorded_checkpoint_size != actual_checkpoint_size
        ):
            raise ValueError(
                f"selection unit {candidate_name}/{seed} checkpoint size does not "
                "match the actual file"
            )
        unit_checkpoint_records[(candidate_name, seed)] = checkpoint_record
        unit_checkpoint_sizes[(candidate_name, seed)] = actual_checkpoint_size
        prediction_path = _resolve_record_path(
            str(prediction_record.get("path", "")),
            selection_receipt_path,
        )
        frame = pd.read_csv(prediction_path)
        required_columns = {
            id_column,
            "y_true",
            "y_pred",
            "confidence",
            "correct",
            *probability_columns,
            *metadata_columns,
        }
        if len(frame) != len(expected_ids) or not required_columns.issubset(frame):
            raise ValueError(
                f"selection unit {candidate_name}/{seed} prediction shape is invalid"
            )
        probabilities = frame[probability_columns].to_numpy(dtype=np.float64)
        unexpected_probability_columns = {
            column for column in frame.columns if re.fullmatch(r"prob_\d+", str(column))
        }.difference(probability_columns)
        expected_uncertainty_columns = (
            {
                "uncertainty_predictive_entropy",
                "uncertainty_expected_data_entropy",
                "uncertainty_epistemic_mutual_information",
            }
            if candidate_configs[candidate_name].get("posterior_sampling") is True
            else {
                "uncertainty_predictive_entropy",
                "uncertainty_one_minus_confidence",
            }
        )
        observed_uncertainty_columns = {
            str(column)
            for column in frame.columns
            if str(column).startswith("uncertainty_")
        }
        if (
            frame[id_column].astype(str).tolist() != expected_ids
            or not np.array_equal(
                _strict_integer_array(
                    frame["y_true"],
                    f"selection unit {candidate_name}/{seed} y_true",
                ),
                expected_y,
            )
            or any(
                frame[column].astype(str).tolist()
                != validation[column].astype(str).tolist()
                for column in metadata_columns
            )
            or unexpected_probability_columns
            or observed_uncertainty_columns != expected_uncertainty_columns
            or not np.isfinite(probabilities).all()
            or (probabilities < -1e-8).any()
            or (probabilities > 1.0 + 1e-8).any()
            or not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0)
        ):
            raise ValueError(
                f"selection unit {candidate_name}/{seed} predictions are invalid"
            )
        probabilities = np.clip(probabilities, 0.0, 1.0)
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        canonical_predictions = probabilities.argmax(axis=1).astype(np.int64)
        predictive_entropy = -np.sum(
            probabilities * np.log(np.clip(probabilities, 1e-12, 1.0)),
            axis=1,
        )
        if (
            not np.array_equal(
                _strict_integer_array(
                    frame["y_pred"],
                    f"selection unit {candidate_name}/{seed} y_pred",
                ),
                canonical_predictions,
            )
            or not np.allclose(
                frame["confidence"].to_numpy(dtype=np.float64),
                probabilities.max(axis=1),
                atol=5e-9,
                rtol=0.0,
            )
            or not np.array_equal(
                np.asarray(
                    [
                        _strict_csv_boolean(
                            value,
                            f"selection unit {candidate_name}/{seed} correct",
                        )
                        for value in frame["correct"]
                    ],
                    dtype=bool,
                ),
                canonical_predictions == expected_y,
            )
            or not np.allclose(
                frame["uncertainty_predictive_entropy"].to_numpy(dtype=np.float64),
                predictive_entropy,
                atol=5e-9,
                rtol=0.0,
            )
        ):
            raise ValueError(
                f"selection unit {candidate_name}/{seed} derived values are invalid"
            )
        unit_probabilities[(candidate_name, seed)] = probabilities
        expected_entropy_column = "uncertainty_expected_data_entropy"
        if candidate_configs[candidate_name].get("posterior_sampling") is True:
            entropy = frame[expected_entropy_column].to_numpy(dtype=np.float64)
            epistemic_mi = frame["uncertainty_epistemic_mutual_information"].to_numpy(
                dtype=np.float64
            )
            if (
                entropy.shape != expected_y.shape
                or not np.isfinite(entropy).all()
                or (entropy < 0.0).any()
                or (entropy > math.log(class_count) + 5e-9).any()
                or not np.isfinite(epistemic_mi).all()
                or (epistemic_mi < 0.0).any()
                or not np.allclose(
                    epistemic_mi,
                    np.maximum(predictive_entropy - entropy, 0.0),
                    atol=5e-9,
                    rtol=0.0,
                )
            ):
                raise ValueError(
                    f"PGS selection unit {candidate_name}/{seed} uncertainty is invalid"
                )
            unit_expected_entropy[(candidate_name, seed)] = entropy
        else:
            one_minus_confidence = frame["uncertainty_one_minus_confidence"].to_numpy(
                dtype=np.float64
            )
            if (
                not np.isfinite(one_minus_confidence).all()
                or (one_minus_confidence < 0.0).any()
                or not np.allclose(
                    one_minus_confidence,
                    1.0 - probabilities.max(axis=1),
                    atol=5e-9,
                    rtol=0.0,
                )
            ):
                raise ValueError(
                    f"point selection unit {candidate_name}/{seed} uncertainty is "
                    "invalid"
                )

    aggregate_path = _resolve_record_path(
        str(aggregate_record["path"]), selection_receipt_path
    )
    aggregate_frame = pd.read_csv(aggregate_path)
    expected_aggregate_rows = len(candidate_order) * len(expected_ids)
    expected_candidate_blocks = [
        candidate_name
        for candidate_name in candidate_order
        for _ in range(len(expected_ids))
    ]
    aggregate_required_columns = {
        "candidate",
        "seed_count",
        id_column,
        "y_true",
        "y_pred",
        "confidence",
        "correct",
        "uncertainty_predictive_entropy",
        "uncertainty_one_minus_confidence",
        *probability_columns,
        *metadata_columns,
    }
    if any(
        candidate.get("posterior_sampling") is True
        for candidate in candidate_configs.values()
    ):
        aggregate_required_columns.update(
            {
                "uncertainty_expected_data_entropy",
                "uncertainty_epistemic_mutual_information",
            }
        )
    unexpected_aggregate_probability_columns = {
        column
        for column in aggregate_frame.columns
        if re.fullmatch(r"prob_\d+", str(column))
    }.difference(probability_columns)
    aggregate_uncertainty_columns = {
        str(column)
        for column in aggregate_frame.columns
        if str(column).startswith("uncertainty_")
    }
    allowed_aggregate_uncertainty_columns = {
        "uncertainty_predictive_entropy",
        "uncertainty_one_minus_confidence",
        "uncertainty_expected_data_entropy",
        "uncertainty_epistemic_mutual_information",
    }
    if (
        aggregate_frame.empty
        or len(aggregate_frame) != expected_aggregate_rows
        or not aggregate_required_columns.issubset(aggregate_frame)
        or unexpected_aggregate_probability_columns
        or aggregate_frame.get("candidate", pd.Series(dtype=str)).astype(str).tolist()
        != expected_candidate_blocks
        or not aggregate_uncertainty_columns.issubset(
            allowed_aggregate_uncertainty_columns
        )
        or aggregate_frame.duplicated(subset=["candidate", id_column]).any()
    ):
        raise ValueError(
            "validation ensemble predictions have missing, duplicate, or extra rows"
        )
    aggregate_predictions: dict[str, dict[str, np.ndarray]] = {}
    leaderboard_rows: list[dict[str, Any]] = []
    labels = np.arange(class_count)
    for candidate_name in candidate_order:
        candidate = candidate_configs[candidate_name]
        subset = aggregate_frame[
            aggregate_frame["candidate"].astype(str) == candidate_name
        ]
        observed_probabilities = subset[probability_columns].to_numpy(dtype=np.float64)
        reconstructed = np.mean(
            np.stack(
                [unit_probabilities[(candidate_name, seed)] for seed in seeds],
                axis=0,
            ),
            axis=0,
        )
        reconstructed /= reconstructed.sum(axis=1, keepdims=True)
        y_pred = reconstructed.argmax(axis=1).astype(np.int64)
        predictive_entropy = -np.sum(
            reconstructed * np.log(np.clip(reconstructed, 1e-12, 1.0)),
            axis=1,
        )
        one_minus_confidence = 1.0 - reconstructed.max(axis=1)
        seed_counts = [
            _strict_integer(value, f"validation ensemble {candidate_name} seed_count")
            for value in subset["seed_count"]
        ]
        if (
            subset[id_column].astype(str).tolist() != expected_ids
            or not np.array_equal(
                _strict_integer_array(
                    subset["y_true"],
                    f"validation ensemble {candidate_name} y_true",
                ),
                expected_y,
            )
            or any(
                subset[column].astype(str).tolist()
                != validation[column].astype(str).tolist()
                for column in metadata_columns
            )
            or set(seed_counts) != {len(seeds)}
            or not np.isfinite(observed_probabilities).all()
            or (observed_probabilities < 0.0).any()
            or (observed_probabilities > 1.0).any()
            or not np.allclose(
                observed_probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0
            )
            or not np.allclose(
                observed_probabilities, reconstructed, atol=5e-9, rtol=0.0
            )
            or not np.array_equal(
                _strict_integer_array(
                    subset["y_pred"],
                    f"validation ensemble {candidate_name} y_pred",
                ),
                y_pred,
            )
            or not np.allclose(
                subset["confidence"].to_numpy(dtype=np.float64),
                reconstructed.max(axis=1),
                atol=5e-9,
                rtol=0.0,
            )
            or not np.array_equal(
                np.asarray(
                    [
                        _strict_csv_boolean(value, "correct")
                        for value in subset["correct"]
                    ],
                    dtype=bool,
                ),
                y_pred == expected_y,
            )
            or not np.allclose(
                subset["uncertainty_predictive_entropy"].to_numpy(dtype=np.float64),
                predictive_entropy,
                atol=5e-9,
                rtol=0.0,
            )
            or not np.allclose(
                subset["uncertainty_one_minus_confidence"].to_numpy(dtype=np.float64),
                one_minus_confidence,
                atol=5e-9,
                rtol=0.0,
            )
        ):
            raise ValueError(
                f"validation ensemble {candidate_name} does not reconstruct from "
                "its five seed predictions"
            )
        bundle: dict[str, np.ndarray] = {
            "y_true": expected_y.copy(),
            "y_pred": y_pred,
            "probabilities": reconstructed,
            "predictive_entropy": predictive_entropy,
            "one_minus_confidence": one_minus_confidence,
        }
        if candidate.get("posterior_sampling") is True:
            expected_data_entropy = np.mean(
                np.stack(
                    [unit_expected_entropy[(candidate_name, seed)] for seed in seeds],
                    axis=0,
                ),
                axis=0,
            )
            epistemic_mi = np.maximum(
                predictive_entropy - expected_data_entropy,
                0.0,
            )
            observed_expected_entropy = subset[
                "uncertainty_expected_data_entropy"
            ].to_numpy(dtype=np.float64)
            observed_epistemic_mi = subset[
                "uncertainty_epistemic_mutual_information"
            ].to_numpy(dtype=np.float64)
            if (
                not np.isfinite(observed_expected_entropy).all()
                or (observed_expected_entropy < 0.0).any()
                or (observed_expected_entropy > math.log(class_count) + 5e-9).any()
                or not np.isfinite(observed_epistemic_mi).all()
                or (observed_epistemic_mi < 0.0).any()
                or not np.allclose(
                    observed_expected_entropy,
                    expected_data_entropy,
                    atol=5e-9,
                    rtol=0.0,
                )
                or not np.allclose(
                    observed_epistemic_mi,
                    epistemic_mi,
                    atol=5e-9,
                    rtol=0.0,
                )
            ):
                raise ValueError(
                    f"validation PGS uncertainty does not reconstruct for "
                    f"{candidate_name}"
                )
            bundle["expected_data_entropy"] = expected_data_entropy
            bundle["epistemic_mutual_information"] = epistemic_mi
        else:
            for column in (
                "uncertainty_expected_data_entropy",
                "uncertainty_epistemic_mutual_information",
            ):
                if column in subset and subset[column].notna().any():
                    raise ValueError(
                        f"point validation ensemble {candidate_name} carries PGS-only "
                        "uncertainty"
                    )
        aggregate_predictions[candidate_name] = bundle
        checkpoint_size = sum(
            unit_checkpoint_sizes[(candidate_name, seed)] for seed in seeds
        )
        leaderboard_rows.append(
            {
                "candidate": candidate_name,
                "ensemble_macro_f1": float(
                    f1_score(
                        expected_y,
                        y_pred,
                        labels=labels,
                        average="macro",
                        zero_division=0,
                    )
                ),
                "ensemble_nll": float(
                    log_loss(expected_y, reconstructed, labels=labels)
                ),
                "total_checkpoint_size_bytes": checkpoint_size,
            }
        )

    model_records = selection.get("model_records")
    if not isinstance(model_records, dict):
        raise TypeError("selection receipt model records are invalid")
    planned_candidates = {
        str(name) for name in selection.get("planned_test_candidates", [])
    }
    if set(model_records) != planned_candidates:
        raise ValueError("selection model records differ from the frozen test plan")
    for candidate_name, seed_records in model_records.items():
        if candidate_name not in candidate_configs or not isinstance(
            seed_records, dict
        ):
            raise TypeError("selection model record candidate is invalid")
        if set(seed_records) != {str(seed) for seed in seeds}:
            raise ValueError(
                f"selection model records are incomplete for {candidate_name}"
            )
        for seed in seeds:
            if (
                seed_records[str(seed)]
                != unit_checkpoint_records[(candidate_name, seed)]
            ):
                raise ValueError(
                    f"selection model checkpoint record differs from unit evidence "
                    f"for {candidate_name}/{seed}"
                )

    recomputed_leaderboard = (
        pd.DataFrame(leaderboard_rows)
        .sort_values(
            [
                "ensemble_macro_f1",
                "ensemble_nll",
                "total_checkpoint_size_bytes",
                "candidate",
            ],
            ascending=[False, True, True, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )

    def validate_full_leaderboard(record: dict[str, Any], artifact_name: str) -> None:
        path = _resolve_record_path(str(record["path"]), selection_receipt_path)
        frame = pd.read_csv(path)
        required = {
            "candidate",
            "seeds_completed",
            "probability_aggregation",
            "ensemble_macro_f1",
            "ensemble_nll",
            "total_checkpoint_size_bytes",
        }
        if len(frame) != len(recomputed_leaderboard) or not required.issubset(frame):
            raise ValueError(f"{artifact_name} shape is invalid")
        if (
            frame["candidate"].astype(str).tolist()
            != recomputed_leaderboard["candidate"].astype(str).tolist()
        ):
            raise ValueError(
                "validation leaderboard does not recompute from five-seed probabilities"
            )
        for index in range(len(recomputed_leaderboard)):
            if (
                _strict_integer(
                    frame.iloc[index]["seeds_completed"],
                    f"{artifact_name} completed seed count",
                )
                != len(seeds)
                or str(frame.iloc[index]["probability_aggregation"])
                != "equal_weight_arithmetic_mean"
            ):
                raise ValueError(
                    f"{artifact_name} does not bind every preregistered seed"
                )
            for field in ("ensemble_macro_f1", "ensemble_nll"):
                if not _numbers_match(
                    frame.iloc[index][field],
                    recomputed_leaderboard.iloc[index][field],
                    atol=1e-12,
                ):
                    raise ValueError(
                        "validation leaderboard does not recompute from five-seed "
                        "probabilities"
                    )
            observed_size = _strict_integer(
                frame.iloc[index]["total_checkpoint_size_bytes"],
                f"{artifact_name} checkpoint size",
            )
            expected_size = int(
                recomputed_leaderboard.iloc[index]["total_checkpoint_size_bytes"]
            )
            if observed_size != expected_size:
                raise ValueError(
                    "validation leaderboard checkpoint-size tie-break does not "
                    "recompute from actual checkpoint files"
                )

    validate_full_leaderboard(leaderboard_record, "validation_leaderboard")
    validate_full_leaderboard(
        ensemble_metrics_record,
        "validation_seed_ensemble_metrics",
    )
    eligible_names = [
        str(name) for name in config.get("deployment_eligible_candidates", [])
    ]
    recomputed_eligible = recomputed_leaderboard[
        recomputed_leaderboard["candidate"].isin(eligible_names)
    ].copy()
    recomputed_eligible.insert(
        1,
        "global_validation_rank",
        recomputed_eligible.index.to_numpy() + 1,
    )
    recomputed_eligible = recomputed_eligible.reset_index(drop=True)
    eligible_path = _resolve_record_path(
        str(eligible_record["path"]), selection_receipt_path
    )
    eligible = pd.read_csv(eligible_path)
    if (
        len(eligible) != len(recomputed_eligible)
        or not {
            "candidate",
            "global_validation_rank",
            "seeds_completed",
            "probability_aggregation",
            "ensemble_macro_f1",
            "ensemble_nll",
            "total_checkpoint_size_bytes",
        }.issubset(eligible)
        or recomputed_eligible.empty
    ):
        raise ValueError("deployment-eligible validation leaderboard is invalid")
    observed_global_ranks = [
        _strict_integer(value, "deployment-eligible global validation rank")
        for value in eligible["global_validation_rank"]
    ]
    if (
        eligible["candidate"].astype(str).tolist()
        != recomputed_eligible["candidate"].astype(str).tolist()
        or observed_global_ranks
        != recomputed_eligible["global_validation_rank"].astype(int).tolist()
        or str(selection.get("selected_candidate", ""))
        != str(recomputed_eligible.iloc[0]["candidate"])
    ):
        raise ValueError(
            "deployment-eligible winner does not recompute from validation evidence"
        )
    for index in range(len(recomputed_eligible)):
        if (
            _strict_integer(
                eligible.iloc[index]["seeds_completed"],
                "deployment-eligible completed seed count",
            )
            != len(seeds)
            or str(eligible.iloc[index]["probability_aggregation"])
            != "equal_weight_arithmetic_mean"
        ):
            raise ValueError("deployment-eligible leaderboard does not bind every seed")
        for field in ("ensemble_macro_f1", "ensemble_nll"):
            if not _numbers_match(
                eligible.iloc[index][field],
                recomputed_eligible.iloc[index][field],
                atol=1e-12,
            ):
                raise ValueError(
                    "deployment-eligible validation metrics do not recompute"
                )
        if _strict_integer(
            eligible.iloc[index]["total_checkpoint_size_bytes"],
            "deployment-eligible checkpoint size",
        ) != int(recomputed_eligible.iloc[index]["total_checkpoint_size_bytes"]):
            raise ValueError(
                "deployment-eligible checkpoint-size tie-break does not recompute"
            )

    expected_review_rows = _recompute_validation_review_rows(
        config,
        candidate_configs,
        aggregate_predictions,
        class_labels,
    )
    review_path = _resolve_record_path(
        str(review_record["path"]), selection_receipt_path
    )
    review_points = pd.read_csv(review_path)
    expected_review_identities = {
        (str(row["candidate"]), str(row["uncertainty"])) for row in expected_review_rows
    }
    observed_review_identities = set(
        zip(
            review_points["candidate"].astype(str),
            review_points["uncertainty"].astype(str),
            strict=True,
        )
    )
    if observed_review_identities != expected_review_identities or len(
        review_points
    ) != len(expected_review_rows):
        raise ValueError("validation review operating-point rows are incomplete")
    review_by_identity = {
        (str(row["candidate"]), str(row["uncertainty"])): row
        for _, row in review_points.iterrows()
    }
    string_fields = {
        "threshold_source",
        "operating_criterion",
        "target_population",
        "tie_policy",
        "policy_component",
        "policy_scope",
    }
    integer_fields = {
        "target_population_count",
        "unconditionally_reviewed_count",
        "overall_retained",
        "retained",
    }
    for expected in expected_review_rows:
        identity = (str(expected["candidate"]), str(expected["uncertainty"]))
        observed = review_by_identity[identity]
        for field in string_fields:
            if str(observed[field]) != str(expected[field]):
                raise ValueError(
                    f"validation review policy field {field} does not recompute"
                )
        for field in integer_fields:
            if _strict_integer(observed[field], f"validation review {field}") != int(
                expected[field]
            ):
                raise ValueError(f"validation review count {field} does not recompute")
        numeric_fields = {
            "marginal_quantile_coverage",
            "overall_realized_coverage",
            "target_coverage",
            "realized_coverage",
            "selective_risk",
            "selective_macro_f1",
            "uncertainty_threshold",
        }
        for field in numeric_fields:
            if not _numbers_match(observed[field], expected.get(field), atol=1e-12):
                raise ValueError(
                    f"validation review statistic {field} does not recompute"
                )

    selected = str(selection.get("selected_candidate", ""))
    selected_candidate = candidate_configs[selected]
    selected_expected_rows = {
        str(row["uncertainty"]): row
        for row in expected_review_rows
        if row["candidate"] == selected
    }
    confidence_row = selected_expected_rows["one_minus_confidence"]
    joint_row = selected_expected_rows["joint_deployed_review_policy"]
    epistemic_row = selected_expected_rows.get("epistemic_mutual_information")
    expected_policy = {
        "candidate": selected,
        "threshold_source": config.get("review_threshold_source"),
        "selection_split": "validation",
        "operating_criterion": config.get("review_operating_criterion"),
        "target_coverage": float(config.get("review_target_coverage")),
        "target_population": config.get("review_target_population"),
        "tie_policy": config.get("review_tie_policy"),
        "policy_scope": joint_row["policy_scope"],
        "marginal_quantile_coverage": joint_row["marginal_quantile_coverage"],
        "minimum_confidence": 1.0 - float(confidence_row["uncertainty_threshold"]),
        "maximum_one_minus_confidence": confidence_row["uncertainty_threshold"],
        "maximum_epistemic_mutual_information": (
            epistemic_row["uncertainty_threshold"] if epistemic_row else None
        ),
        "epistemic_uncertainty_semantics": (
            "joint_training_seed_pgs_component_mutual_information_nats"
            if selected_candidate.get("posterior_sampling") is True
            else None
        ),
        "epistemic_component_axis": (
            "training_seed_x_pgs_virtual_member"
            if selected_candidate.get("posterior_sampling") is True
            else None
        ),
        "epistemic_component_count": (
            len(seeds) * int(config.get("virtual_ensembles"))
            if selected_candidate.get("posterior_sampling") is True
            else None
        ),
        "epistemic_training_seed_count": (
            len(seeds) if selected_candidate.get("posterior_sampling") is True else None
        ),
        "epistemic_virtual_ensembles_per_seed": (
            int(config.get("virtual_ensembles"))
            if selected_candidate.get("posterior_sampling") is True
            else None
        ),
        "validation_realized_confidence_coverage": confidence_row["realized_coverage"],
        "validation_confidence_selective_risk": confidence_row["selective_risk"],
        "validation_realized_epistemic_coverage": (
            epistemic_row["realized_coverage"] if epistemic_row else None
        ),
        "validation_epistemic_selective_risk": (
            epistemic_row["selective_risk"] if epistemic_row else None
        ),
        "validation_joint_realized_coverage": joint_row["realized_coverage"],
        "validation_joint_overall_realized_coverage": joint_row[
            "overall_realized_coverage"
        ],
        "validation_joint_selective_risk": joint_row["selective_risk"],
        "validation_target_population_count": joint_row["target_population_count"],
        "validation_unconditionally_reviewed_count": joint_row[
            "unconditionally_reviewed_count"
        ],
        "unconditionally_reviewed_labels": (
            ["Instansi lain"] if "Instansi lain" in class_labels else []
        ),
        "routable_labels": [
            label for label in class_labels if label != "Instansi lain"
        ],
    }
    policy = selection.get("review_policy")
    if not isinstance(policy, dict) or set(policy) != set(expected_policy):
        raise ValueError("selection review policy shape does not recompute")
    for field, expected in expected_policy.items():
        observed = policy.get(field)
        if isinstance(expected, float):
            matches = _numbers_match(observed, expected, atol=1e-12)
        elif isinstance(expected, int):
            try:
                matches = _strict_integer(
                    observed,
                    f"selection review policy {field}",
                ) == int(expected)
            except (TypeError, ValueError):
                matches = False
        else:
            matches = observed == expected
        if not matches:
            raise ValueError(
                f"selection review policy field {field} does not recompute"
            )


def _validate_matched_checkpoint_inference_ablation(
    config: dict[str, Any],
    inputs: dict[str, Any],
    selection: dict[str, Any],
    test: dict[str, Any],
    *,
    input_manifest_path: Path,
    test_receipt_path: Path,
) -> None:
    import pandas as pd

    expected_plan = _expected_matched_checkpoint_ablation_plan(config)
    if (
        selection.get("matched_checkpoint_inference_ablation_plan") != expected_plan
        or test.get("matched_checkpoint_inference_ablation_plan") != expected_plan
    ):
        raise ValueError(
            "matched-checkpoint inference ablation was not frozen before test access"
        )
    seeds = [int(seed) for seed in config.get("seeds", [])]
    candidate_configs = {
        str(item.get("name")): item
        for item in config.get("candidates", [])
        if isinstance(item, dict) and item.get("name")
    }
    fixed_candidates = set(config.get("test", {}).get("fixed_candidates", []))
    configured_ablations = {
        str(item["candidate"]): str(item["label"])
        for item in expected_plan["ablations"]
    }
    if len(configured_ablations) != len(expected_plan["ablations"]):
        raise ValueError("matched-checkpoint ablation candidates must be unique")
    for candidate_name in configured_ablations:
        candidate = candidate_configs.get(candidate_name, {})
        if (
            candidate.get("model") != "catboost"
            or candidate.get("posterior_sampling") is not True
            or candidate_name not in fixed_candidates
        ):
            raise ValueError(
                "matched-checkpoint inference ablation is not bound to a frozen "
                f"posterior CatBoost test candidate: {candidate_name}"
            )

    artifacts = test.get("artifacts", {})
    predictions_record = artifacts.get("matched_checkpoint_inference_predictions")
    comparisons_record = artifacts.get("matched_checkpoint_inference_ablations")
    cluster_tests_record = artifacts.get("cluster_paired_accuracy_tests")
    if (
        not isinstance(predictions_record, dict)
        or not isinstance(comparisons_record, dict)
        or not isinstance(cluster_tests_record, dict)
    ):
        raise TypeError("matched-checkpoint ablation artifacts are absent")
    predictions_path = _resolve_record_path(
        str(predictions_record.get("path", "")), test_receipt_path
    )
    comparisons_path = _resolve_record_path(
        str(comparisons_record.get("path", "")), test_receipt_path
    )
    cluster_tests_path = _resolve_record_path(
        str(cluster_tests_record.get("path", "")), test_receipt_path
    )
    predictions = pd.read_csv(predictions_path)
    comparisons = pd.read_csv(comparisons_path)
    archived_cluster_tests = pd.read_csv(cluster_tests_path)
    id_column = str(config.get("id_column", ""))
    label_column = str(config.get("label_column", ""))
    time_column = str(config.get("time_column", ""))
    cluster_column = "leakage_group_id"
    class_count = int(config.get("expected_num_classes", 0))
    test_split_record = inputs.get("splits", {}).get("test")
    if not isinstance(test_split_record, dict):
        raise TypeError("input manifest lacks the locked-test split record")
    test_split_path = _resolve_record_path(
        str(test_split_record.get("path", "")), input_manifest_path
    )
    locked_test = pd.read_csv(test_split_path)
    required_split_columns = {
        id_column,
        label_column,
        time_column,
        cluster_column,
    }
    if locked_test.empty or not required_split_columns.issubset(locked_test):
        raise ValueError("locked-test split lacks ablation audit columns")
    expected_ids = locked_test[id_column].astype(str).tolist()
    expected_y = locked_test[label_column].to_numpy(dtype=np.int64)
    if (
        len(set(expected_ids)) != len(expected_ids)
        or (expected_y < 0).any()
        or (expected_y >= class_count).any()
    ):
        raise ValueError("locked-test IDs or labels are invalid for ablation audit")
    cluster_ids = locked_test[cluster_column].astype(str).to_numpy()
    calendar_values = locked_test[time_column].to_numpy(copy=True)
    probability_columns = [f"prob_{index}" for index in range(class_count)]
    required_prediction_columns = {
        "candidate",
        "ablation_label",
        "seed",
        "inference_mode",
        "checkpoint_sha256",
        "checkpoint_tree_count",
        id_column,
        "y_true",
        "y_pred",
        *probability_columns,
    }
    if predictions.empty or not required_prediction_columns.issubset(predictions):
        raise ValueError("matched-checkpoint per-sample predictions are incomplete")
    expected_modes = {
        "native_point_same_posterior_checkpoint",
        "virtual_ensemble_same_posterior_checkpoint",
    }
    probability_bundles: dict[
        tuple[str, str, int], tuple[list[str], np.ndarray, np.ndarray]
    ] = {}
    expected_binding_identities = {
        (candidate, seed) for candidate in configured_ablations for seed in seeds
    }
    observed_candidates = set(predictions["candidate"].astype(str))
    observed_seeds = set(predictions["seed"].astype(int))
    observed_modes = set(predictions["inference_mode"].astype(str))
    expected_rows = (
        len(configured_ablations) * len(seeds) * len(expected_modes) * len(expected_ids)
    )
    if (
        observed_candidates != set(configured_ablations)
        or observed_seeds != set(seeds)
        or observed_modes != expected_modes
        or len(predictions) != expected_rows
        or predictions.duplicated(
            subset=["candidate", "seed", "inference_mode", id_column]
        ).any()
    ):
        raise ValueError(
            "matched-checkpoint predictions contain missing, duplicate, or extra "
            "candidate/seed/mode/test-ID rows"
        )
    for candidate_name, label in configured_ablations.items():
        for seed in seeds:
            pair = predictions[
                (predictions["candidate"].astype(str) == candidate_name)
                & (predictions["seed"].astype(int) == seed)
            ]
            if set(pair["inference_mode"].astype(str)) != expected_modes:
                raise ValueError(
                    f"matched-checkpoint arms are incomplete for {candidate_name}, "
                    f"seed {seed}"
                )
            source_record = (
                selection.get("model_records", {})
                .get(candidate_name, {})
                .get(str(seed), {})
            )
            expected_checkpoint_sha = source_record.get("sha256")
            if (
                not isinstance(expected_checkpoint_sha, str)
                or set(pair["checkpoint_sha256"].astype(str))
                != {expected_checkpoint_sha}
                or pair["checkpoint_tree_count"].nunique() != 1
                or int(pair["checkpoint_tree_count"].iloc[0]) < 1
                or set(pair["ablation_label"].astype(str)) != {label}
            ):
                raise ValueError(
                    "matched-checkpoint prediction arms do not share the frozen "
                    f"checkpoint identity for {candidate_name}, seed {seed}"
                )
            reference_ids: list[str] | None = None
            reference_y: np.ndarray | None = None
            for mode in sorted(expected_modes):
                arm = pair[pair["inference_mode"].astype(str) == mode]
                ids = arm[id_column].astype(str).tolist()
                y_true = arm["y_true"].to_numpy(dtype=np.int64)
                probabilities = arm[probability_columns].to_numpy(dtype=np.float64)
                if (
                    ids != expected_ids
                    or not np.array_equal(y_true, expected_y)
                    or probabilities.shape != (len(ids), class_count)
                    or not np.isfinite(probabilities).all()
                    or (probabilities < 0.0).any()
                    or (probabilities > 1.0).any()
                    or (y_true < 0).any()
                    or (y_true >= class_count).any()
                    or not np.allclose(
                        probabilities.sum(axis=1), 1.0, atol=1e-6, rtol=0.0
                    )
                    or not np.array_equal(
                        arm["y_pred"].to_numpy(dtype=np.int64),
                        probabilities.argmax(axis=1),
                    )
                ):
                    raise ValueError(
                        f"invalid matched-checkpoint predictions for {candidate_name}, "
                        f"seed {seed}, mode {mode}"
                    )
                if reference_ids is None:
                    reference_ids, reference_y = ids, y_true
                elif ids != reference_ids or not np.array_equal(y_true, reference_y):
                    raise ValueError(
                        "matched-checkpoint arms differ in row order or labels"
                    )
                probability_bundles[(candidate_name, mode, seed)] = (
                    ids,
                    y_true,
                    probabilities,
                )

    execution = test.get("matched_checkpoint_inference_ablation_execution")
    if not isinstance(execution, dict):
        raise TypeError("matched-checkpoint ablation execution receipt is absent")
    bindings = execution.get("checkpoint_bindings")
    if (
        execution.get("analysis_role") != "prespecified_inference_only_ablation"
        or execution.get("same_loaded_checkpoint_object_used_within_each_seed_pair")
        is not True
        or execution.get("comparison_rows") != 2 * len(configured_ablations)
        or execution.get("cluster_accuracy_rows") != len(configured_ablations)
        or not isinstance(bindings, list)
        or {
            (str(item.get("candidate")), int(item.get("seed", -1)))
            for item in bindings
            if isinstance(item, dict)
        }
        != expected_binding_identities
        or len(bindings) != len(expected_binding_identities)
    ):
        raise ValueError("matched-checkpoint execution receipt is incomplete")
    for binding in bindings:
        candidate_name = str(binding["candidate"])
        seed = int(binding["seed"])
        source_record = selection["model_records"][candidate_name][str(seed)]
        prediction_pair = predictions[
            (predictions["candidate"].astype(str) == candidate_name)
            & (predictions["seed"].astype(int) == seed)
        ]
        archived_tree_count = int(prediction_pair["checkpoint_tree_count"].iloc[0])
        if (
            binding.get("checkpoint_sha256") != source_record.get("sha256")
            or type(binding.get("checkpoint_tree_count")) is not int
            or binding["checkpoint_tree_count"] < 1
            or binding["checkpoint_tree_count"] != archived_tree_count
            or binding.get("ablation_label") != configured_ablations[candidate_name]
            or binding.get("same_checkpoint_object_used_for_both_inference_modes")
            is not True
            or binding.get("reference_probability_semantics")
            != "native_point_probability_from_same_posterior_sampling_checkpoint"
            or binding.get("challenger_probability_semantics")
            != "posterior_mean_virtual_ensemble_probability"
        ):
            raise ValueError(
                f"matched-checkpoint execution binding is invalid for "
                f"{candidate_name}, seed {seed}"
            )

    required_comparison_columns = {
        "comparison",
        "candidate",
        "reference",
        "challenger",
        "same_checkpoint_within_seed",
        "training_intervention",
        "metric",
        "delta_challenger_minus_reference",
    }
    if comparisons.empty or not required_comparison_columns.issubset(comparisons):
        raise ValueError("matched-checkpoint comparison artifact is incomplete")
    if len(comparisons) != 2 * len(configured_ablations):
        raise ValueError("matched-checkpoint comparison row count is invalid")
    for candidate_name, label in configured_ablations.items():
        rows = comparisons[comparisons["candidate"].astype(str) == candidate_name]
        if (
            set(rows["comparison"].astype(str)) != {label}
            or set(rows["metric"].astype(str)) != {"accuracy", "macro_f1"}
            or set(rows["reference"].astype(str))
            != {"native_point_same_posterior_checkpoint"}
            or set(rows["challenger"].astype(str))
            != {"virtual_ensemble_same_posterior_checkpoint"}
            or not all(
                _strict_csv_boolean(value, "same_checkpoint_within_seed")
                for value in rows["same_checkpoint_within_seed"]
            )
            or set(rows["training_intervention"].astype(str))
            != {"none_within_ablation_pair"}
        ):
            raise ValueError(
                f"matched-checkpoint comparison semantics are invalid for {candidate_name}"
            )
        native_by_seed = {
            seed: (
                expected_y.copy(),
                probability_bundles[
                    (
                        candidate_name,
                        "native_point_same_posterior_checkpoint",
                        seed,
                    )
                ][2],
            )
            for seed in seeds
        }
        pgs_by_seed = {
            seed: (
                expected_y.copy(),
                probability_bundles[
                    (
                        candidate_name,
                        "virtual_ensemble_same_posterior_checkpoint",
                        seed,
                    )
                ][2],
            )
            for seed in seeds
        }
        native = np.mean(
            np.stack([native_by_seed[seed][1] for seed in seeds], axis=0),
            axis=0,
        )
        pgs = np.mean(
            np.stack([pgs_by_seed[seed][1] for seed in seeds], axis=0),
            axis=0,
        )
        native_prediction = native.argmax(axis=1)
        pgs_prediction = pgs.argmax(axis=1)
        test_config = config.get("test", {})
        expected_bootstrap_by_metric = {
            metric: hierarchical_paired_bootstrap(
                native_by_seed,
                pgs_by_seed,
                cluster_ids=cluster_ids,
                calendar_values=calendar_values,
                metric=metric,
                num_classes=class_count,
                iterations=int(test_config.get("bootstrap_iterations", 0)),
                confidence_level=float(test_config.get("confidence_level", 0.0)),
                random_seed=int(test_config.get("bootstrap_seed", -1)),
                stratification=str(test_config.get("bootstrap_stratification", "")),
            )
            for metric in ("accuracy", "macro_f1")
        }
        numeric_fields = {
            "delta_challenger_minus_reference",
            "ci_lower",
            "ci_upper",
            "confidence_level",
            "bootstrap_probability_delta_nonpositive",
            "bootstrap_probability_delta_nonnegative",
            "bootstrap_two_sided_tail_probability_descriptive",
        }
        integer_fields = {
            "common_seeds",
            "n_clusters",
            "iterations",
            "bootstrap_replicates",
            "bootstrap_seed",
        }
        string_fields = {
            "sampling_unit",
            "bootstrap_rng",
            "analysis_role",
            "estimand",
            "probability_aggregation",
            "replicate_seed_rule",
            "point_estimate_seed_rule",
            "bootstrap_stratification",
            "stratification_calendar_rule",
            "stratification_label_rule",
            "cluster_strata_sha256",
            "bootstrap_algorithm_id",
            "bootstrap_algorithm",
            "strata_cluster_counts_json",
        }
        for metric, expected_bootstrap in expected_bootstrap_by_metric.items():
            metric_rows = rows[rows["metric"].astype(str) == metric]
            if len(metric_rows) != 1:
                raise ValueError(
                    f"matched-checkpoint {metric} interval row is not unique"
                )
            row = metric_rows.iloc[0]
            if any(
                not math.isclose(
                    float(row[field]),
                    float(expected_bootstrap[field]),
                    abs_tol=1e-12,
                    rel_tol=0.0,
                )
                for field in numeric_fields
            ) or any(
                int(row[field]) != int(expected_bootstrap[field])
                for field in integer_fields
            ):
                raise ValueError(
                    "matched-checkpoint bootstrap interval/tail values do not "
                    "recompute from the hash-bound per-sample probabilities"
                )
            if any(
                str(row[field]) != str(expected_bootstrap[field])
                for field in string_fields
            ):
                raise ValueError(
                    "matched-checkpoint bootstrap design fields differ from the "
                    "recomputed frozen design"
                )
            if (
                _strict_csv_boolean(
                    row["training_seed_resampling"],
                    "training_seed_resampling",
                )
                != bool(expected_bootstrap["training_seed_resampling"])
                or ast.literal_eval(str(row["bootstrap_rng_stream_derivation"]))
                != expected_bootstrap["bootstrap_rng_stream_derivation"]
                or ast.literal_eval(str(row["strata_cluster_counts"]))
                != expected_bootstrap["strata_cluster_counts"]
            ):
                raise ValueError(
                    "matched-checkpoint bootstrap structured design receipt is invalid"
                )

        cluster_rows = archived_cluster_tests[
            archived_cluster_tests["comparison"].astype(str) == label
        ]
        if len(cluster_rows) != 1:
            raise ValueError(
                f"matched-checkpoint cluster accuracy row is absent for {label}"
            )
        expected_cluster_test = cluster_paired_accuracy_test(
            expected_y,
            native_prediction,
            pgs_prediction,
            cluster_ids,
            monte_carlo_iterations=int(
                test_config.get("cluster_permutation_iterations", 0)
            ),
            random_seed=int(test_config.get("cluster_permutation_seed", -1)),
        )
        cluster_row = cluster_rows.iloc[0]
        if (
            str(cluster_row.get("reference"))
            != "native_point_same_posterior_checkpoint"
            or str(cluster_row.get("challenger"))
            != "virtual_ensemble_same_posterior_checkpoint"
            or str(cluster_row.get("prediction_vector"))
            != (
                "equal_weight_mean_probability_over_all_seeds_same_"
                "posterior_checkpoints"
            )
            or _strict_csv_boolean(
                cluster_row.get("same_checkpoint_within_seed"),
                "same_checkpoint_within_seed",
            )
            is not True
        ):
            raise ValueError("matched-checkpoint cluster-test semantics are invalid")
        for field, expected_value in expected_cluster_test.items():
            observed_value = cluster_row.get(field)
            if isinstance(expected_value, float):
                matches = math.isclose(
                    float(observed_value),
                    expected_value,
                    abs_tol=1e-12,
                    rel_tol=0.0,
                )
            else:
                matches = str(observed_value) == str(expected_value)
            if not matches:
                raise ValueError(
                    "matched-checkpoint cluster accuracy test does not recompute"
                )

    if (
        archived_cluster_tests.empty
        or "holm_adjusted_cluster_p" not in archived_cluster_tests
        or not np.allclose(
            archived_cluster_tests["holm_adjusted_cluster_p"].to_numpy(
                dtype=np.float64
            ),
            holm_adjusted_pvalues(
                archived_cluster_tests["cluster_paired_two_sided_p"]
                .astype(float)
                .tolist()
            ),
            atol=1e-12,
            rtol=0.0,
        )
    ):
        raise ValueError("cluster-test Holm correction does not recompute")


def _check_experiment(run_dir: Path | None) -> Gate:
    name, category = "locked_phase_a_retrospective_experiment", "experiment"
    if run_dir is None:
        return _failed(
            name, category, None, "pass --experiment-run after the real locked run"
        )
    run_dir = run_dir.resolve()
    required = {
        "config": run_dir / "resolved_config.json",
        "environment": run_dir / "metadata" / "environment.json",
        "inputs": run_dir / "metadata" / "input_manifest.json",
        "selection": run_dir / "selection" / "selection_receipt.json",
        "test": run_dir / "test" / "TEST_EVALUATION_COMPLETE.json",
    }
    missing = [key for key, path in required.items() if not path.is_file()]
    if missing:
        return _failed(name, category, run_dir, f"missing receipts: {missing}")
    try:
        config = _read_json(required["config"])
        inputs = _read_json(required["inputs"])
        selection = _read_json(required["selection"])
        test = _read_json(required["test"])
        protocol_digest = _resolved_protocol_digest(config)
        if selection.get("protocol_digest") != protocol_digest:
            raise ValueError(
                "selection receipt protocol digest differs from resolved config"
            )
        if test.get("protocol_digest") != protocol_digest:
            raise ValueError(
                "locked-test receipt protocol digest differs from resolved config"
            )
        seeds = [int(value) for value in config.get("seeds", [])]
        if len(seeds) < 5 or len(set(seeds)) != len(seeds):
            raise ValueError("at least five distinct preregistered seeds are required")
        if selection.get("test_csv_parsed") is not False:
            raise ValueError("selection receipt does not attest an unopened test set")
        if (
            test.get("phase") != "locked_test_complete"
            or test.get("test_ranking_performed") is not False
        ):
            raise ValueError("test receipt is incomplete or test ranking was performed")
        selection_without_digest = dict(selection)
        stored_selection_digest = selection_without_digest.pop("receipt_digest", None)
        if stored_selection_digest != _object_sha256(selection_without_digest):
            raise ValueError("selection receipt digest mismatch")
        test_without_digest = dict(test)
        stored_test_digest = test_without_digest.pop("receipt_digest", None)
        if stored_test_digest != _object_sha256(test_without_digest):
            raise ValueError("locked-test receipt digest mismatch")
        input_digest = _object_sha256(inputs)
        if selection.get("input_manifest_digest") != input_digest:
            raise ValueError("selection receipt is not bound to the input manifest")
        if test.get("input_manifest_digest") != input_digest:
            raise ValueError("test receipt is not bound to the input manifest")
        if test.get("selection_receipt_digest") != stored_selection_digest:
            raise ValueError("test receipt is not bound to the selection receipt")

        class_map = inputs.get("class_map")
        class_map_digest = inputs.get("class_map_sha256")
        if (
            not isinstance(class_map, dict)
            or class_map.get("sha256") != class_map_digest
            or _class_map_sha256(class_map) != class_map_digest
        ):
            raise ValueError("input manifest class-map semantic digest mismatch")
        if selection.get("class_map_sha256") != class_map_digest:
            raise ValueError("selection receipt class-map digest mismatch")
        if test.get("class_map_sha256") != class_map_digest:
            raise ValueError("test receipt class-map digest mismatch")

        input_records = dict(inputs.get("splits", {})) | dict(
            inputs.get("embeddings", {})
        )
        if inputs.get("split_manifest"):
            input_records["split_manifest"] = inputs["split_manifest"]
        ok, detail = _verify_records(input_records, required["inputs"])
        if not ok:
            raise ValueError(f"input manifest: {detail}")
        ok, detail = _verify_records(selection.get("artifacts"), required["selection"])
        if not ok:
            raise ValueError(f"selection artifacts: {detail}")
        ok, detail = _verify_records(test.get("artifacts"), required["test"])
        if not ok:
            raise ValueError(f"test artifacts: {detail}")
        required_final_artifacts = {
            "metrics_by_seed",
            "aggregate_metrics",
            "paired_comparisons",
            "training_seed_sensitivity",
            "bootstrap_cluster_strata",
            "cluster_paired_accuracy_tests",
            "seed_ensemble_predictions",
            "seed_ensemble_metrics",
            "seed_ensemble_risk_coverage_at_validation_thresholds",
            "unit_artifact_index",
            "environment_manifest",
            "locked_test_split_audit",
            "matched_checkpoint_inference_predictions",
            "matched_checkpoint_inference_ablations",
        }
        if missing_final := sorted(
            required_final_artifacts - set(test.get("artifacts", {}))
        ):
            raise ValueError(f"locked-test receipt misses artifacts: {missing_final}")

        environment = _read_json(required["environment"])
        packages = environment.get("packages", {})
        if not isinstance(packages, dict) or any(
            not packages.get(name)
            for name in ("catboost", "numpy", "pandas", "scikit-learn", "scipy")
        ):
            raise ValueError("environment manifest lacks required package versions")
        if not environment.get("python", {}).get("version"):
            raise ValueError("environment manifest lacks Python version")

        for name, embedding in inputs.get("embeddings", {}).items():
            if not isinstance(embedding, dict):
                raise TypeError(f"embedding record {name!r} is invalid")
            extraction = embedding.get("extraction_receipt")
            if not extraction:
                raise ValueError(f"embedding {name!r} lacks an extraction receipt")
            ok, detail = _verify_artifact(extraction, required["inputs"])
            if not ok:
                raise ValueError(f"embedding {name!r} extraction receipt: {detail}")
            provenance = embedding.get("provenance", {})
            encoder = provenance.get("encoder", {})
            if not (
                provenance.get("source_snapshot_sha256")
                and provenance.get("source_row_order_sha256")
                and encoder.get("repository")
                and encoder.get("revision")
                and provenance.get("extraction_code_commit")
            ):
                raise ValueError(f"embedding {name!r} provenance is incomplete")
            modality = str(name).partition(":")[0]
            if modality not in {"image", "text"}:
                raise ValueError(f"embedding {name!r} has no valid modality prefix")
            try:
                validate_preprocessing_contract(
                    provenance.get("preprocessing"),
                    modality=modality,
                    pooling=provenance.get("pooling"),
                    prefix=provenance.get("prefix"),
                    max_length=provenance.get("max_length"),
                    output_dtype=provenance.get("dtype"),
                )
            except PreprocessingContractError as exc:
                raise ValueError(
                    f"embedding {name!r} preprocessing contract: {exc}"
                ) from exc
            declared_preprocessing_hash = provenance.get("preprocessing_sha256")
            if (
                not isinstance(declared_preprocessing_hash, str)
                or preprocessing_sha256(provenance["preprocessing"])
                != declared_preprocessing_hash
            ):
                raise ValueError(
                    f"embedding {name!r} preprocessing semantic digest mismatch"
                )

        candidates = config.get("candidates", [])
        candidate_configs = {
            str(item.get("name")): item for item in candidates if item.get("name")
        }
        model_kinds = {item.get("model") for item in candidates}
        required_models = {
            "catboost",
            "logistic_regression",
            "dummy_prior",
            "dummy_stratified",
            "tfidf_logistic",
            "late_fusion_catboost",
        }
        if missing_models := sorted(required_models - model_kinds):
            raise ValueError(
                f"baseline families missing from frozen config: {missing_models}"
            )
        if not any(item.get("posterior_sampling") for item in candidates):
            raise ValueError("no posterior-sampling candidate in frozen config")
        _validate_matched_checkpoint_inference_ablation(
            config,
            inputs,
            selection,
            test,
            input_manifest_path=required["inputs"],
            test_receipt_path=required["test"],
        )
        reconstruction_variants = {
            bool(item.get("posterior_sampling", False))
            for item in candidates
            if item.get("model") == "catboost"
            and item.get("image_encoder") == "dinov2_large"
            and item.get("text_encoder") == "mE5_large"
        }
        if reconstruction_variants != {False, True}:
            raise ValueError("DINOv2+mE5 baseline needs matched point and PGS variants")
        if not any(
            item.get("image_encoder") and not item.get("text_encoder")
            for item in candidates
        ):
            raise ValueError("no image-only ablation in frozen config")
        if not any(
            item.get("text_encoder") and not item.get("image_encoder")
            for item in candidates
        ):
            raise ValueError("no text-only ablation in frozen config")
        inference_plan = test.get("prespecified_phase_a_inference_plan", {})
        if selection.get("prespecified_phase_a_inference_plan") != inference_plan:
            raise ValueError(
                "test inference plan differs from the frozen selection receipt"
            )
        seed_rule = str(inference_plan.get("seed_ensemble_prediction_rule", ""))
        if (
            inference_plan.get("cluster_column") != "leakage_group_id"
            or "equal-weight arithmetic mean" not in seed_rule
            or "preregistered seeds" not in seed_rule
            or "lowest class ID" not in seed_rule
            or "whole-cluster" not in str(inference_plan.get("paired_bootstrap", ""))
            or "cluster-level"
            not in str(inference_plan.get("paired_accuracy_test", ""))
        ):
            raise ValueError(
                "locked Phase-A cluster/seed-ensemble inference plan is incomplete"
            )
        test_config = config.get("test", {})
        bootstrap_iterations = inference_plan.get("paired_bootstrap_iterations")
        bootstrap_seed = inference_plan.get("paired_bootstrap_seed")
        bootstrap_stratification = inference_plan.get("paired_bootstrap_stratification")
        sensitivity_iterations = inference_plan.get(
            "training_seed_sensitivity_iterations"
        )
        sensitivity_seed = inference_plan.get("training_seed_sensitivity_seed")
        expected_primary_rng_derivation = bootstrap_rng_stream_derivation(
            int(bootstrap_seed),
            include_training_seed_stream=False,
        )
        expected_sensitivity_rng_derivation = bootstrap_rng_stream_derivation(
            int(sensitivity_seed),
            include_training_seed_stream=True,
        )
        if (
            bootstrap_iterations != 10000
            or test_config.get("bootstrap_iterations") != 10000
        ):
            raise ValueError(
                "release protocol requires exactly 10,000 preregistered paired "
                "bootstrap replicates"
            )
        if (
            isinstance(bootstrap_seed, bool)
            or not isinstance(bootstrap_seed, int)
            or test_config.get("bootstrap_seed") != bootstrap_seed
        ):
            raise ValueError(
                "paired bootstrap seed is absent or differs from the frozen config"
            )
        if (
            sensitivity_iterations != 10000
            or test_config.get("training_seed_sensitivity_iterations") != 10000
            or isinstance(sensitivity_seed, bool)
            or not isinstance(sensitivity_seed, int)
            or test_config.get("training_seed_sensitivity_seed") != sensitivity_seed
        ):
            raise ValueError(
                "training-seed sensitivity must use 10,000 preregistered draws "
                "and the frozen RNG seed"
            )
        if (
            bootstrap_stratification != "utc_month_x_cluster_majority_label_v1"
            or test_config.get("bootstrap_stratification") != bootstrap_stratification
            or inference_plan.get("paired_bootstrap_algorithm_id")
            != BOOTSTRAP_ALGORITHM_ID
            or inference_plan.get("paired_bootstrap_estimand")
            != "deployed_fixed_preregistered_seed_ensemble_metric_delta"
            or inference_plan.get("paired_bootstrap_probability_aggregation")
            != "arithmetic_mean_before_argmax_and_metric"
            or inference_plan.get("paired_bootstrap_point_estimate_seed_rule")
            != "all_preregistered_seeds_exactly_once_equal_weight"
            or inference_plan.get("paired_bootstrap_replicate_seed_rule")
            != "all_preregistered_seeds_exactly_once_equal_weight_fixed_across_draws"
            or inference_plan.get("paired_bootstrap_training_seed_resampling")
            is not False
            or inference_plan.get("paired_bootstrap_rng_stream_derivation")
            != expected_primary_rng_derivation
            or inference_plan.get("paired_bootstrap_configuration_timing")
            != "frozen_in_selection_receipt_before_locked_test_access"
        ):
            raise ValueError(
                "paired bootstrap stratification/algorithm was not preregistered"
            )
        bootstrap_execution = test.get(
            "prespecified_phase_a_inference_execution", {}
        ).get("paired_bootstrap")
        if not isinstance(bootstrap_execution, dict):
            raise TypeError("locked-test receipt lacks paired bootstrap execution")
        if (
            bootstrap_execution.get("bootstrap_replicates") != bootstrap_iterations
            or bootstrap_execution.get("bootstrap_seed") != bootstrap_seed
            or bootstrap_execution.get("bootstrap_stratification")
            != bootstrap_stratification
            or bootstrap_execution.get("bootstrap_algorithm_id")
            != inference_plan.get("paired_bootstrap_algorithm_id")
            or bootstrap_execution.get("bootstrap_algorithm")
            != inference_plan.get("paired_bootstrap_algorithm")
            or bootstrap_execution.get("estimand")
            != inference_plan.get("paired_bootstrap_estimand")
            or bootstrap_execution.get("probability_aggregation")
            != inference_plan.get("paired_bootstrap_probability_aggregation")
            or bootstrap_execution.get("point_estimate_seed_rule")
            != inference_plan.get("paired_bootstrap_point_estimate_seed_rule")
            or bootstrap_execution.get("replicate_seed_rule")
            != inference_plan.get("paired_bootstrap_replicate_seed_rule")
            or bootstrap_execution.get("training_seed_resampling") is not False
            or bootstrap_execution.get("analysis_role")
            != "primary_phase_a_prespecified_interval"
            or bootstrap_execution.get("bootstrap_rng_stream_derivation")
            != inference_plan.get("paired_bootstrap_rng_stream_derivation")
        ):
            raise ValueError(
                "executed paired bootstrap differs from the frozen inference plan"
            )
        sensitivity_execution = test.get(
            "prespecified_phase_a_inference_execution", {}
        ).get("training_seed_sensitivity")
        if not isinstance(sensitivity_execution, dict):
            raise TypeError(
                "locked-test receipt lacks training-seed sensitivity execution"
            )
        if (
            inference_plan.get("training_seed_sensitivity_algorithm_id")
            != TRAINING_SEED_SENSITIVITY_ALGORITHM_ID
            or inference_plan.get("training_seed_sensitivity_estimand")
            != (
                "training_seed_superpopulation_equal_size_probability_ensemble_"
                "metric_delta"
            )
            or sensitivity_execution.get("bootstrap_replicates")
            != sensitivity_iterations
            or sensitivity_execution.get("bootstrap_seed") != sensitivity_seed
            or sensitivity_execution.get("bootstrap_stratification")
            != bootstrap_stratification
            or sensitivity_execution.get("bootstrap_algorithm_id")
            != inference_plan.get("training_seed_sensitivity_algorithm_id")
            or sensitivity_execution.get("bootstrap_algorithm")
            != inference_plan.get("training_seed_sensitivity_algorithm")
            or sensitivity_execution.get("estimand")
            != inference_plan.get("training_seed_sensitivity_estimand")
            or sensitivity_execution.get("probability_aggregation")
            != inference_plan.get("training_seed_sensitivity_probability_aggregation")
            or sensitivity_execution.get("point_estimate_seed_rule")
            != inference_plan.get("training_seed_sensitivity_point_estimate_seed_rule")
            or sensitivity_execution.get("replicate_seed_rule")
            != inference_plan.get("training_seed_sensitivity_replicate_seed_rule")
            or sensitivity_execution.get("training_seed_resampling") is not True
            or sensitivity_execution.get("analysis_role")
            != "secondary_training_seed_sensitivity"
            or sensitivity_execution.get("bootstrap_rng_stream_derivation")
            != expected_sensitivity_rng_derivation
            or inference_plan.get("training_seed_sensitivity_rng_stream_derivation")
            != expected_sensitivity_rng_derivation
            or sensitivity_seed != bootstrap_seed
        ):
            raise ValueError(
                "training-seed sensitivity differs from the frozen secondary plan"
            )
        for field in (
            "bootstrap_stratification",
            "stratification_calendar_rule",
            "stratification_label_rule",
            "strata_cluster_counts",
            "cluster_strata_sha256",
        ):
            if sensitivity_execution.get(field) != bootstrap_execution.get(field):
                raise ValueError(
                    "primary bootstrap and seed sensitivity do not share one "
                    "frozen cluster-stratification design"
                )
        strata_counts = bootstrap_execution.get("strata_cluster_counts")
        if (
            not isinstance(strata_counts, dict)
            or not strata_counts
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count < 1
                for count in strata_counts.values()
            )
            or sum(strata_counts.values()) < 2
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                str(bootstrap_execution.get("cluster_strata_sha256", "")),
            )
        ):
            raise ValueError("paired bootstrap realized-strata receipt is invalid")
        strata_record = test.get("artifacts", {}).get("bootstrap_cluster_strata")
        strata_path = _resolve_record_path(str(strata_record["path"]), required["test"])
        with strata_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required_columns = {
                "leakage_group_id",
                "utc_anchor_month",
                "majority_label_id",
                "row_count",
                "class_composition_json",
                "stratum",
            }
            if not reader.fieldnames or not required_columns.issubset(
                reader.fieldnames
            ):
                raise ValueError("bootstrap strata artifact lacks required columns")
            strata_rows = [
                {
                    "leakage_group_id": row["leakage_group_id"],
                    "utc_anchor_month": row["utc_anchor_month"],
                    "majority_label_id": int(row["majority_label_id"]),
                    "row_count": int(row["row_count"]),
                    "class_composition_json": row["class_composition_json"],
                    "stratum": row["stratum"],
                }
                for row in reader
            ]
        if (
            not strata_rows
            or len({row["leakage_group_id"] for row in strata_rows}) != len(strata_rows)
            or _object_sha256(
                sorted(strata_rows, key=lambda row: row["leakage_group_id"])
            )
            != bootstrap_execution["cluster_strata_sha256"]
        ):
            raise ValueError("bootstrap strata artifact semantic digest is invalid")
        archived_counts: dict[str, int] = {}
        for row in strata_rows:
            archived_counts[row["stratum"]] = archived_counts.get(row["stratum"], 0) + 1
        if archived_counts != strata_counts:
            raise ValueError("bootstrap strata artifact counts differ from the receipt")

        selection_artifacts = selection.get("artifacts", {})
        required_selection_artifacts = {
            "validation_metrics_by_seed",
            "validation_leaderboard",
            "validation_deployment_eligible_leaderboard",
            "validation_seed_ensemble_predictions",
            "validation_seed_ensemble_metrics",
            "validation_review_operating_points",
            "unit_artifact_index",
        }
        if missing_selection := sorted(
            required_selection_artifacts - set(selection_artifacts)
        ):
            raise ValueError(
                f"selection receipt misses ensemble artifacts: {missing_selection}"
            )
        selection_rule = str(selection.get("selection_rule", ""))
        eligibility_rule = str(selection.get("selection_eligibility_rule", ""))
        eligible_candidates = config.get("deployment_eligible_candidates")
        configured_candidate_names = list(candidate_configs)
        if (
            not isinstance(eligible_candidates, list)
            or not eligible_candidates
            or len(set(eligible_candidates)) != len(eligible_candidates)
            or any(name not in candidate_configs for name in eligible_candidates)
            or selection.get("deployment_eligible_candidates") != eligible_candidates
            or selection.get("secondary_baseline_candidates")
            != [
                name
                for name in configured_candidate_names
                if name not in eligible_candidates
            ]
            or selection.get("selected_candidate") not in eligible_candidates
            or "protocol.deployment_eligible_candidates" not in eligibility_rule
            or "secondary baselines or ablations" not in eligibility_rule
        ):
            raise ValueError(
                "primary selection does not bind its preregistered deployment-"
                "eligible candidate subset"
            )
        for candidate_name in eligible_candidates:
            candidate_config = candidate_configs[candidate_name]
            if (
                candidate_config.get("model") != "catboost"
                or not candidate_config.get("image_encoder")
                or not candidate_config.get("text_encoder")
            ):
                raise ValueError(
                    "deployment-eligible candidate is unsupported by the five-head "
                    f"image+text runtime: {candidate_name}"
                )
        if (
            selection.get("primary_system")
            != "equal_weight_preregistered_seed_ensemble"
            or "ensemble_macro_f1" not in selection_rule
            or "equal-weight arithmetic mean" not in selection_rule
            or "ensemble_nll" not in selection_rule
            or "checkpoint size" not in selection_rule
        ):
            raise ValueError(
                "candidate selection is not bound to ensemble validation macro-F1"
            )
        _validate_validation_selection_semantics(
            config,
            inputs,
            selection,
            input_manifest_path=required["inputs"],
            selection_receipt_path=required["selection"],
        )
        calibration = selection.get("calibration_protocol")
        expected_calibration = {
            "family": config.get("calibration_family"),
            "fitting_objective": config.get("calibration_fitting_objective"),
            "probability_scope": config.get("calibration_probability_scope"),
            "claim": config.get("calibration_claim"),
            "ece": {
                "family": config.get("ece_family"),
                "binning": config.get("ece_binning"),
                "bins": config.get("ece_bins"),
                "bin_interval_semantics": config.get("ece_bin_interval_semantics"),
            },
        }
        if calibration != expected_calibration:
            raise ValueError(
                "selection calibration/ECE protocol differs from resolved config"
            )
        review_policy = selection.get("review_policy")
        class_labels = [
            str(item["label_name"]) for item in class_map.get("classes", [])
        ]
        expected_unconditional = (
            ["Instansi lain"] if "Instansi lain" in class_labels else []
        )
        expected_routable = [
            label for label in class_labels if label != "Instansi lain"
        ]
        if (
            not isinstance(review_policy, dict)
            or review_policy.get("candidate") != selection.get("selected_candidate")
            or review_policy.get("threshold_source")
            != config.get("review_threshold_source")
            or review_policy.get("selection_split") != "validation"
            or review_policy.get("operating_criterion")
            != config.get("review_operating_criterion")
            or review_policy.get("target_coverage")
            != config.get("review_target_coverage")
            or review_policy.get("target_population")
            != config.get("review_target_population")
            or review_policy.get("tie_policy") != config.get("review_tie_policy")
            or review_policy.get("policy_scope")
            != "model_review_gates_plus_unconditional_labels_excluding_registry"
            or review_policy.get("unconditionally_reviewed_labels")
            != expected_unconditional
            or review_policy.get("routable_labels") != expected_routable
        ):
            raise ValueError(
                "selection review policy is not validation-frozen/catch-all-safe"
            )
        if (
            test.get("calibration_protocol") != calibration
            or test.get("review_policy_applied_unchanged") != review_policy
        ):
            raise ValueError(
                "locked test did not apply calibration/review policy unchanged"
            )
        import pandas as pd

        leaderboard_path = _resolve_record_path(
            selection_artifacts["validation_seed_ensemble_metrics"]["path"],
            required["selection"],
        )
        leaderboard = pd.read_csv(leaderboard_path)
        eligible_leaderboard_path = _resolve_record_path(
            selection_artifacts["validation_deployment_eligible_leaderboard"]["path"],
            required["selection"],
        )
        eligible_leaderboard = pd.read_csv(eligible_leaderboard_path)
        expected_eligible_order = (
            leaderboard[leaderboard["candidate"].astype(str).isin(eligible_candidates)][
                "candidate"
            ]
            .astype(str)
            .tolist()
        )
        if (
            leaderboard.empty
            or "ensemble_macro_f1" not in leaderboard
            or "ensemble_nll" not in leaderboard
            or "total_checkpoint_size_bytes" not in leaderboard
            or eligible_leaderboard.empty
            or eligible_leaderboard["candidate"].astype(str).tolist()
            != expected_eligible_order
            or set(expected_eligible_order) != set(eligible_candidates)
            or str(eligible_leaderboard.iloc[0].get("candidate", ""))
            != str(selection.get("selected_candidate", ""))
        ):
            raise ValueError(
                "selected candidate is not the first frozen deployment-eligible "
                "ensemble-macro-F1 row"
            )
        review_points_path = _resolve_record_path(
            selection_artifacts["validation_review_operating_points"]["path"],
            required["selection"],
        )
        review_points = pd.read_csv(review_points_path)
        selected_points = review_points[
            review_points["candidate"] == selection["selected_candidate"]
        ]
        confidence_points = selected_points[
            selected_points["uncertainty"] == "one_minus_confidence"
        ]
        joint_points = selected_points[
            selected_points["uncertainty"] == "joint_deployed_review_policy"
        ]
        selected_config = candidate_configs[str(selection["selected_candidate"])]
        epistemic_points = selected_points[
            selected_points["uncertainty"] == "epistemic_mutual_information"
        ]
        if (
            len(confidence_points) != 1
            or str(confidence_points.iloc[0]["threshold_source"])
            != "validation_seed_ensemble"
            or len(joint_points) != 1
            or str(joint_points.iloc[0]["policy_component"]) != "joint"
            or str(joint_points.iloc[0]["target_population"])
            != "predicted_routable_labels_only"
            or str(joint_points.iloc[0]["policy_scope"])
            != "model_review_gates_plus_unconditional_labels_excluding_registry"
            or float(joint_points.iloc[0]["realized_coverage"])
            < float(review_policy["target_coverage"])
            or not math.isclose(
                float(confidence_points.iloc[0]["uncertainty_threshold"]),
                float(review_policy["maximum_one_minus_confidence"]),
            )
            or not math.isclose(
                1.0 - float(confidence_points.iloc[0]["uncertainty_threshold"]),
                float(review_policy["minimum_confidence"]),
            )
            or not math.isclose(
                float(joint_points.iloc[0]["marginal_quantile_coverage"]),
                float(review_policy["marginal_quantile_coverage"]),
            )
            or not math.isclose(
                float(joint_points.iloc[0]["realized_coverage"]),
                float(review_policy["validation_joint_realized_coverage"]),
            )
            or not math.isclose(
                float(joint_points.iloc[0]["selective_risk"]),
                float(review_policy["validation_joint_selective_risk"]),
            )
            or not math.isclose(
                float(joint_points.iloc[0]["overall_realized_coverage"]),
                float(review_policy["validation_joint_overall_realized_coverage"]),
            )
            or int(joint_points.iloc[0]["target_population_count"])
            != int(review_policy["validation_target_population_count"])
            or int(joint_points.iloc[0]["unconditionally_reviewed_count"])
            != int(review_policy["validation_unconditionally_reviewed_count"])
            or float(joint_points.iloc[0]["overall_realized_coverage"])
            > float(joint_points.iloc[0]["realized_coverage"])
        ):
            raise ValueError(
                "selected joint review policy is not fitted on validation ensemble"
            )
        selected_uses_pgs = bool(selected_config.get("posterior_sampling", False))
        if selected_uses_pgs:
            if (
                len(epistemic_points) != 1
                or not math.isclose(
                    float(epistemic_points.iloc[0]["uncertainty_threshold"]),
                    float(review_policy["maximum_epistemic_mutual_information"]),
                )
                or review_policy.get("epistemic_uncertainty_semantics")
                != "joint_training_seed_pgs_component_mutual_information_nats"
                or review_policy.get("epistemic_component_axis")
                != "training_seed_x_pgs_virtual_member"
                or review_policy.get("epistemic_training_seed_count") != len(seeds)
                or review_policy.get("epistemic_virtual_ensembles_per_seed")
                != config.get("virtual_ensembles")
                or review_policy.get("epistemic_component_count")
                != len(seeds) * int(config["virtual_ensembles"])
            ):
                raise ValueError(
                    "selected epistemic threshold differs from its validation row"
                )
        elif not epistemic_points.empty or any(
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
            raise ValueError("point selection declared epistemic review metadata")
        test_risk_path = _resolve_record_path(
            test["artifacts"]["seed_ensemble_risk_coverage_at_validation_thresholds"][
                "path"
            ],
            required["test"],
        )
        test_risk = pd.read_csv(test_risk_path)
        test_joint = test_risk[
            test_risk["uncertainty"] == "joint_deployed_review_policy"
        ]
        planned_review_candidates = list(selection.get("planned_test_candidates", []))
        if (
            test_risk.empty
            or set(test_risk["threshold_source"].astype(str))
            != {"validation_seed_ensemble"}
            or len(test_joint) != len(planned_review_candidates)
            or set(test_joint["policy_component"].astype(str)) != {"joint"}
            or set(test_risk["candidate"].astype(str)) != set(planned_review_candidates)
        ):
            raise ValueError("test risk/coverage refitted thresholds on evaluated data")
        frozen_fields = (
            "threshold_source",
            "operating_criterion",
            "target_population",
            "tie_policy",
            "policy_component",
            "policy_scope",
        )
        frozen_numeric_fields = (
            "target_coverage",
            "marginal_quantile_coverage",
        )
        for candidate_name in planned_review_candidates:
            candidate_config = candidate_configs[candidate_name]
            expected_gates = {"one_minus_confidence"}
            if candidate_config.get("posterior_sampling", False):
                expected_gates.add("epistemic_mutual_information")
            validation_candidate = review_points[
                review_points["candidate"] == candidate_name
            ]
            test_candidate = test_risk[test_risk["candidate"] == candidate_name]
            validation_gates = validation_candidate[
                validation_candidate["policy_component"] == "gate"
            ]
            test_gates = test_candidate[test_candidate["policy_component"] == "gate"]
            validation_joint_rows = validation_candidate[
                validation_candidate["policy_component"] == "joint"
            ]
            test_joint_rows = test_candidate[
                test_candidate["policy_component"] == "joint"
            ]
            if (
                set(validation_gates["uncertainty"].astype(str)) != expected_gates
                or set(test_gates["uncertainty"].astype(str)) != expected_gates
                or len(validation_candidate) != len(expected_gates) + 1
                or len(test_candidate) != len(expected_gates) + 1
                or len(validation_joint_rows) != 1
                or len(test_joint_rows) != 1
            ):
                raise ValueError(
                    f"{candidate_name} review gates differ from the frozen policy"
                )
            for measure in expected_gates:
                validation_row = validation_gates[
                    validation_gates["uncertainty"] == measure
                ].iloc[0]
                test_row = test_gates[test_gates["uncertainty"] == measure].iloc[0]
                if any(
                    str(test_row[field]) != str(validation_row[field])
                    for field in frozen_fields
                ) or any(
                    not math.isclose(
                        float(test_row[field]), float(validation_row[field])
                    )
                    for field in (
                        *frozen_numeric_fields,
                        "uncertainty_threshold",
                    )
                ):
                    raise ValueError(
                        f"{candidate_name} {measure} threshold was not applied unchanged"
                    )
            validation_joint = validation_joint_rows.iloc[0]
            test_candidate_joint = test_joint_rows.iloc[0]
            if any(
                str(test_candidate_joint[field]) != str(validation_joint[field])
                for field in frozen_fields
            ) or any(
                not math.isclose(
                    float(test_candidate_joint[field]),
                    float(validation_joint[field]),
                )
                for field in frozen_numeric_fields
            ):
                raise ValueError(
                    f"{candidate_name} joint policy metadata changed on locked test"
                )
            for phase_name, candidate_rows, joint_row in (
                ("validation", validation_candidate, validation_joint),
                ("locked test", test_candidate, test_candidate_joint),
            ):
                target_counts = set(
                    candidate_rows["target_population_count"].astype(int)
                )
                unconditional_counts = set(
                    candidate_rows["unconditionally_reviewed_count"].astype(int)
                )
                if len(target_counts) != 1 or len(unconditional_counts) != 1:
                    raise ValueError(
                        f"{candidate_name} {phase_name} review-population counts "
                        "differ across gates"
                    )
                target_count = next(iter(target_counts))
                unconditional_count = next(iter(unconditional_counts))
                overall_coverage = float(joint_row["overall_realized_coverage"])
                conditional_coverage = float(joint_row["realized_coverage"])
                if (
                    target_count < 0
                    or unconditional_count < 0
                    or target_count + unconditional_count < 1
                    or not 0.0 <= overall_coverage <= 1.0
                    or (
                        target_count > 0
                        and (
                            not 0.0 <= conditional_coverage <= 1.0
                            or overall_coverage > conditional_coverage
                        )
                    )
                    or (
                        target_count == 0
                        and (
                            not math.isnan(conditional_coverage)
                            or overall_coverage != 0.0
                        )
                    )
                ):
                    raise ValueError(
                        f"{candidate_name} {phase_name} catch-all/routable "
                        "coverage accounting is invalid"
                    )
        selection_units = {
            (candidate_name, seed)
            for candidate_name in candidate_configs
            for seed in seeds
        }
        _verify_unit_index(
            selection_artifacts["unit_artifact_index"],
            parent_receipt=required["selection"],
            phase="selection",
            expected_units=selection_units,
            protocol_digest=protocol_digest,
            class_map_digest=str(class_map_digest),
            candidate_configs=candidate_configs,
        )

        planned = list(selection.get("planned_test_candidates", []))
        expected_units = {(candidate, seed) for candidate in planned for seed in seeds}
        _verify_unit_index(
            test["artifacts"]["unit_artifact_index"],
            parent_receipt=required["test"],
            phase="test",
            expected_units=expected_units,
            protocol_digest=protocol_digest,
            class_map_digest=str(class_map_digest),
            candidate_configs=candidate_configs,
        )
        observed_units: set[tuple[str, int]] = set()
        required_unit_artifacts = {
            "checkpoint",
            "predictions",
            "per_class_metrics",
            "risk_coverage",
            "reliability_bins",
            "confusion_matrix_counts",
            "confusion_matrix_row_normalized",
        }
        for candidate, seed in sorted(expected_units):
            receipt_path = (
                run_dir / "test" / candidate / f"seed_{seed}" / "unit_receipt.json"
            )
            if not receipt_path.is_file():
                raise ValueError(f"missing test unit receipt: {candidate}/seed_{seed}")
            receipt = _read_json(receipt_path)
            if (
                receipt.get("phase") != "test"
                or receipt.get("candidate") != candidate
                or int(receipt.get("seed", -1)) != seed
                or receipt.get("protocol_digest") != protocol_digest
                or receipt.get("class_map_sha256") != class_map_digest
            ):
                raise ValueError(
                    f"test unit identity mismatch: {candidate}/seed_{seed}"
                )
            artifacts = receipt.get("artifacts", {})
            if missing_artifacts := sorted(required_unit_artifacts - set(artifacts)):
                raise ValueError(
                    f"{candidate}/seed_{seed} missing artifacts: {missing_artifacts}"
                )
            ok, detail = _verify_records(artifacts, receipt_path)
            if not ok:
                raise ValueError(f"{candidate}/seed_{seed}: {detail}")
            observed_units.add((candidate, seed))
        if observed_units != expected_units:
            raise ValueError("test unit set differs from the frozen test plan")
        return Gate(
            name,
            category,
            True,
            str(run_dir),
            f"verified {len(expected_units)} locked test units across {len(seeds)} seeds",
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, run_dir, str(exc))


def _selected_candidate_config(
    config: dict[str, Any], selection: dict[str, Any]
) -> dict[str, Any]:
    selected = selection.get("selected_candidate")
    matches = [
        item
        for item in config.get("candidates", [])
        if isinstance(item, dict) and item.get("name") == selected
    ]
    if len(matches) != 1:
        raise ValueError("selected candidate is absent/ambiguous in resolved config")
    return matches[0]


def _selected_embedding_record(
    inputs: dict[str, Any], candidate: dict[str, Any], modality: str
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    encoder_name = candidate.get(f"{modality}_encoder")
    if not isinstance(encoder_name, str) or not encoder_name:
        raise ValueError(f"selected candidate has no {modality} encoder")
    key = f"{modality}:{encoder_name}"
    record = inputs.get("embeddings", {}).get(key)
    if not isinstance(record, dict) or not isinstance(record.get("provenance"), dict):
        raise TypeError(f"experiment input manifest lacks selected encoder {key}")
    return encoder_name, record, record["provenance"]


def _validate_encoder_export_parity_lineage(
    *,
    manifest: dict[str, Any],
    inputs: dict[str, Any],
    config: dict[str, Any],
    selection: dict[str, Any],
    encoder_parity_paths: list[Path],
) -> None:
    """Bind parity reports to selected embedding receipts and exported ONNX bytes."""
    candidate = _selected_candidate_config(config, selection)
    reports_by_component: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in encoder_parity_paths:
        report = _read_json(path)
        component = str(report.get("component", ""))
        if component in reports_by_component:
            raise ValueError(f"duplicate encoder parity component {component!r}")
        reports_by_component[component] = (path, report)
    if set(reports_by_component) != {"image_encoder", "text_encoder"}:
        raise ValueError(
            "exactly one image and one text encoder parity report required"
        )

    artifact_by_path = {
        str(item["path"]): item
        for item in manifest.get("artifacts", [])
        if isinstance(item, dict) and item.get("path")
    }
    runtime = manifest.get("runtime", {})
    for modality, component, runtime_field in (
        ("image", "image_encoder", "image_model"),
        ("text", "text_encoder", "text_model"),
    ):
        encoder_name, source_record, provenance = _selected_embedding_record(
            inputs, candidate, modality
        )
        exported = manifest.get("encoders", {}).get(modality)
        if not isinstance(exported, dict):
            raise TypeError(f"export lacks {modality} encoder provenance")
        extraction_receipt = source_record.get("extraction_receipt", {})
        expected_export = {
            "name": encoder_name,
            "repository": provenance.get("encoder", {}).get("repository"),
            "revision": provenance.get("encoder", {}).get("revision"),
            "extraction_receipt_sha256": extraction_receipt.get("sha256"),
            "embedding_sha256": provenance.get("embedding_sha256"),
            "extraction_code_commit": provenance.get("extraction_code_commit"),
            "preprocessing": provenance.get("preprocessing"),
            "preprocessing_sha256": provenance.get("preprocessing_sha256"),
            "pooling": provenance.get("pooling"),
            "prefix": provenance.get("prefix"),
            "max_length": provenance.get("max_length"),
            "dimension": provenance.get("dimension"),
            "dtype": provenance.get("dtype"),
        }
        mismatched_export = {
            key: {"expected": expected, "observed": exported.get(key)}
            for key, expected in expected_export.items()
            if exported.get(key) != expected
        }
        if mismatched_export:
            raise ValueError(
                f"exported {modality} encoder differs from selected embedding "
                f"provenance: {mismatched_export}"
            )

        report_path, report = reports_by_component[component]
        contract_path = _resolve_record_path(
            str(report.get("preprocessing_contract", "")), report_path
        )
        contract = _read_json(contract_path)
        expected_contract = {
            "encoder_name": encoder_name,
            "encoder": provenance.get("encoder"),
            "extraction_code_commit": provenance.get("extraction_code_commit"),
            "preprocessing": provenance.get("preprocessing"),
            "preprocessing_sha256": provenance.get("preprocessing_sha256"),
            "pooling": provenance.get("pooling"),
            "prefix": provenance.get("prefix"),
            "max_length": provenance.get("max_length"),
            "embedding_dtype": provenance.get("dtype"),
            "embedding_cache_sha256": provenance.get("embedding_sha256"),
            "embedding_extraction_receipt_sha256": extraction_receipt.get("sha256"),
        }
        mismatched_contract = {
            key: {"expected": expected, "observed": contract.get(key)}
            for key, expected in expected_contract.items()
            if contract.get(key) != expected
        }
        if mismatched_contract:
            raise ValueError(
                f"{modality} parity contract differs from the selected encoder: "
                f"{mismatched_contract}"
            )

        model_path = runtime.get(runtime_field)
        if not isinstance(model_path, str) or model_path not in artifact_by_path:
            raise ValueError(f"runtime.{runtime_field} is not a manifested model")
        model_name = Path(model_path).name
        prefix = str(Path(model_path).parent).replace("\\", "/")
        component_names = {
            model_name,
            f"{model_name}_data",
            f"{model_name}.data",
        }
        expected_component_hashes = {
            Path(path).name: str(record.get("sha256"))
            for path, record in artifact_by_path.items()
            if path.startswith(prefix + "/") and Path(path).name in component_names
        }
        if report.get("onnx_component_sha256") != expected_component_hashes:
            raise ValueError(
                f"{modality} parity ONNX components differ from exported artifacts"
            )


def _check_export_bundle(
    export_dir: Path,
    expected_manifest_sha256: str | None,
    experiment_run: Path | None,
    classifier_parity_path: Path | None = None,
    encoder_parity_paths: list[Path] | None = None,
) -> Gate:
    name, category = "receipt_bound_deployment_export", "deployment"
    manifest_path = export_dir.resolve() / "export_manifest.json"
    if not expected_manifest_sha256:
        return _failed(
            name,
            category,
            manifest_path,
            "pass an externally stored --export-manifest-sha256 trust anchor",
        )
    try:
        manifest = validate_export_manifest(
            export_dir,
            expected_manifest_sha256=expected_manifest_sha256,
            expected_classes=TARGET_CLASSES,
        )
        protocol = manifest["protocol"]
        if protocol.get("export_policy") != "locked_test_complete":
            raise ValueError(
                "selection-only bundles are preview artifacts, not Q2 deployment evidence"
            )
        if experiment_run is None:
            raise ValueError(
                "pass --experiment-run so the export can be bound to the locked run"
            )
        run_dir = experiment_run.resolve()
        config = _read_json(run_dir / "resolved_config.json")
        inputs = _read_json(run_dir / "metadata" / "input_manifest.json")
        selection_path = run_dir / "selection" / "selection_receipt.json"
        test_path = run_dir / "test" / "TEST_EVALUATION_COMPLETE.json"
        selection = _read_json(selection_path)
        test = _read_json(test_path)

        selected_candidate = str(selection.get("selected_candidate", ""))
        seed_values = [int(value) for value in config.get("seeds", [])]
        if (
            not selected_candidate
            or len(seed_values) < 5
            or manifest["model"].get("candidate") != selected_candidate
            or manifest["model"].get("seeds") != seed_values
            or manifest["model"].get("ensemble_size") != len(seed_values)
            or manifest["model"].get("probability_aggregation")
            != "equal_weight_arithmetic_mean"
        ):
            raise ValueError(
                "export candidate/seed ensemble differs from the frozen selection"
            )
        expected_links = {
            "protocol_digest": _resolved_protocol_digest(config),
            "input_manifest_digest": _object_sha256(inputs),
            "selection_receipt_digest": selection.get("receipt_digest"),
            "locked_test_receipt_digest": test.get("receipt_digest"),
            "source_class_map_sha256": inputs.get("class_map_sha256"),
        }
        mismatches = {
            key: {"expected": expected, "observed": protocol.get(key)}
            for key, expected in expected_links.items()
            if not expected or protocol.get(key) != expected
        }
        if mismatches:
            raise ValueError(
                f"export/experiment receipt crosslinks differ: {mismatches}"
            )
        if (
            manifest.get("calibration") != selection.get("calibration_protocol")
            or manifest.get("review_policy") != selection.get("review_policy")
            or test.get("calibration_protocol") != selection.get("calibration_protocol")
            or test.get("review_policy_applied_unchanged")
            != selection.get("review_policy")
        ):
            raise ValueError(
                "export calibration/review thresholds differ from the validation-frozen "
                "selection and locked-test execution"
            )

        source_members = protocol.get("source_members")
        runtime_members = manifest.get("runtime", {}).get("classifier_members")
        if not isinstance(source_members, list) or not isinstance(
            runtime_members, list
        ):
            raise TypeError("export lacks classifier/source ensemble members")
        if [item.get("seed") for item in source_members] != seed_values or [
            item.get("seed") for item in runtime_members
        ] != seed_values:
            raise ValueError("export classifier members differ from frozen seed order")
        frozen_records = selection.get("model_records", {}).get(selected_candidate, {})
        for member in source_members:
            seed = int(member["seed"])
            checkpoint = frozen_records.get(str(seed))
            if not isinstance(checkpoint, dict):
                raise TypeError(
                    f"selection receipt lacks checkpoint record for seed {seed}"
                )
            ok, detail = _verify_artifact(checkpoint, selection_path)
            if not ok:
                raise ValueError(f"deployed checkpoint seed {seed}: {detail}")
            if checkpoint.get("sha256") != member.get("checkpoint_sha256"):
                raise ValueError(
                    f"export source checkpoint differs for frozen seed {seed}"
                )
            unit_path = (
                run_dir
                / "selection"
                / selected_candidate
                / f"seed_{seed}"
                / "unit_receipt.json"
            )
            if not unit_path.is_file() or _sha256(unit_path) != member.get(
                "unit_receipt_sha256"
            ):
                raise ValueError(
                    f"export source unit receipt is missing/changed for seed {seed}"
                )
        if classifier_parity_path is not None and classifier_parity_path.is_file():
            parity = _read_json(classifier_parity_path)
            parity_members = parity.get("members")
            if (
                parity.get("seeds") != seed_values
                or not isinstance(parity_members, list)
                or len(parity_members) != len(runtime_members)
            ):
                raise ValueError("classifier parity seed order differs from export")
            artifact_by_path = {
                item["path"]: item for item in manifest.get("artifacts", [])
            }
            for runtime_member, parity_member in zip(
                runtime_members, parity_members, strict=True
            ):
                expected_onnx = artifact_by_path[runtime_member["onnx"]]["sha256"]
                expected_native = artifact_by_path[runtime_member["native"]]["sha256"]
                if (
                    parity_member.get("onnx_model_sha256") != expected_onnx
                    or parity_member.get("native_model_sha256") != expected_native
                ):
                    raise ValueError(
                        f"classifier parity files differ for seed {runtime_member['seed']}"
                    )
        if encoder_parity_paths:
            _validate_encoder_export_parity_lineage(
                manifest=manifest,
                inputs=inputs,
                config=config,
                selection=selection,
                encoder_parity_paths=encoder_parity_paths,
            )
        return Gate(
            name,
            category,
            True,
            str(manifest_path),
            (
                "externally anchored five-seed export, all runtime heads, class "
                "semantics, encoder revisions, and locked-run links verified"
            ),
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ExportContractError,
    ) as exc:
        return _failed(name, category, manifest_path, str(exc))


def _check_label_audit(path: Path) -> Gate:
    name, category = "independent_label_audit", "validity"
    if not path.is_file():
        return _failed(name, category, path, "aggregate label-audit report is missing")
    try:
        report = _read_json(path)
        annotators = report.get("annotators", [])
        if len(annotators) != 2:
            raise ValueError("exactly two independent annotators are required")
        if report.get("sampling_design") != "stratified_without_replacement":
            raise ValueError("the label audit is not bound to the prescribed design")
        if not report.get("sample_receipt_sha256") or not report.get(
            "sample_content_sha256"
        ):
            raise ValueError("sample receipt/content hashes are missing")
        if report.get("independent_annotation_attested") is not True:
            raise ValueError("independent annotation has not been attested")
        release = report.get("test_label_release_authority", {})
        if (
            release.get("authorization_mode")
            not in {"independent_data_custodian", "post_locked_test_completion"}
            or not release.get("sha256")
            or not release.get("authorized_at_utc")
        ):
            raise ValueError("test-label release authority is missing")
        roles: list[str] = []
        for annotator in annotators:
            if int(annotator.get("scored_rows", 0)) != int(
                annotator.get("total_rows", -1)
            ):
                raise ValueError("an annotation worksheet is incomplete")
            if len(annotator.get("per_class", {})) != 9:
                raise ValueError("per-class results do not cover all nine labels")
            if not annotator.get("micro_approx_stratified_95"):
                raise ValueError(
                    "design-aware approximate confidence interval is missing"
                )
            role = str(annotator.get("annotator_role", "")).strip()
            if not role:
                raise ValueError("an annotator domain role is missing")
            roles.append(role)
        if len(set(roles)) != 2:
            raise ValueError("annotator roles must identify two distinct reviewers")
        agreement = report.get("inter_annotator", {})
        if int(agreement.get("paired_scored", 0)) != int(annotators[0]["scored_rows"]):
            raise ValueError("inter-annotator rows are incomplete")
        if "cohen_kappa" not in agreement or "observed_agreement" not in agreement:
            raise ValueError("agreement statistics are missing")
        if (
            "resolved_label_exact_agreement" not in agreement
            or "resolved_label_mean_jaccard" not in agreement
        ):
            raise ValueError("resolved-label agreement statistics are missing")
        if "disagreement_row_ids" in agreement:
            raise ValueError("public aggregate report contains raw disagreement IDs")
        return Gate(
            name,
            category,
            True,
            str(path),
            "two independently attested complete worksheets, design-aware intervals, and agreement verified",
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, path, str(exc))


def _check_privacy_screen(path: Path) -> Gate:
    name, category = "aggregate_privacy_screen", "governance"
    if not path.is_file():
        return _failed(name, category, path, "privacy-screen report is missing")
    try:
        report = _read_json(path)
        if int(report.get("rows_scanned", 0)) <= 0:
            raise ValueError("no rows were scanned")
        if not report.get("input_sha256") or not report.get("limitations"):
            raise ValueError("input hash or limitations are missing")
        return Gate(
            name,
            category,
            True,
            str(path),
            "regex/EXIF screening complete; pixel and governance attestations remain separate gates",
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, path, str(exc))


def _verify_report_file(
    report: dict[str, Any],
    report_path: Path,
    path_key: str,
    hash_key: str,
) -> None:
    raw_path = report.get(path_key)
    expected_hash = report.get(hash_key)
    if not raw_path or not expected_hash:
        raise ValueError(f"{path_key}/{hash_key} binding is missing")
    ok, detail = _verify_artifact(
        {"path": str(raw_path), "sha256": str(expected_hash)}, report_path
    )
    if not ok:
        raise ValueError(f"{path_key}: {detail}")


def _required_parity_metric(
    record: dict[str, Any],
    field: str,
    *,
    low: float | None = None,
    high: float | None = None,
) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"parity metric {field} must be numeric")
    number = float(value)
    if (
        not math.isfinite(number)
        or (low is not None and number < low)
        or (high is not None and number > high)
    ):
        raise ValueError(f"parity metric {field} is outside its valid range")
    return number


def _validate_classifier_parity_metrics(record: dict[str, Any], context: str) -> None:
    if (
        record.get("probability_tolerance")
        != CLASSIFIER_PARITY_TOLERANCES["probability_tolerance"]
        or record.get("minimum_top1_agreement")
        != CLASSIFIER_PARITY_TOLERANCES["minimum_top1_agreement"]
    ):
        raise ValueError(f"{context} tolerances differ from the frozen policy")
    errors = [
        _required_parity_metric(record, field, low=0.0)
        for field in (
            "p50_absolute_probability_error",
            "p95_absolute_probability_error",
            "p99_absolute_probability_error",
            "max_absolute_probability_error",
        )
    ]
    _required_parity_metric(record, "mean_absolute_probability_error", low=0.0)
    agreement = _required_parity_metric(record, "top1_agreement", low=0.0, high=1.0)
    if errors != sorted(errors):
        raise ValueError(f"{context} error percentiles are not monotonic")
    if (
        errors[-1] > CLASSIFIER_PARITY_TOLERANCES["probability_tolerance"]
        or agreement < CLASSIFIER_PARITY_TOLERANCES["minimum_top1_agreement"]
        or record.get("passed") is not True
    ):
        raise ValueError(f"{context} metrics violate the frozen policy")


def _validate_encoder_parity_metrics(record: dict[str, Any]) -> None:
    if (
        record.get("absolute_tolerance")
        != ENCODER_TENSOR_PARITY_TOLERANCES["absolute_tolerance"]
        or record.get("minimum_cosine_similarity")
        != ENCODER_TENSOR_PARITY_TOLERANCES["minimum_cosine_similarity"]
    ):
        raise ValueError("encoder parity tolerances differ from the frozen policy")
    errors = [
        _required_parity_metric(record, field, low=0.0)
        for field in (
            "p50_absolute_error",
            "p95_absolute_error",
            "p99_absolute_error",
            "max_absolute_error",
        )
    ]
    _required_parity_metric(record, "mean_absolute_error", low=0.0)
    minimum_cosine = _required_parity_metric(
        record, "minimum_row_cosine_similarity", low=-1.0, high=1.0
    )
    if errors != sorted(errors):
        raise ValueError("encoder parity error percentiles are not monotonic")
    if (
        errors[-1] > ENCODER_TENSOR_PARITY_TOLERANCES["absolute_tolerance"]
        or minimum_cosine
        < ENCODER_TENSOR_PARITY_TOLERANCES["minimum_cosine_similarity"]
        or record.get("passed") is not True
    ):
        raise ValueError("encoder parity metrics violate the frozen policy")


def _check_parity(
    path: Path,
    name: str,
    *,
    expected_component: str,
    require_locked_test: bool = True,
) -> Gate:
    category = "deployment"
    if not path.is_file():
        return _failed(name, category, path, "parity report is missing")
    try:
        report = _read_json(path)
        if report.get("passed") is not True or int(report.get("samples", 0)) <= 0:
            raise ValueError("parity gate did not pass on a non-empty sample")
        if report.get("component") != expected_component:
            raise ValueError(
                f"component must be {expected_component}, got {report.get('component')!r}"
            )
        if require_locked_test and (
            report.get("evaluation_split") != "locked_test"
            or not report.get("test_ids_sha256")
            or not report.get("split_manifest_sha256")
        ):
            raise ValueError(
                "parity report is not bound to locked-test IDs and split manifest"
            )
        if not report.get("execution_providers") or not report.get(
            "onnx_opset_imports"
        ):
            raise ValueError("runtime provider or ONNX opset metadata is missing")
        versions = report.get("software_versions", {})
        if not {"numpy", "onnxruntime", "onnx"}.issubset(versions):
            raise ValueError("required software versions are missing")
        _verify_report_file(report, path, "test_ids", "test_ids_sha256")
        _verify_report_file(report, path, "split_manifest", "split_manifest_sha256")
        _verify_locked_test_ids(report, path)
        if expected_component == "classifier":
            required_errors = {
                "p50_absolute_probability_error",
                "p95_absolute_probability_error",
                "p99_absolute_probability_error",
                "max_absolute_probability_error",
            }
            if not required_errors.issubset(report):
                raise ValueError("classifier error percentiles are incomplete")
            if report.get("tolerance_source") != "frozen_export_contract_v4":
                raise ValueError("classifier parity tolerance source is not frozen")
            _validate_classifier_parity_metrics(report, "classifier ensemble")
            if (
                report.get("parity_scope")
                != "equal_weight_native_and_onnx_seed_ensemble"
                or report.get("probability_aggregation")
                != "equal_weight_arithmetic_mean"
            ):
                raise ValueError(
                    "classifier parity does not cover the deployed ensemble"
                )
            members = report.get("members")
            parity_seeds = report.get("seeds")
            if (
                not isinstance(members, list)
                or len(members) < 5
                or report.get("ensemble_size") != len(members)
                or not isinstance(parity_seeds, list)
                or len(parity_seeds) != len(members)
                or len(set(parity_seeds)) != len(parity_seeds)
            ):
                raise ValueError(
                    "classifier parity must cover at least five seed heads"
                )
            for index, member in enumerate(members):
                if not isinstance(member, dict) or member.get("passed") is not True:
                    raise ValueError(f"classifier parity member {index} did not pass")
                _validate_classifier_parity_metrics(
                    member, f"classifier parity member {index}"
                )
                if member.get("member_index") != index:
                    raise ValueError("classifier parity member order is not frozen")
                if member.get("seed") != parity_seeds[index]:
                    raise ValueError("classifier parity seed order is inconsistent")
                for path_key, hash_key in (
                    ("native_model", "native_model_sha256"),
                    ("onnx_model", "onnx_model_sha256"),
                ):
                    _verify_report_file(member, path, path_key, hash_key)
                if member.get("native_class_order") != member.get(
                    "onnx_class_order"
                ) or member.get("native_class_order") != list(
                    range(int(report.get("classes", 0)))
                ):
                    raise ValueError(
                        f"classifier member {index} class order is not verified"
                    )
            for path_key, hash_key in (
                ("feature_sample", "feature_sample_sha256"),
                ("class_map", "class_map_sha256"),
                ("feature_receipt", "feature_receipt_sha256"),
            ):
                _verify_report_file(report, path, path_key, hash_key)
            semantic_digest = report.get("class_map_semantic_sha256")
            native_order = report.get("native_class_order")
            onnx_order = report.get("onnx_class_order")
            if (
                not semantic_digest
                or native_order != onnx_order
                or native_order != list(range(int(report.get("classes", 0))))
            ):
                raise ValueError("classifier class semantics/order are not verified")
            class_map_path = _resolve_record_path(str(report["class_map"]), path)
            class_map = _read_json(class_map_path)
            if (
                class_map.get("sha256") != semantic_digest
                or _class_map_sha256(class_map) != semantic_digest
            ):
                raise ValueError("classifier class-map semantic digest mismatch")
            expected_names = [
                item.get("label_name") for item in class_map.get("classes", [])
            ]
            if report.get("ordered_class_names") != expected_names:
                raise ValueError("classifier ordered class names differ from class map")
            feature_receipt_path = _resolve_record_path(
                str(report["feature_receipt"]), path
            )
            feature_receipt = _read_json(feature_receipt_path)
            expected_feature_bindings = {
                "feature_sample_sha256": report.get("feature_sample_sha256"),
                "ordered_test_ids_sha256": report.get("ordered_test_ids_sha256"),
                "split_manifest_sha256": report.get("split_manifest_sha256"),
                "class_map_semantic_sha256": semantic_digest,
                "rows": int(report.get("samples", 0)),
            }
            if any(
                feature_receipt.get(key) != expected
                for key, expected in expected_feature_bindings.items()
            ):
                raise ValueError("feature receipt is not cross-bound to parity inputs")
        else:
            required_errors = {
                "p50_absolute_error",
                "p95_absolute_error",
                "p99_absolute_error",
                "max_absolute_error",
            }
            if not required_errors.issubset(report):
                raise ValueError("encoder error percentiles are incomplete")
            if report.get("tolerance_source") != "frozen_export_contract_v4":
                raise ValueError("encoder parity tolerance source is not frozen")
            _validate_encoder_parity_metrics(report)
            if (
                report.get("parity_scope")
                != "native_reference_vs_onnx_at_tensor_boundary"
            ):
                raise ValueError("encoder tensor-boundary parity scope is not explicit")
            if report.get("raw_input_end_to_end") is not False:
                raise ValueError(
                    "encoder tensor report has an invalid raw-input scope flag"
                )
            for path_key, hash_key in (
                ("input_sample", "input_sample_sha256"),
                ("reference_output", "reference_output_sha256"),
                ("preprocessing_contract", "preprocessing_contract_sha256"),
            ):
                _verify_report_file(report, path, path_key, hash_key)
            contract_path = _resolve_record_path(
                str(report["preprocessing_contract"]), path
            )
            contract = _read_json(contract_path)
            expected_contract = {
                "component": expected_component,
                "tensor_input_sha256": report.get("input_sample_sha256"),
                "native_reference_sha256": report.get("reference_output_sha256"),
                "ordered_test_ids_sha256": report.get("ordered_test_ids_sha256"),
                "split_manifest_sha256": report.get("split_manifest_sha256"),
                "rows": int(report.get("samples", 0)),
            }
            if any(
                contract.get(key) != expected
                for key, expected in expected_contract.items()
            ):
                raise ValueError("encoder preprocessing contract crosslinks differ")
            encoder = contract.get("encoder", {})
            if not re.fullmatch(
                r"[0-9a-fA-F]{40,64}", str(encoder.get("revision", ""))
            ) or not re.fullmatch(
                r"[0-9a-fA-F]{40,64}",
                str(contract.get("extraction_code_commit", "")),
            ):
                raise ValueError("encoder/preprocessing revisions are not immutable")
            modality = "text" if expected_component == "text_encoder" else "image"
            try:
                validate_preprocessing_contract(
                    contract.get("preprocessing"),
                    modality=modality,
                    pooling=contract.get("pooling"),
                    prefix=contract.get("prefix"),
                    max_length=contract.get("max_length"),
                    output_dtype=contract.get("embedding_dtype"),
                )
            except PreprocessingContractError as exc:
                raise ValueError(
                    f"encoder parity preprocessing contract: {exc}"
                ) from exc
            if preprocessing_sha256(contract["preprocessing"]) != contract.get(
                "preprocessing_sha256"
            ):
                raise ValueError(
                    "encoder parity preprocessing semantic digest mismatch"
                )
            if (
                report.get("encoder_name") != contract.get("encoder_name")
                or report.get("embedding_cache_sha256")
                != contract.get("embedding_cache_sha256")
                or report.get("embedding_extraction_receipt_sha256")
                != contract.get("embedding_extraction_receipt_sha256")
                or report.get("reference_cache_tolerance") != 1e-6
                or not isinstance(
                    report.get("reference_cache_max_absolute_error"), (int, float)
                )
                or float(report["reference_cache_max_absolute_error"]) > 1e-6
            ):
                raise ValueError(
                    "encoder native reference is not bound to the selected "
                    "embedding-cache rows"
                )
            for file_field, hash_field in (
                ("embedding_cache", "embedding_cache_sha256"),
                (
                    "embedding_extraction_receipt",
                    "embedding_extraction_receipt_sha256",
                ),
            ):
                linked = _resolve_record_path(
                    str(contract.get(file_field, "")), contract_path
                )
                if (
                    not linked.is_file()
                    or linked.is_symlink()
                    or _sha256(linked) != contract.get(hash_field)
                ):
                    raise ValueError(
                        f"encoder parity {file_field} is missing or changed"
                    )
            onnx_path = _resolve_record_path(str(report.get("onnx_model", "")), path)
            component_hashes = report.get("onnx_component_sha256", {})
            expected_onnx_hash = component_hashes.get(onnx_path.name)
            if not onnx_path.is_file() or not expected_onnx_hash:
                raise ValueError("encoder ONNX graph/hash binding is missing")
            if _sha256(onnx_path) != expected_onnx_hash:
                raise ValueError("encoder ONNX graph hash mismatch")
        return Gate(
            name,
            category,
            True,
            str(path),
            "recorded locked-test component parity passed with verified hashes, percentiles, runtime, and opset",
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, path, str(exc))


def _check_evidence_crosslinks(
    *,
    split_manifest_path: Path,
    experiment_run: Path | None,
    classifier_parity_path: Path,
    encoder_parity_paths: list[Path],
) -> Gate:
    name, category = "evidence_digest_crosslinks", "integrity"
    try:
        split = _read_json(split_manifest_path)
        split_hash = _sha256(split_manifest_path)
        class_digest = split.get("class_map", {}).get("sha256")
        if not class_digest:
            raise ValueError("split class-map digest is missing")
        reports = [_read_json(classifier_parity_path)] + [
            _read_json(path) for path in encoder_parity_paths
        ]
        if any(report.get("split_manifest_sha256") != split_hash for report in reports):
            raise ValueError(
                "a parity report is not bound to the supplied split manifest"
            )
        if reports[0].get("class_map_semantic_sha256") != class_digest:
            raise ValueError("classifier parity uses a different class-map contract")
        ordered_ids = {report.get("ordered_test_ids_sha256") for report in reports}
        if None in ordered_ids or len(ordered_ids) != 1:
            raise ValueError(
                "parity reports do not share one ordered locked-test ID digest"
            )
        if experiment_run is not None:
            run_dir = experiment_run.resolve()
            inputs = _read_json(run_dir / "metadata" / "input_manifest.json")
            config = _read_json(run_dir / "resolved_config.json")
            selection = _read_json(run_dir / "selection" / "selection_receipt.json")
            selected_candidate = _selected_candidate_config(config, selection)
            if inputs.get("class_map_sha256") != class_digest:
                raise ValueError("experiment and split class-map digests differ")
            if inputs.get("split_manifest", {}).get("sha256") != split_hash:
                raise ValueError(
                    "experiment input manifest binds a different split manifest"
                )
            embedding_provenance = [
                (str(name), record.get("provenance", {}))
                for name, record in inputs.get("embeddings", {}).items()
                if isinstance(record, dict)
            ]
            classifier_report = reports[0]
            feature_receipt_path = _resolve_record_path(
                str(classifier_report.get("feature_receipt", "")),
                classifier_parity_path,
            )
            feature_receipt = _read_json(feature_receipt_path)
            fusion = feature_receipt.get("fusion", {})
            if (
                feature_receipt.get("schema_version") != 2
                or feature_receipt.get("selected_candidate")
                != selection.get("selected_candidate")
                or feature_receipt.get("embedding_index_column")
                != config.get("embedding_index_column")
                or fusion.get("operation") != "concatenate"
                or fusion.get("modality_order") != ["image", "text"]
                or fusion.get("axis") != 1
                or fusion.get("l2_per_modality") != config.get("l2_per_modality")
                or fusion.get("l2_epsilon") != 1e-9
                or fusion.get("output_dtype") != "float32"
            ):
                raise ValueError(
                    "classifier parity fused-feature receipt differs from the "
                    "selected Phase-A feature construction"
                )
            source_embeddings = feature_receipt.get("source_embeddings", {})
            source_dimension = 0
            for modality in ("image", "text"):
                encoder_name, embedding_record, provenance = _selected_embedding_record(
                    inputs, selected_candidate, modality
                )
                source = source_embeddings.get(modality)
                if not isinstance(source, dict):
                    raise TypeError(
                        f"classifier parity lacks selected {modality} embedding"
                    )
                extraction = embedding_record.get("extraction_receipt", {})
                expected_source = {
                    "key": f"{modality}:{encoder_name}",
                    "encoder_name": encoder_name,
                    "sha256": embedding_record.get("sha256"),
                    "extraction_receipt_sha256": extraction.get("sha256"),
                    "preprocessing_sha256": provenance.get("preprocessing_sha256"),
                    "dimension": provenance.get("dimension"),
                    "dtype": provenance.get("dtype"),
                }
                if any(
                    source.get(key) != expected
                    for key, expected in expected_source.items()
                ):
                    raise ValueError(
                        f"classifier parity {modality} source is not the selected "
                        "experiment embedding"
                    )
                declared_source_path = _resolve_record_path(
                    str(source.get("path", "")), feature_receipt_path
                )
                declared_extraction_path = _resolve_record_path(
                    str(source.get("extraction_receipt_path", "")),
                    feature_receipt_path,
                )
                if (
                    declared_source_path
                    != Path(str(embedding_record.get("path"))).resolve()
                ):
                    raise ValueError(
                        f"classifier parity {modality} embedding path differs"
                    )
                if (
                    declared_extraction_path
                    != Path(str(extraction.get("path"))).resolve()
                ):
                    raise ValueError(
                        f"classifier parity {modality} receipt path differs"
                    )
                source_dimension += int(provenance.get("dimension", 0))
            if feature_receipt.get("dimension") != source_dimension:
                raise ValueError(
                    "classifier parity fused feature dimension differs from selected "
                    "encoder dimensions"
                )
            for report_path, report in zip(
                encoder_parity_paths, reports[1:], strict=True
            ):
                contract_path = _resolve_record_path(
                    str(report["preprocessing_contract"]), report_path
                )
                contract = _read_json(contract_path)
                modality = (
                    "text" if contract.get("component") == "text_encoder" else "image"
                )
                expected_encoder_name = selected_candidate.get(f"{modality}_encoder")
                if not isinstance(expected_encoder_name, str):
                    raise TypeError(
                        f"selected candidate has no {modality} encoder for parity"
                    )
                contract_encoder = contract.get("encoder", {})
                matches = [
                    provenance
                    for name, provenance in embedding_provenance
                    if name == f"{modality}:{expected_encoder_name}"
                    and contract.get("encoder_name") == expected_encoder_name
                    and provenance.get("encoder") == contract_encoder
                    and provenance.get("preprocessing_sha256")
                    == contract.get("preprocessing_sha256")
                    and provenance.get("extraction_code_commit")
                    == contract.get("extraction_code_commit")
                ]
                if not matches:
                    raise ValueError(
                        f"{modality} parity preprocessing is not bound to any "
                        "experiment embedding receipt"
                    )
        return Gate(
            name,
            category,
            True,
            str(split_manifest_path),
            "split, experiment, classifier, encoders, class map, and ordered test IDs share verified digests",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, split_manifest_path, str(exc))


def _finite_number(value: Any, field: str, *, low: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or (low is not None and number < low):
        raise ValueError(f"{field} is outside its valid range")
    return number


def _proportion(value: Any, field: str) -> float:
    number = _finite_number(value, field, low=0.0)
    if number > 1.0:
        raise ValueError(f"{field} must be between 0 and 1")
    return number


def _validate_governance(value: dict[str, Any]) -> None:
    if value.get("decision") not in {"approved", "exempt", "not_required"}:
        raise ValueError(
            "governance decision must be approved, exempt, or not_required"
        )
    if not value.get("decision_reference") or not value.get("jurisdiction_basis"):
        raise ValueError("governance decision reference/jurisdiction basis is missing")


def _validate_visual_privacy(value: dict[str, Any]) -> None:
    rows_reviewed = value.get("rows_reviewed")
    if (
        isinstance(rows_reviewed, bool)
        or not isinstance(rows_reviewed, int)
        or rows_reviewed < 1
    ):
        raise ValueError("rows_reviewed must be positive")
    required = {
        "faces",
        "people",
        "addresses",
        "documents",
        "house_numbers",
        "license_plates",
    }
    if not required.issubset(set(value.get("review_scope", []))):
        raise ValueError("visual privacy review scope is incomplete")
    coverage_mode = value.get("coverage_mode")
    if coverage_mode not in {"census", "risk_based_sample"}:
        raise ValueError("coverage_mode must be census or risk_based_sample")
    if coverage_mode == "risk_based_sample" and not value.get("sampling_basis"):
        raise ValueError("risk-based privacy review requires sampling_basis")
    required_artifacts = {
        "dataset_images",
        "manuscript_pdf",
        "supplementary_material",
    }
    if not required_artifacts.issubset(set(value.get("reviewed_artifact_classes", []))):
        raise ValueError(
            "privacy review did not cover every publication artifact class"
        )
    finding_counts: dict[str, int] = {}
    for field in (
        "sensitive_findings_detected",
        "sensitive_findings_resolved",
        "unresolved_sensitive_findings",
    ):
        count = value.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"{field} must be a non-negative integer")
        finding_counts[field] = count
    if (
        finding_counts["sensitive_findings_resolved"]
        + finding_counts["unresolved_sensitive_findings"]
        != finding_counts["sensitive_findings_detected"]
    ):
        raise ValueError("privacy finding counts are internally inconsistent")
    if finding_counts["unresolved_sensitive_findings"] != 0:
        raise ValueError("unresolved sensitive findings remain")
    if value.get("publication_outputs_cleared") is not True:
        raise ValueError("publication outputs have not been cleared for release")
    if finding_counts["sensitive_findings_detected"] and not value.get(
        "remediation_reference"
    ):
        raise ValueError("resolved privacy findings require remediation_reference")
    digest_roles = {
        "dataset_image_manifest_sha256": "dataset_image_manifest",
        "manuscript_pdf_sha256": "final_manuscript_pdf",
        "supplementary_material_manifest_sha256": "supplementary_material_manifest",
    }
    evidence_files = value.get("evidence_files")
    if not isinstance(evidence_files, list):
        raise TypeError("visual privacy evidence_files must be a list")
    evidence_by_role = {
        str(record.get("role")): record
        for record in evidence_files
        if isinstance(record, dict) and record.get("role")
    }
    for field, role in digest_roles.items():
        digest = value.get(field)
        if not re.fullmatch(r"[0-9a-f]{64}", str(digest or "")):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        record = evidence_by_role.get(role)
        if not isinstance(record, dict) or record.get("sha256") != digest:
            raise ValueError(f"{field} is not cross-linked to evidence role {role}")


def _validate_routing(value: dict[str, Any]) -> None:
    sample_size = int(value.get("sample_size", 0))
    reviewers = int(value.get("agency_reviewers", 0))
    if sample_size < 1 or reviewers < 1:
        raise ValueError("routing sample_size/agency_reviewers must be positive")
    accuracy = _proportion(
        value.get("metrics", {}).get("routing_accuracy"), "routing_accuracy"
    )
    correct = int(value.get("routing_correct", -1))
    if not 0 <= correct <= sample_size or abs(correct / sample_size - accuracy) > 1e-9:
        raise ValueError("routing numerator/denominator do not reproduce accuracy")


def _validate_external(value: dict[str, Any]) -> None:
    if int(value.get("sample_size", 0)) < 1:
        raise ValueError("external sample_size must be positive")
    if not value.get("source_domain") or value.get("source_domain") == value.get(
        "development_domain"
    ):
        raise ValueError("external source and development domains must differ")
    _proportion(value.get("metrics", {}).get("macro_f1"), "external macro_f1")


def _attested_utc(value: Any, field: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"{field} must be timezone-aware UTC")
    return parsed


def _validate_phase_b_later_cohort(value: dict[str, Any]) -> None:
    sample_size = value.get("sample_size")
    if (
        isinstance(sample_size, bool)
        or not isinstance(sample_size, int)
        or sample_size < 1
    ):
        raise ValueError("Phase-B sample_size must be a positive integer")
    if value.get("cohort_type") != "strictly_later_same_domain":
        raise ValueError("Phase B must be declared strictly_later_same_domain")
    development_domain = value.get("development_domain")
    phase_b_domain = value.get("phase_b_domain")
    if not development_domain or phase_b_domain != development_domain:
        raise ValueError("Phase B must use the same declared task/source domain")
    for field in (
        "unavailable_during_model_development",
        "unseen_until_protocol_freeze",
        "single_access_after_freeze",
    ):
        if value.get(field) is not True:
            raise ValueError(f"{field} must be explicitly true")
    if value.get("retuning_after_unseal") is not False:
        raise ValueError("retuning_after_unseal must be explicitly false")
    if value.get("access_count") != 1:
        raise ValueError("Phase-B access_count must equal one")

    development_max = _attested_utc(
        value.get("development_data_max_utc"), "development_data_max_utc"
    )
    cohort_start = _attested_utc(
        value.get("phase_b_cohort_start_utc"), "phase_b_cohort_start_utc"
    )
    cohort_end = _attested_utc(
        value.get("phase_b_cohort_end_utc"), "phase_b_cohort_end_utc"
    )
    protocol_frozen = _attested_utc(
        value.get("protocol_frozen_at_utc"), "protocol_frozen_at_utc"
    )
    unsealed = _attested_utc(
        value.get("phase_b_unsealed_at_utc"), "phase_b_unsealed_at_utc"
    )
    evaluated = _attested_utc(value.get("evaluated_at_utc"), "evaluated_at_utc")
    if not development_max < cohort_start <= cohort_end:
        raise ValueError("Phase-B cohort is not strictly later than development data")
    if not protocol_frozen < unsealed:
        raise ValueError("Phase B was not unsealed after the protocol freeze")
    if unsealed < cohort_end:
        raise ValueError("Phase B was accessed before its cohort was complete")
    if evaluated < unsealed:
        raise ValueError("Phase-B evaluation predates the recorded unsealing")

    digest_roles = {
        "cohort_manifest_sha256": "phase_b_cohort_manifest",
        "cohort_membership_sha256": "phase_b_cohort_membership",
        "access_log_sha256": "phase_b_access_log",
        "analysis_plan_sha256": "frozen_analysis_plan",
        "phase_b_results_sha256": "phase_b_per_sample_predictions",
    }
    evidence_files = value.get("evidence_files")
    if not isinstance(evidence_files, list):
        raise TypeError("Phase-B evidence_files must be a list")
    evidence_by_role = {
        str(record.get("role")): record
        for record in evidence_files
        if isinstance(record, dict) and record.get("role")
    }
    for field, role in digest_roles.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(value.get(field, ""))):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
        record = evidence_by_role.get(role)
        if not isinstance(record, dict) or record.get("sha256") != value.get(field):
            raise ValueError(f"{field} is not cross-linked to evidence role {role}")
    _proportion(value.get("metrics", {}).get("macro_f1"), "Phase-B macro_f1")
    if not re.fullmatch(
        r"[0-9a-f]{64}", str(value.get("phase_b_ordered_ids_sha256", ""))
    ):
        raise ValueError("Phase-B ordered result IDs digest is missing")
    for field in (
        "development_source_snapshot_sha256",
        "phase_b_source_snapshot_sha256",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value.get(field, ""))):
            raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    if not value.get("release_candidate") or not value.get("release_model_version"):
        raise ValueError("Phase-B results do not identify the selected release")


def _phase_b_evidence_path(
    records: dict[str, Any],
    *,
    role: str,
    digest_field: str,
    report: dict[str, Any],
    report_path: Path,
) -> Path:
    record = records.get(role)
    if not isinstance(record, dict):
        raise TypeError(f"Phase-B {role} evidence is missing")
    if record.get("sha256") != report.get(digest_field):
        raise ValueError(f"Phase-B {role} digest is not cross-linked")
    ok, detail = _verify_artifact(record, report_path)
    if not ok:
        raise ValueError(f"Phase-B {role} evidence: {detail}")
    return _resolve_record_path(str(record.get("path", "")), report_path)


def _phase_a_reference(
    split_manifest_path: Path,
) -> tuple[datetime, str, set[str], set[str]]:
    manifest = _read_json(split_manifest_path)
    parameters = manifest.get("parameters", {})
    id_column = parameters.get("id_column")
    time_column = manifest.get("time_column") or parameters.get("time_column")
    if not isinstance(id_column, str) or not id_column:
        raise ValueError("Phase-A split manifest lacks its ID-column contract")
    if not isinstance(time_column, str) or not time_column:
        raise ValueError("Phase-A split manifest lacks its UTC time-column contract")

    source_record = manifest.get("source")
    ok, detail = _verify_artifact(source_record, split_manifest_path)
    if not ok:
        raise ValueError(f"Phase-A source snapshot: {detail}")
    assert isinstance(source_record, dict)
    source_digest = str(source_record.get("sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", source_digest):
        raise ValueError("Phase-A source snapshot digest is not lowercase SHA-256")
    source_path = _resolve_record_path(str(source_record["path"]), split_manifest_path)
    with source_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {id_column, time_column}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Phase-A source snapshot lacks ID/time columns")
        source_rows = list(reader)
    if not source_rows:
        raise ValueError("Phase-A source snapshot is empty")
    source_ids = [str(row[id_column]) for row in source_rows]
    if any(not value for value in source_ids) or len(set(source_ids)) != len(
        source_ids
    ):
        raise ValueError("Phase-A source IDs must be non-empty and unique")
    source_timestamps = [
        _attested_utc(row[time_column], f"Phase-A source {time_column}")
        for row in source_rows
    ]
    source_max = max(source_timestamps)
    manifest_max = _attested_utc(
        manifest.get("time_range", {}).get("max"), "Phase-A manifest time_range.max"
    )
    if manifest_max != source_max:
        raise ValueError(
            "Phase-A manifest maximum timestamp does not recompute from its "
            "hashed source snapshot"
        )

    output_ids: set[str] = set()
    output_groups: set[str] = set()
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise TypeError("Phase-A split manifest outputs are missing")
    for split in ("train", "val", "test", "quarantine"):
        record = outputs.get(split)
        if record is None:
            if split == "quarantine":
                continue
            raise ValueError(f"Phase-A split manifest lacks {split} output")
        ok, detail = _verify_artifact(record, split_manifest_path)
        if not ok:
            raise ValueError(f"Phase-A {split} output: {detail}")
        assert isinstance(record, dict)
        output_path = _resolve_record_path(str(record["path"]), split_manifest_path)
        with output_path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or id_column not in reader.fieldnames:
                raise ValueError(f"Phase-A {split} output lacks {id_column!r}")
            if "leakage_group_id" not in reader.fieldnames:
                raise ValueError(
                    f"Phase-A {split} output lacks leakage_group_id lineage"
                )
            for row in reader:
                sample_id = str(row[id_column])
                leakage_group_id = str(row["leakage_group_id"])
                if not sample_id or not leakage_group_id:
                    raise ValueError(
                        f"Phase-A {split} contains an empty ID or leakage group"
                    )
                if sample_id in output_ids:
                    raise ValueError("Phase-A split outputs contain duplicate IDs")
                output_ids.add(sample_id)
                output_groups.add(leakage_group_id)
    if not output_ids.issubset(set(source_ids)):
        raise ValueError("Phase-A split IDs are absent from the hashed source snapshot")
    return source_max, source_digest, set(source_ids), output_groups


def _validate_phase_b_analysis_plan(
    plan: dict[str, Any],
    *,
    report: dict[str, Any],
    phase_a_source_digest: str,
) -> None:
    expected_top_level = {
        "schema_version": 1,
        "status": "frozen",
        "protocol_digest": report.get("protocol_digest"),
        "split_manifest_sha256": report.get("split_manifest_sha256"),
        "development_source_snapshot_sha256": phase_a_source_digest,
        "class_map_sha256": report.get("class_map_sha256"),
        "experiment_receipt_sha256": report.get("experiment_receipt_sha256"),
        "export_manifest_sha256": report.get("export_manifest_sha256"),
        "release_candidate": report.get("release_candidate"),
        "release_model_version": report.get("release_model_version"),
    }
    for field, expected in expected_top_level.items():
        if plan.get(field) != expected:
            raise ValueError(f"frozen analysis plan {field} differs from the release")
    if _attested_utc(
        plan.get("frozen_at_utc"), "analysis plan frozen_at_utc"
    ) != _attested_utc(report.get("protocol_frozen_at_utc"), "protocol_frozen_at_utc"):
        raise ValueError("frozen analysis plan timestamp differs from the attestation")

    cohort_policy = plan.get("cohort_policy")
    expected_cohort_policy = {
        "cohort_type": report.get("cohort_type"),
        "development_domain": report.get("development_domain"),
        "phase_b_domain": report.get("phase_b_domain"),
        "development_data_max_utc": report.get("development_data_max_utc"),
        "require_strictly_later": True,
        "require_same_domain": True,
        "unavailable_during_model_development": True,
        "unseen_until_protocol_freeze": True,
    }
    if not isinstance(cohort_policy, dict):
        raise TypeError("frozen analysis plan cohort_policy is missing")
    for field, expected in expected_cohort_policy.items():
        if cohort_policy.get(field) != expected:
            raise ValueError(
                f"frozen analysis plan cohort policy {field} is not locked"
            )

    evaluation_policy = plan.get("evaluation_policy")
    expected_evaluation_policy = {
        "access_policy": "single_access_after_freeze",
        "access_count": 1,
        "retuning_after_unseal": False,
        "primary_metric": "macro_f1",
        "class_count": len(TARGET_CLASSES),
        "probability_columns": [
            f"prob_{index}" for index in range(len(TARGET_CLASSES))
        ],
        "prediction_rule": "argmax_with_canonical_class_order_tie_break",
        "sample_unit": "sample_id",
    }
    if not isinstance(evaluation_policy, dict):
        raise TypeError("frozen analysis plan evaluation_policy is missing")
    for field, expected in expected_evaluation_policy.items():
        if evaluation_policy.get(field) != expected:
            raise ValueError(
                f"frozen analysis plan evaluation policy {field} is not locked"
            )


def _validate_phase_b_access_log(
    access_log: dict[str, Any],
    *,
    report: dict[str, Any],
) -> None:
    expected_log_fields = {
        "schema_version": 1,
        "access_count": 1,
        "cohort_manifest_sha256": report.get("cohort_manifest_sha256"),
        "cohort_membership_sha256": report.get("cohort_membership_sha256"),
        "analysis_plan_sha256": report.get("analysis_plan_sha256"),
    }
    for field, expected in expected_log_fields.items():
        if access_log.get(field) != expected:
            raise ValueError(f"Phase-B access log {field} differs from its evidence")
    events = access_log.get("access_events")
    if not isinstance(events, list) or len(events) != 1:
        raise ValueError("Phase-B access log must contain exactly one access event")
    event = events[0]
    if not isinstance(event, dict):
        raise TypeError("Phase-B access event must be an object")
    expected_event_fields = {
        "sequence": 1,
        "event_type": "phase_b_unseal_and_locked_evaluation_access",
        "access_scope": "one_shot_read_only",
        "protocol_digest": report.get("protocol_digest"),
        "release_candidate": report.get("release_candidate"),
        "release_model_version": report.get("release_model_version"),
    }
    for field, expected in expected_event_fields.items():
        if event.get(field) != expected:
            raise ValueError(f"Phase-B access event {field} is not the locked event")
    if not event.get("actor_role"):
        raise ValueError("Phase-B access event actor_role is missing")
    accessed_at = _attested_utc(event.get("accessed_at_utc"), "accessed_at_utc")
    unsealed_at = _attested_utc(
        report.get("phase_b_unsealed_at_utc"), "phase_b_unsealed_at_utc"
    )
    if accessed_at != unsealed_at:
        raise ValueError("Phase-B access time differs from the recorded unsealing")
    if accessed_at < _attested_utc(
        report.get("phase_b_cohort_end_utc"), "phase_b_cohort_end_utc"
    ) or accessed_at > _attested_utc(
        report.get("evaluated_at_utc"), "evaluated_at_utc"
    ):
        raise ValueError(
            "Phase-B access event falls outside the locked evaluation window"
        )


def _recompute_phase_b_predictions(
    report: dict[str, Any],
    report_path: Path,
    *,
    phase_a_split_manifest_path: Path,
) -> None:
    _validate_phase_b_later_cohort(report)
    if _sha256(phase_a_split_manifest_path) != report.get("split_manifest_sha256"):
        raise ValueError("Phase-B report is not bound to this Phase-A split manifest")
    records = {
        str(item.get("role")): item
        for item in report.get("evidence_files", [])
        if isinstance(item, dict) and item.get("role")
    }
    results_path = _phase_b_evidence_path(
        records,
        role="phase_b_per_sample_predictions",
        digest_field="phase_b_results_sha256",
        report=report,
        report_path=report_path,
    )
    cohort_path = _phase_b_evidence_path(
        records,
        role="phase_b_cohort_manifest",
        digest_field="cohort_manifest_sha256",
        report=report,
        report_path=report_path,
    )
    membership_path = _phase_b_evidence_path(
        records,
        role="phase_b_cohort_membership",
        digest_field="cohort_membership_sha256",
        report=report,
        report_path=report_path,
    )
    access_log_path = _phase_b_evidence_path(
        records,
        role="phase_b_access_log",
        digest_field="access_log_sha256",
        report=report,
        report_path=report_path,
    )
    analysis_plan_path = _phase_b_evidence_path(
        records,
        role="frozen_analysis_plan",
        digest_field="analysis_plan_sha256",
        report=report,
        report_path=report_path,
    )

    probability_columns = [f"prob_{index}" for index in range(len(TARGET_CLASSES))]
    with results_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"sample_id", "y_true", "y_pred", *probability_columns}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Phase-B predictions lack IDs, labels, or probabilities")
        rows = list(reader)
    if len(rows) != report.get("sample_size") or not rows:
        raise ValueError("Phase-B prediction rows differ from sample_size")
    ids = [str(row["sample_id"]) for row in rows]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Phase-B sample IDs must be non-empty and unique")
    ids_digest = _ordered_ids_sha256(ids)
    if ids_digest != report.get("phase_b_ordered_ids_sha256"):
        raise ValueError("Phase-B ordered sample-ID digest differs")

    cohort_manifest = _read_json(cohort_path)
    expected_manifest_fields = {
        "schema_version": 2,
        "cohort_type": report.get("cohort_type"),
        "development_domain": report.get("development_domain"),
        "phase_b_domain": report.get("phase_b_domain"),
        "development_data_max_utc": report.get("development_data_max_utc"),
        "phase_b_cohort_start_utc": report.get("phase_b_cohort_start_utc"),
        "phase_b_cohort_end_utc": report.get("phase_b_cohort_end_utc"),
        "sample_count": len(ids),
        "ordered_sample_ids_sha256": ids_digest,
        "cohort_membership_sha256": report.get("cohort_membership_sha256"),
        "phase_b_source_snapshot_sha256": report.get("phase_b_source_snapshot_sha256"),
        "source_row_digest_algorithm": "sha256_canonical_source_row_v1",
    }
    for field, expected in expected_manifest_fields.items():
        if cohort_manifest.get(field) != expected:
            raise ValueError(
                f"Phase-B cohort manifest {field} differs from the hashed evidence"
            )

    expected_membership_header = [
        "sample_id",
        "created_at_utc",
        "source_row_sha256",
        "source_snapshot_sha256",
    ]
    with membership_path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames not in (
            expected_membership_header,
            [*expected_membership_header, "leakage_group_id"],
        ):
            raise ValueError(
                "Phase-B membership header must be the canonical ordered lineage schema"
            )
        membership_rows = list(reader)
        has_membership_groups = "leakage_group_id" in reader.fieldnames
    if len(membership_rows) != len(ids):
        raise ValueError("Phase-B membership rows differ from prediction rows")
    membership_ids = [str(row["sample_id"]) for row in membership_rows]
    if membership_ids != ids:
        raise ValueError(
            "Phase-B membership IDs/order differ from the hashed predictions"
        )
    membership_timestamps = [
        _attested_utc(row["created_at_utc"], "Phase-B membership created_at_utc")
        for row in membership_rows
    ]
    observed_start = min(membership_timestamps)
    observed_end = max(membership_timestamps)
    if observed_start != _attested_utc(
        report.get("phase_b_cohort_start_utc"), "phase_b_cohort_start_utc"
    ) or observed_end != _attested_utc(
        report.get("phase_b_cohort_end_utc"), "phase_b_cohort_end_utc"
    ):
        raise ValueError(
            "Phase-B cohort start/end do not recompute from membership timestamps"
        )
    source_row_digests = [str(row["source_row_sha256"]) for row in membership_rows]
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", digest) for digest in source_row_digests
    ) or len(set(source_row_digests)) != len(source_row_digests):
        raise ValueError(
            "Phase-B membership source-row digests must be unique lowercase SHA-256"
        )
    expected_phase_b_source = report.get("phase_b_source_snapshot_sha256")
    membership_source_digests = {
        str(row["source_snapshot_sha256"]) for row in membership_rows
    }
    if membership_source_digests != {expected_phase_b_source}:
        raise ValueError(
            "Phase-B membership does not bind one declared source snapshot"
        )

    phase_a_max, phase_a_source_digest, phase_a_ids, phase_a_groups = (
        _phase_a_reference(phase_a_split_manifest_path)
    )
    if report.get("development_source_snapshot_sha256") != phase_a_source_digest:
        raise ValueError(
            "Phase-B development source digest differs from the frozen Phase-A source"
        )
    if (
        _attested_utc(
            report.get("development_data_max_utc"), "development_data_max_utc"
        )
        != phase_a_max
    ):
        raise ValueError(
            "Phase-B development maximum differs from the frozen Phase-A source maximum"
        )
    phase_a_id_overlap = sorted(set(ids).intersection(phase_a_ids))
    if phase_a_id_overlap:
        raise ValueError("Phase-B sample IDs overlap the Phase-A source snapshot")
    if has_membership_groups:
        membership_groups = [str(row["leakage_group_id"]) for row in membership_rows]
        if any(not group for group in membership_groups):
            raise ValueError("Phase-B membership contains an empty leakage group")
        if set(membership_groups).intersection(phase_a_groups):
            raise ValueError("Phase-B leakage groups overlap Phase-A split groups")

    _validate_phase_b_analysis_plan(
        _read_json(analysis_plan_path),
        report=report,
        phase_a_source_digest=phase_a_source_digest,
    )
    _validate_phase_b_access_log(_read_json(access_log_path), report=report)

    try:
        y_true = np.asarray([int(row["y_true"]) for row in rows], dtype=np.int64)
        y_pred = np.asarray([int(row["y_pred"]) for row in rows], dtype=np.int64)
        probabilities = np.asarray(
            [[float(row[column]) for column in probability_columns] for row in rows],
            dtype=np.float64,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Phase-B labels/probabilities are not numeric") from exc
    if (
        ((y_true < 0) | (y_true >= len(TARGET_CLASSES))).any()
        or ((y_pred < 0) | (y_pred >= len(TARGET_CLASSES))).any()
        or not np.isfinite(probabilities).all()
        or (probabilities < 0.0).any()
        or (probabilities > 1.0).any()
        or not np.allclose(probabilities.sum(axis=1), 1.0, rtol=0.0, atol=1e-6)
        or not np.array_equal(y_pred, probabilities.argmax(axis=1))
    ):
        raise ValueError("Phase-B labels/probabilities violate the class-map contract")
    observed_macro_f1 = float(
        f1_score(
            y_true,
            y_pred,
            labels=np.arange(len(TARGET_CLASSES)),
            average="macro",
            zero_division=0,
        )
    )
    declared = float(report.get("metrics", {}).get("macro_f1"))
    if not math.isclose(observed_macro_f1, declared, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError(
            "Phase-B macro_f1 does not recompute from hashed per-sample predictions"
        )


def _validate_usability(value: dict[str, Any]) -> None:
    if (
        int(value.get("standard_sus_items", 0)) != 10
        or int(value.get("participants", 0)) < 1
    ):
        raise ValueError("validated SUS-10 and positive participant count are required")
    if not {"citizen", "agency_operator"}.issubset(
        set(value.get("participant_groups", []))
    ):
        raise ValueError("citizen and agency_operator groups are required")
    metrics = value.get("task_metrics", {})
    for key in ("task_success", "error_rate", "correction_rate"):
        _proportion(metrics.get(key), key)
    _finite_number(metrics.get("completion_time"), "completion_time", low=0.0)
    if not value.get("completion_time_unit"):
        raise ValueError("completion_time_unit is missing")


def _validate_latency(value: dict[str, Any]) -> None:
    if int(value.get("sample_count", 0)) < 100 or not value.get("hardware"):
        raise ValueError("hardware and at least 100 samples are required")
    metrics = value.get("metrics", {})
    for key in ("cold_start", "p50", "p95", "p99", "throughput", "peak_memory"):
        _finite_number(metrics.get(key), key, low=0.0)
    if not isinstance(value.get("units"), dict) or not value.get("batch_size"):
        raise ValueError("latency units and batch_size are required")
    if int(value.get("warmup_runs", -1)) < 0:
        raise ValueError("warmup_runs must be non-negative")


def _validate_supabase_runtime_security(value: dict[str, Any]) -> None:
    for field in (
        "isolated_supabase_project",
        "attestation_worker_connected",
        "release_allowlist_enabled",
        "database_round_trip_completed",
        "trusted_upload_sanitizer_connected",
    ):
        if value.get(field) is not True:
            raise ValueError(f"{field} must be explicitly true")
    if value.get("credential_material_in_evidence") is not False:
        raise ValueError("runtime security evidence must not contain credentials")
    for field in ("test_runner", "supabase_version", "migration_bundle_sha256"):
        if not value.get(field):
            raise ValueError(f"runtime security {field} is missing")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value.get("migration_bundle_sha256", ""))):
        raise ValueError("migration_bundle_sha256 must be a lowercase SHA-256")

    required_principals = {
        "citizen_a",
        "citizen_b",
        "agency_bm",
        "agency_sda",
        "super_admin",
        "service_role_worker",
    }
    if not required_principals.issubset(set(value.get("test_principals", []))):
        raise ValueError("runtime security test principals are incomplete")
    required_checks = {
        "rls_read_isolation",
        "storage_owner_isolation",
        "trusted_upload_sanitization",
        "rpc_privilege_boundaries",
        "report_lifecycle",
        "release_allowlist",
        "probability_consistency",
        "review_gate_enforcement",
        "assignment_fail_closed",
        "confidence_precision_round_trip",
    }
    checks = value.get("checks")
    if not isinstance(checks, dict) or any(
        checks.get(check) is not True for check in required_checks
    ):
        raise ValueError("runtime security check matrix is incomplete or failed")
    counts = value.get("test_counts")
    if not isinstance(counts, dict):
        raise TypeError("runtime security test_counts must be an object")
    for field, minimum in (("positive", 9), ("negative", 18)):
        count = counts.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < minimum:
            raise ValueError(f"runtime security {field} test count is insufficient")
    if counts.get("failed") != 0:
        raise ValueError("runtime security tests contain failures")

    round_trip = value.get("confidence_round_trip")
    if not isinstance(round_trip, dict):
        raise TypeError("confidence_round_trip must be an object")
    supplied = _proportion(round_trip.get("supplied"), "supplied confidence")
    stored = _proportion(round_trip.get("stored"), "stored confidence")
    winning = _proportion(
        round_trip.get("stored_winning_probability"),
        "stored winning probability",
    )
    declared_error = _finite_number(
        round_trip.get("absolute_error"), "confidence round-trip error", low=0.0
    )
    observed_error = abs(stored - winning)
    if abs(supplied * 10_000 - round(supplied * 10_000)) <= 1e-9:
        raise ValueError("confidence round trip must exercise more than four decimals")
    if (
        observed_error > 1e-12
        or abs(declared_error - observed_error) > 1e-15
        or abs(supplied - stored) > 1e-12
    ):
        raise ValueError("confidence precision did not survive the database round trip")


def _validate_raw_pipeline_parity(value: dict[str, Any]) -> None:
    if value.get("raw_input_end_to_end") is not True:
        raise ValueError("raw image/text end-to-end parity was not executed")
    if int(value.get("sample_count", 0)) < 1:
        raise ValueError("raw pipeline parity sample_count must be positive")
    if not {"image", "text", "classifier"}.issubset(set(value.get("components", []))):
        raise ValueError("raw parity must cover image, text, and classifier components")
    metrics = value.get("metrics", {})
    max_error = _finite_number(
        metrics.get("max_absolute_probability_error"), "raw parity max error", low=0.0
    )
    top1_agreement = _proportion(
        metrics.get("top1_agreement"), "raw parity top1 agreement"
    )
    tolerances = value.get("frozen_tolerances")
    if not isinstance(tolerances, dict):
        raise TypeError("raw parity frozen_tolerances must be an object")
    if tolerances != RAW_PIPELINE_PARITY_TOLERANCES:
        raise ValueError(
            "raw parity tolerances differ from the exact frozen export policy"
        )
    max_error_tolerance = _finite_number(
        tolerances.get("max_absolute_probability_error"),
        "raw parity maximum tolerated error",
        low=0.0,
    )
    minimum_top1 = _proportion(
        tolerances.get("minimum_top1_agreement"),
        "raw parity minimum top1 agreement",
    )
    if value.get("tolerance_source") != "frozen_export_manifest":
        raise ValueError("raw parity tolerances are not frozen in the export manifest")
    if value.get("tolerance_manifest_sha256") != value.get("export_manifest_sha256"):
        raise ValueError("raw parity tolerance manifest does not match the release")
    if max_error > max_error_tolerance or top1_agreement < minimum_top1:
        raise ValueError("raw end-to-end parity metrics violate frozen tolerances")
    if value.get("passed") is not True:
        raise ValueError("raw end-to-end parity is not marked passed")


ATTESTATION_REQUIREMENTS: dict[str, Callable[[dict[str, Any]], None]] = {
    "governance_review": _validate_governance,
    "visual_privacy_review": _validate_visual_privacy,
    "routing_validation": _validate_routing,
    "external_validation": _validate_external,
    "phase_b_later_cohort_validation": _validate_phase_b_later_cohort,
    "usability_validation": _validate_usability,
    "latency_benchmark": _validate_latency,
    "supabase_runtime_security_validation": _validate_supabase_runtime_security,
    "end_to_end_raw_pipeline_parity": _validate_raw_pipeline_parity,
}


def _check_attestation(
    path: Path,
    evidence_type: str,
    *,
    expected_bindings: dict[str, str | None],
    expected_release: dict[str, str] | None = None,
    phase_a_split_manifest_path: Path | None = None,
) -> Gate:
    name, category = evidence_type, "external_evidence"
    if not path.is_file():
        return _failed(
            name, category, path, "independently reviewed attestation is missing"
        )
    try:
        report = _read_json(path)
        if (
            report.get("schema_version") != 1
            or report.get("evidence_type") != evidence_type
        ):
            raise ValueError("schema_version/evidence_type mismatch")
        if report.get("status") != "complete":
            raise ValueError("status is not complete")
        if not (
            report.get("reviewer_role")
            and report.get("reviewer_name_or_registry_id")
            and report.get("reviewer_affiliation")
            and report.get("reviewer_independent_of_model_selection") is True
        ):
            raise ValueError("reviewer identity/affiliation/independence is incomplete")
        reviewed_at = datetime.fromisoformat(
            str(report.get("reviewed_at_utc", "")).replace("Z", "+00:00")
        )
        if (
            reviewed_at.tzinfo is None
            or reviewed_at.utcoffset() != timezone.utc.utcoffset(reviewed_at)
        ):
            raise ValueError("reviewed_at_utc must be timezone-aware UTC")
        if reviewed_at > datetime.now(timezone.utc):
            raise ValueError("reviewed_at_utc cannot be in the future")
        for key, expected in expected_bindings.items():
            if not expected:
                raise ValueError(f"cannot establish expected {key} crosslink")
            if report.get(key) != expected:
                raise ValueError(f"attestation {key} differs from the evidence package")
        evidence_files = report.get("evidence_files")
        if not isinstance(evidence_files, list) or not evidence_files:
            raise ValueError("at least one hashed underlying evidence file is required")
        for record in evidence_files:
            ok, detail = _verify_artifact(record, path)
            if not ok:
                raise ValueError(f"underlying evidence: {detail}")
            evidence_path = _resolve_record_path(str(record["path"]), path)
            if evidence_path.resolve() == path.resolve():
                raise ValueError(
                    "an attestation cannot cite itself as underlying evidence"
                )
        ATTESTATION_REQUIREMENTS[evidence_type](report)
        if evidence_type == "phase_b_later_cohort_validation":
            if not expected_release or any(
                report.get(field) != expected
                for field, expected in expected_release.items()
            ):
                raise ValueError(
                    "Phase-B results differ from the externally anchored selected release"
                )
            if phase_a_split_manifest_path is None:
                raise ValueError("Phase-B gate lacks the frozen Phase-A split manifest")
            _recompute_phase_b_predictions(
                report,
                path,
                phase_a_split_manifest_path=phase_a_split_manifest_path,
            )
        return Gate(
            name,
            category,
            True,
            str(path),
            "schema-complete, hash-bound reviewer attestation; reviewer authenticity is not machine-verified",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return _failed(name, category, path, str(exc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--split-manifest",
        type=Path,
        default=ROOT / "artifacts/splits_q2/split_manifest.json",
    )
    parser.add_argument("--experiment-run", type=Path)
    parser.add_argument(
        "--label-audit",
        type=Path,
        default=ROOT / "artifacts/audits/label_audit_report.json",
    )
    parser.add_argument(
        "--privacy-audit",
        type=Path,
        default=ROOT / "artifacts/audits/privacy_aggregate.json",
    )
    parser.add_argument(
        "--classifier-parity",
        type=Path,
        default=ROOT / "artifacts/parity/classifier_report.json",
    )
    parser.add_argument("--encoder-parity", action="append", type=Path, default=[])
    parser.add_argument(
        "--export-dir",
        type=Path,
        default=ROOT / "artifacts/export",
        help="versioned receipt-bound export directory",
    )
    parser.add_argument(
        "--export-manifest-sha256",
        help="externally stored SHA-256 of export_manifest.json (never self-derived)",
    )
    parser.add_argument(
        "--attestation-dir", type=Path, default=ROOT / "artifacts/attestations"
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    gates = [
        _check_split_manifest(args.split_manifest),
        _check_experiment(args.experiment_run),
        _check_export_bundle(
            args.export_dir,
            args.export_manifest_sha256,
            args.experiment_run,
            args.classifier_parity,
            args.encoder_parity,
        ),
        _check_label_audit(args.label_audit),
        _check_privacy_screen(args.privacy_audit),
        _check_parity(
            args.classifier_parity,
            "classifier_onnx_parity",
            expected_component="classifier",
        ),
    ]
    if len(args.encoder_parity) < 2:
        gates.append(
            _failed(
                "image_and_text_encoder_tensor_parity",
                "deployment",
                None,
                "pass at least two --encoder-parity reports (image and text)",
            )
        )
    else:
        resolved_encoder_reports = {path.resolve() for path in args.encoder_parity}
        if len(resolved_encoder_reports) != len(args.encoder_parity):
            gates.append(
                _failed(
                    "image_and_text_encoder_tensor_parity",
                    "deployment",
                    None,
                    "encoder parity reports must be distinct files",
                )
            )
            encoder_gates = []
        else:
            encoder_reports: list[tuple[Path, str]] = []
            try:
                for path in args.encoder_parity:
                    component = str(_read_json(path).get("component", ""))
                    encoder_reports.append((path, component))
                components = [component for _, component in encoder_reports]
                if sorted(components) != ["image_encoder", "text_encoder"]:
                    raise ValueError(
                        "provide exactly one image_encoder and one text_encoder report"
                    )
                all_reports = [_read_json(args.classifier_parity)] + [
                    _read_json(path) for path, _ in encoder_reports
                ]
                if (
                    len({item.get("ordered_test_ids_sha256") for item in all_reports})
                    != 1
                ):
                    raise ValueError(
                        "parity reports use different ordered locked-test ID sets"
                    )
                if (
                    len({item.get("split_manifest_sha256") for item in all_reports})
                    != 1
                ):
                    raise ValueError("parity reports use different split manifests")
                encoder_gates = [
                    _check_parity(
                        path,
                        f"{component}_onnx_tensor_parity",
                        expected_component=component,
                    )
                    for path, component in encoder_reports
                ]
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                gates.append(
                    _failed(
                        "image_and_text_encoder_tensor_parity",
                        "deployment",
                        None,
                        str(exc),
                    )
                )
                encoder_gates = []
        if encoder_gates:
            gates.append(
                Gate(
                    "image_and_text_encoder_tensor_parity",
                    "deployment",
                    all(gate.passed for gate in encoder_gates),
                    ", ".join(str(path) for path in args.encoder_parity),
                    "; ".join(gate.detail for gate in encoder_gates),
                )
            )
    gates.append(
        _check_evidence_crosslinks(
            split_manifest_path=args.split_manifest,
            experiment_run=args.experiment_run,
            classifier_parity_path=args.classifier_parity,
            encoder_parity_paths=args.encoder_parity,
        )
    )
    expected_bindings: dict[str, str | None] = {
        "split_manifest_sha256": None,
        "class_map_sha256": None,
        "protocol_digest": None,
        "experiment_receipt_sha256": None,
        "ordered_test_ids_sha256": None,
        "export_manifest_sha256": None,
    }
    expected_release: dict[str, str] | None = None
    try:
        split_value = _read_json(args.split_manifest)
        expected_bindings["split_manifest_sha256"] = _sha256(args.split_manifest)
        expected_bindings["class_map_sha256"] = split_value.get("class_map", {}).get(
            "sha256"
        )
        classifier_value = _read_json(args.classifier_parity)
        expected_bindings["ordered_test_ids_sha256"] = classifier_value.get(
            "ordered_test_ids_sha256"
        )
        if args.export_manifest_sha256:
            # This is deliberately the operator/custodian-provided trust anchor,
            # not a digest silently calculated from the local manifest.
            expected_bindings["export_manifest_sha256"] = (
                args.export_manifest_sha256.lower()
            )
            export_manifest_path = args.export_dir.resolve() / "export_manifest.json"
            if _sha256(export_manifest_path) == args.export_manifest_sha256.lower():
                export_manifest = _read_json(export_manifest_path)
                expected_release = {
                    "release_candidate": str(
                        export_manifest.get("model", {}).get("candidate", "")
                    ),
                    "release_model_version": str(
                        export_manifest.get("model", {}).get("version", "")
                    ),
                }
        if args.experiment_run is not None:
            final_receipt_path = (
                args.experiment_run.resolve() / "test" / "TEST_EVALUATION_COMPLETE.json"
            )
            final_value = _read_json(final_receipt_path)
            expected_bindings["protocol_digest"] = final_value.get("protocol_digest")
            expected_bindings["experiment_receipt_sha256"] = _sha256(final_receipt_path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # The individual gates report the concrete missing/malformed file.  The
        # attestation gates fail closed because one or more crosslinks stay null.
        pass
    for evidence_type in ATTESTATION_REQUIREMENTS:
        gates.append(
            _check_attestation(
                args.attestation_dir / f"{evidence_type}.json",
                evidence_type,
                expected_bindings=expected_bindings,
                expected_release=expected_release,
                phase_a_split_manifest_path=args.split_manifest,
            )
        )

    ready = all(gate.passed for gate in gates)
    payload = {
        "schema_version": 1,
        "schema_complete_for_q2_evidence_review": ready,
        "passed": sum(gate.passed for gate in gates),
        "total": len(gates),
        "gates": [asdict(gate) for gate in gates],
        "disclaimer": (
            "Passing verifies schema, hashes, and crosslinks in the declared package; "
            "it does not authenticate reviewers, independently validate evidence, or "
            "predict journal acceptance."
        ),
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    return 0 if ready else 2


if __name__ == "__main__":
    sys.exit(main())
