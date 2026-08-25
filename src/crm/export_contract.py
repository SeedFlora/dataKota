"""Immutable, fail-closed contract for deployable Q2 model bundles.

The manifest is intentionally independent of the serving application.  It can
be checked after an upload/download and before ONNX Runtime or Transformers
opens any model file.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from crm.deployment import EPISTEMIC_MI_METHOD
from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
    validate_preprocessing_contract,
)

EXPORT_SCHEMA_VERSION = 4
EXPORT_KIND = "crm_q2_receipt_bound_export"
MANIFEST_FILENAME = "export_manifest.json"
RAW_PIPELINE_PARITY_TOLERANCES = {
    "max_absolute_probability_error": 1e-5,
    "minimum_top1_agreement": 1.0,
}
ENCODER_TENSOR_PARITY_TOLERANCES = {
    "absolute_tolerance": 1e-5,
    "minimum_cosine_similarity": 0.99999,
}
CLASSIFIER_PARITY_TOLERANCES = {
    "probability_tolerance": 1e-5,
    "minimum_top1_agreement": 1.0,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")


class ExportContractError(RuntimeError):
    """Raised when a deployable bundle cannot prove its identity/integrity."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def object_sha256(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, *, root: Path, role: str) -> dict[str, Any]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ExportContractError(f"artifact escapes export root: {path}") from exc
    if not path.is_file() or path.is_symlink():
        raise ExportContractError(
            f"artifact must be a regular, non-symlink file: {path}"
        )
    return {
        "role": role,
        "path": relative,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def artifact_tree_sha256(artifacts: Iterable[Mapping[str, Any]], *, prefix: str) -> str:
    normalized_prefix = prefix.rstrip("/") + "/"
    rows = [
        {
            "path": str(item["path"])[len(normalized_prefix) :],
            "size_bytes": int(item["size_bytes"]),
            "sha256": str(item["sha256"]),
        }
        for item in artifacts
        if str(item.get("path", "")).startswith(normalized_prefix)
    ]
    if not rows:
        raise ExportContractError(f"artifact tree {prefix!r} is empty")
    rows.sort(key=lambda row: row["path"])
    return object_sha256(rows)


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    return object_sha256(payload)


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.lower()):
        raise ExportContractError(f"{field} must be a 64-character SHA-256 digest")
    return value.lower()


def _safe_artifact_path(root: Path, stored: Any) -> Path:
    if not isinstance(stored, str) or not stored:
        raise ExportContractError("artifact path must be a non-empty relative string")
    relative = Path(stored)
    if relative.is_absolute():
        raise ExportContractError(f"absolute artifact path is forbidden: {stored}")
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ExportContractError(
            f"artifact path escapes export root: {stored}"
        ) from exc
    return resolved


def _validate_class_map(
    raw: Any, expected_classes: Sequence[str] | None
) -> tuple[str, ...]:
    if not isinstance(raw, Mapping):
        raise ExportContractError("class_map must be an object")
    classes = raw.get("classes")
    if not isinstance(classes, list) or not classes:
        raise ExportContractError("class_map.classes must be a non-empty list")
    labels: list[str] = []
    semantic_rows: list[dict[str, Any]] = []
    for index, item in enumerate(classes):
        if not isinstance(item, Mapping):
            raise ExportContractError(f"class_map.classes[{index}] must be an object")
        if item.get("label_id") != index:
            raise ExportContractError(
                "class ids must be contiguous and ordered from zero"
            )
        label = item.get("label_name")
        if not isinstance(label, str) or not label.strip() or label != label.strip():
            raise ExportContractError(
                f"class_map.classes[{index}].label_name is invalid"
            )
        labels.append(label)
        semantic_rows.append({"label_id": index, "label_name": label})
    semantic_hash = _require_sha256(
        raw.get("semantic_sha256"), "class_map.semantic_sha256"
    )
    if object_sha256(semantic_rows) != semantic_hash:
        raise ExportContractError("class-map semantic digest mismatch")
    if expected_classes is not None and tuple(expected_classes) != tuple(labels):
        raise ExportContractError(
            "export class map differs from the serving code contract; refusing "
            "to reinterpret classifier columns"
        )
    return tuple(labels)


def validate_export_manifest(
    export_dir: str | Path,
    *,
    expected_manifest_sha256: str | None,
    expected_classes: Sequence[str] | None = None,
    expected_model_version: str | None = None,
) -> dict[str, Any]:
    """Validate a complete export bundle and return its parsed manifest.

    ``expected_manifest_sha256`` is a deployment trust anchor.  It is required;
    an internal digest alone detects accidental edits but cannot authenticate a
    substituted manifest and substituted model together.
    """
    root = Path(export_dir).resolve()
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ExportContractError(f"missing regular {MANIFEST_FILENAME} in {root}")
    expected_hash = _require_sha256(
        expected_manifest_sha256, "expected_manifest_sha256"
    )
    observed_hash = sha256_file(manifest_path)
    if observed_hash != expected_hash:
        raise ExportContractError(
            f"export manifest hash mismatch: expected {expected_hash}, got {observed_hash}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ExportContractError("export manifest is not valid UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise ExportContractError("export manifest must be a JSON object")
    if manifest.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise ExportContractError("unsupported export manifest schema version")
    if manifest.get("kind") != EXPORT_KIND:
        raise ExportContractError("unexpected export manifest kind")
    stored_digest = _require_sha256(
        manifest.get("manifest_digest"), "manifest.manifest_digest"
    )
    if manifest_digest(manifest) != stored_digest:
        raise ExportContractError("export manifest semantic digest mismatch")

    model = manifest.get("model")
    if not isinstance(model, Mapping):
        raise ExportContractError("manifest.model must be an object")
    for field in ("name", "version", "candidate"):
        if not isinstance(model.get(field), str) or not model[field].strip():
            raise ExportContractError(f"manifest.model.{field} must be non-empty")
    if model["version"].strip().lower() == "unversioned":
        raise ExportContractError("unversioned model bundles are forbidden")
    if (
        expected_model_version is not None
        and model["version"] != expected_model_version
    ):
        raise ExportContractError(
            f"model version mismatch: expected {expected_model_version!r}, "
            f"got {model['version']!r}"
        )
    seeds = model.get("seeds")
    if (
        not isinstance(seeds, list)
        or len(seeds) < 5
        or any(type(seed) is not int for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ExportContractError(
            "manifest.model.seeds must contain at least five distinct integers"
        )
    if model.get("ensemble_size") != len(seeds):
        raise ExportContractError("model.ensemble_size differs from model.seeds")
    if model.get("probability_aggregation") != "equal_weight_arithmetic_mean":
        raise ExportContractError(
            "deployment must use an equal-weight arithmetic probability mean"
        )
    if model.get("checkpoint_tree_policy") != (
        "full_early_stopped_trajectory_for_both_point_and_pgs"
    ):
        raise ExportContractError(
            "model checkpoint policy must retain the full matched point/PGS "
            "early-stopped trajectory"
        )
    if (
        type(model.get("classifier_feature_count")) is not int
        or model["classifier_feature_count"] < 1
    ):
        raise ExportContractError(
            "manifest.model.classifier_feature_count must be positive"
        )
    posterior_sampling = model.get("training_posterior_sampling")
    if type(posterior_sampling) is not bool:
        raise ExportContractError("model.training_posterior_sampling must be boolean")
    expected_method = (
        "catboost_virtual_ensemble_seed_ensemble"
        if posterior_sampling
        else "onnx_equal_weight_seed_ensemble"
    )
    if model.get("default_inference_method") != expected_method:
        raise ExportContractError(
            "default inference method does not reproduce the evaluated seed ensemble"
        )

    labels = _validate_class_map(manifest.get("class_map"), expected_classes)
    if model.get("class_count") != len(labels):
        raise ExportContractError("model.class_count differs from the class map")

    calibration = manifest.get("calibration")
    expected_calibration = {
        "family": "identity_no_posthoc_calibration",
        "fitting_objective": "not_applicable_identity",
        "probability_scope": "equal_weight_seed_ensemble_probabilities",
        "claim": "uncalibrated_probabilities",
    }
    if not isinstance(calibration, Mapping) or any(
        calibration.get(field) != expected
        for field, expected in expected_calibration.items()
    ):
        raise ExportContractError(
            "manifest.calibration must bind the preregistered identity/no-claim "
            "probability protocol"
        )
    ece = calibration.get("ece")
    if (
        not isinstance(ece, Mapping)
        or ece.get("family") != "top_label"
        or ece.get("binning") != "equal_width_0_1"
        or type(ece.get("bins")) is not int
        or ece["bins"] < 2
        or ece.get("bin_interval_semantics") != "left_closed_right_open_final_closed"
    ):
        raise ExportContractError("manifest.calibration.ece semantics are incomplete")

    review_policy = manifest.get("review_policy")
    expected_unconditional = ["Instansi lain"] if "Instansi lain" in labels else []
    expected_routable = [label for label in labels if label != "Instansi lain"]
    if (
        not isinstance(review_policy, Mapping)
        or review_policy.get("candidate") != model["candidate"]
        or review_policy.get("threshold_source") != "validation_seed_ensemble"
        or review_policy.get("selection_split") != "validation"
        or review_policy.get("operating_criterion")
        != "fixed_target_joint_validation_coverage_on_predicted_routable_labels"
        or review_policy.get("target_population") != "predicted_routable_labels_only"
        or review_policy.get("policy_scope")
        != "model_review_gates_plus_unconditional_labels_excluding_registry"
        or review_policy.get("tie_policy") != "include_all_at_boundary"
        or review_policy.get("unconditionally_reviewed_labels")
        != expected_unconditional
        or review_policy.get("routable_labels") != expected_routable
    ):
        raise ExportContractError(
            "manifest.review_policy must be validation-frozen and exclude catch-all "
            "labels from automatic routing"
        )
    target_coverage = review_policy.get("target_coverage")
    marginal_quantile = review_policy.get("marginal_quantile_coverage")
    validation_joint_coverage = review_policy.get("validation_joint_realized_coverage")
    validation_overall_coverage = review_policy.get(
        "validation_joint_overall_realized_coverage"
    )
    validation_joint_risk = review_policy.get("validation_joint_selective_risk")
    target_population_count = review_policy.get("validation_target_population_count")
    unconditional_count = review_policy.get("validation_unconditionally_reviewed_count")
    minimum_confidence = review_policy.get("minimum_confidence")
    maximum_one_minus = review_policy.get("maximum_one_minus_confidence")
    if (
        not isinstance(target_coverage, (int, float))
        or isinstance(target_coverage, bool)
        or not isfinite(target_coverage)
        or not 0.0 < target_coverage <= 1.0
        or not isinstance(marginal_quantile, (int, float))
        or isinstance(marginal_quantile, bool)
        or not isfinite(marginal_quantile)
        or not target_coverage <= marginal_quantile <= 1.0
        or not isinstance(validation_joint_coverage, (int, float))
        or isinstance(validation_joint_coverage, bool)
        or not isfinite(validation_joint_coverage)
        or not target_coverage <= validation_joint_coverage <= 1.0
        or not isinstance(validation_overall_coverage, (int, float))
        or isinstance(validation_overall_coverage, bool)
        or not isfinite(validation_overall_coverage)
        or not 0.0 <= validation_overall_coverage <= validation_joint_coverage
        or not isinstance(validation_joint_risk, (int, float))
        or isinstance(validation_joint_risk, bool)
        or not isfinite(validation_joint_risk)
        or not 0.0 <= validation_joint_risk <= 1.0
        or not isinstance(minimum_confidence, (int, float))
        or isinstance(minimum_confidence, bool)
        or not isfinite(minimum_confidence)
        or not 0.0 <= minimum_confidence <= 1.0
        or not isinstance(maximum_one_minus, (int, float))
        or isinstance(maximum_one_minus, bool)
        or not isfinite(maximum_one_minus)
        or not 0.0 <= maximum_one_minus <= 1.0
        or abs(minimum_confidence + maximum_one_minus - 1.0) > 1e-9
        or type(target_population_count) is not int
        or target_population_count < 1
        or type(unconditional_count) is not int
        or unconditional_count < 0
    ):
        raise ExportContractError(
            "manifest.review_policy confidence threshold is invalid"
        )
    epistemic_threshold = review_policy.get("maximum_epistemic_mutual_information")
    epistemic_fields = {
        "semantics": review_policy.get("epistemic_uncertainty_semantics"),
        "axis": review_policy.get("epistemic_component_axis"),
        "component_count": review_policy.get("epistemic_component_count"),
        "seed_count": review_policy.get("epistemic_training_seed_count"),
        "virtual_per_seed": review_policy.get("epistemic_virtual_ensembles_per_seed"),
    }
    if posterior_sampling:
        if (
            not isinstance(epistemic_threshold, (int, float))
            or isinstance(epistemic_threshold, bool)
            or not isfinite(epistemic_threshold)
            or epistemic_threshold < 0.0
            or epistemic_fields["semantics"] != EPISTEMIC_MI_METHOD
            or epistemic_fields["axis"] != "training_seed_x_pgs_virtual_member"
            or epistemic_fields["seed_count"] != len(seeds)
            or type(epistemic_fields["virtual_per_seed"]) is not int
            or epistemic_fields["virtual_per_seed"] < 2
            or epistemic_fields["component_count"]
            != len(seeds) * epistemic_fields["virtual_per_seed"]
        ):
            raise ExportContractError(
                "PGS exports require a validation-frozen joint training-seed + "
                "virtual-member epistemic uncertainty contract"
            )
    elif epistemic_threshold is not None or any(
        value is not None for value in epistemic_fields.values()
    ):
        raise ExportContractError(
            "point exports must not declare epistemic uncertainty metadata"
        )

    protocol = manifest.get("protocol")
    if not isinstance(protocol, Mapping):
        raise ExportContractError("manifest.protocol must be an object")
    if protocol.get("export_policy") not in {
        "selection_complete",
        "locked_test_complete",
    }:
        raise ExportContractError("unsupported protocol export policy")
    if protocol.get("deployment_seed_rule") != "all_preregistered_seeds_equal_weight":
        raise ExportContractError("unsupported or missing deployment-seed rule")
    eligible_candidates = protocol.get("deployment_eligible_candidates")
    if (
        not isinstance(eligible_candidates, list)
        or not eligible_candidates
        or any(
            not isinstance(candidate, str) or not candidate.strip()
            for candidate in eligible_candidates
        )
        or len(set(eligible_candidates)) != len(eligible_candidates)
        or model["candidate"] not in eligible_candidates
    ):
        raise ExportContractError(
            "protocol.deployment_eligible_candidates must bind a unique "
            "preregistered set containing the selected model"
        )
    selection_eligibility_rule = protocol.get("selection_eligibility_rule")
    if (
        not isinstance(selection_eligibility_rule, str)
        or "protocol.deployment_eligible_candidates" not in selection_eligibility_rule
        or "secondary baselines or ablations" not in selection_eligibility_rule
    ):
        raise ExportContractError(
            "protocol.selection_eligibility_rule does not distinguish the primary "
            "deployable family from secondary baselines"
        )
    for field in (
        "protocol_digest",
        "input_manifest_digest",
        "selection_receipt_digest",
        "source_class_map_sha256",
    ):
        _require_sha256(protocol.get(field), f"manifest.protocol.{field}")
    if protocol["export_policy"] == "locked_test_complete":
        _require_sha256(
            protocol.get("locked_test_receipt_digest"),
            "manifest.protocol.locked_test_receipt_digest",
        )
    virtual_ensembles = protocol.get("virtual_ensembles_per_seed")
    if posterior_sampling:
        if type(virtual_ensembles) is not int or virtual_ensembles < 2:
            raise ExportContractError(
                "posterior seed ensembles require a frozen virtual-ensemble count"
            )
        if virtual_ensembles != epistemic_fields["virtual_per_seed"]:
            raise ExportContractError(
                "protocol virtual-ensemble count differs from review-policy "
                "epistemic semantics"
            )
    elif virtual_ensembles is not None:
        raise ExportContractError(
            "point seed ensembles must not declare virtual ensembles"
        )
    source_members = protocol.get("source_members")
    if not isinstance(source_members, list) or len(source_members) != len(seeds):
        raise ExportContractError(
            "protocol.source_members must bind every preregistered seed"
        )
    if [
        item.get("seed") for item in source_members if isinstance(item, Mapping)
    ] != seeds:
        raise ExportContractError(
            "protocol.source_members must follow the frozen model seed order"
        )
    for index, member in enumerate(source_members):
        if not isinstance(member, Mapping):
            raise ExportContractError(f"protocol.source_members[{index}] is invalid")
        _require_sha256(
            member.get("checkpoint_sha256"),
            f"protocol.source_members[{index}].checkpoint_sha256",
        )
        _require_sha256(
            member.get("unit_receipt_sha256"),
            f"protocol.source_members[{index}].unit_receipt_sha256",
        )
        if type(member.get("tree_count")) is not int or member["tree_count"] < 1:
            raise ExportContractError(
                f"protocol.source_members[{index}].tree_count must be positive"
            )

    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ExportContractError("manifest.artifacts must be a non-empty list")
    by_path: dict[str, Mapping[str, Any]] = {}
    roles: dict[str, list[str]] = {}
    for index, record in enumerate(artifacts):
        if not isinstance(record, Mapping):
            raise ExportContractError(f"artifacts[{index}] must be an object")
        stored = record.get("path")
        path = _safe_artifact_path(root, stored)
        if stored in by_path:
            raise ExportContractError(f"duplicate artifact path: {stored}")
        by_path[str(stored)] = record
        role = record.get("role")
        if not isinstance(role, str) or not role:
            raise ExportContractError(f"artifacts[{index}].role must be non-empty")
        roles.setdefault(role, []).append(str(stored))
        expected_size = record.get("size_bytes")
        if type(expected_size) is not int or expected_size < 1:
            raise ExportContractError(f"artifact {stored} has an invalid size")
        expected_artifact_hash = _require_sha256(
            record.get("sha256"), f"artifact {stored}.sha256"
        )
        if not path.is_file() or path.is_symlink():
            raise ExportContractError(
                f"manifested artifact is missing/not regular: {stored}"
            )
        if path.stat().st_size != expected_size:
            raise ExportContractError(f"manifested artifact size changed: {stored}")
        if sha256_file(path) != expected_artifact_hash:
            raise ExportContractError(f"manifested artifact hash changed: {stored}")

    runtime = manifest.get("runtime")
    if not isinstance(runtime, Mapping):
        raise ExportContractError("manifest.runtime must be an object")
    required_runtime_roles = {
        "image_model": "image_encoder_onnx",
        "image_preprocessor": "image_preprocessor",
        "text_model": "text_encoder_onnx",
    }
    for field, role in required_runtime_roles.items():
        stored = runtime.get(field)
        if not isinstance(stored, str) or stored not in by_path:
            raise ExportContractError(f"runtime.{field} is not a manifested artifact")
        if by_path[stored].get("role") != role:
            raise ExportContractError(f"runtime.{field} has the wrong artifact role")
        if len(roles.get(role, [])) != 1:
            raise ExportContractError(f"artifact role {role!r} must occur exactly once")
    classifier_members = runtime.get("classifier_members")
    if not isinstance(classifier_members, list) or len(classifier_members) != len(
        seeds
    ):
        raise ExportContractError(
            "runtime.classifier_members must contain every seed-ensemble head"
        )
    if len(roles.get("classifier_onnx", [])) != len(seeds) or len(
        roles.get("classifier_native", [])
    ) != len(seeds):
        raise ExportContractError(
            "classifier artifact roles must occur once per seed-ensemble head"
        )
    source_by_seed = {int(item["seed"]): item for item in source_members}
    observed_member_seeds: list[int] = []
    for index, member in enumerate(classifier_members):
        if not isinstance(member, Mapping):
            raise ExportContractError(f"runtime.classifier_members[{index}] is invalid")
        seed = member.get("seed")
        if type(seed) is not int:
            raise ExportContractError(
                f"runtime.classifier_members[{index}].seed must be an integer"
            )
        observed_member_seeds.append(seed)
        if (
            type(member.get("tree_count")) is not int
            or member["tree_count"] < 1
            or member["tree_count"] != source_by_seed.get(seed, {}).get("tree_count")
        ):
            raise ExportContractError(
                f"runtime classifier seed {seed} tree count differs from its "
                "selection receipt"
            )
        for field, role in (
            ("onnx", "classifier_onnx"),
            ("native", "classifier_native"),
        ):
            stored = member.get(field)
            if not isinstance(stored, str) or stored not in by_path:
                raise ExportContractError(
                    f"runtime.classifier_members[{index}].{field} is not manifested"
                )
            if by_path[stored].get("role") != role:
                raise ExportContractError(
                    f"runtime.classifier_members[{index}].{field} has the wrong role"
                )
        if by_path[member["native"]]["sha256"] != source_by_seed.get(seed, {}).get(
            "checkpoint_sha256"
        ):
            raise ExportContractError(
                f"native classifier for seed {seed} differs from its frozen checkpoint"
            )
    if observed_member_seeds != seeds:
        raise ExportContractError(
            "runtime classifier members must follow the frozen model seed order"
        )
    tokenizer_dir = runtime.get("text_tokenizer_dir")
    if not isinstance(tokenizer_dir, str) or not tokenizer_dir.strip():
        raise ExportContractError("runtime.text_tokenizer_dir must be non-empty")
    tokenizer_prefix = tokenizer_dir.rstrip("/") + "/"
    if not any(path.startswith(tokenizer_prefix) for path in by_path):
        raise ExportContractError("text tokenizer directory has no manifested files")
    for runtime_directory in (
        "classifiers",
        "image_encoder",
        tokenizer_dir.rstrip("/"),
    ):
        directory = _safe_artifact_path(root, runtime_directory)
        if not directory.is_dir() or directory.is_symlink():
            raise ExportContractError(
                f"runtime artifact directory is missing/not regular: {runtime_directory}"
            )
        actual_files: set[str] = set()
        for item in directory.rglob("*"):
            if item.is_symlink():
                raise ExportContractError(
                    f"runtime artifact symlink is forbidden: {item}"
                )
            if item.is_file():
                actual_files.add(item.relative_to(root).as_posix())
        manifested_files = {
            path
            for path in by_path
            if path.startswith(runtime_directory.rstrip("/") + "/")
        }
        unexpected = sorted(actual_files.difference(manifested_files))
        if unexpected:
            raise ExportContractError(
                f"unmanifested runtime artifacts are forbidden: {unexpected}"
            )
    if runtime.get("text_pooling") not in {"cls", "e5_avg"}:
        raise ExportContractError("runtime.text_pooling is unsupported")
    if not isinstance(runtime.get("text_prefix"), str):
        raise ExportContractError("runtime.text_prefix must be a string")
    if (
        type(runtime.get("text_max_length")) is not int
        or runtime["text_max_length"] < 1
    ):
        raise ExportContractError("runtime.text_max_length must be positive")

    expected_fusion = {
        "operation": "concatenate",
        "modality_order": ["image", "text"],
        "axis": 1,
        "l2_per_modality": True,
        "l2_epsilon": 1e-9,
        "output_dtype": "float32",
    }
    if manifest.get("feature_fusion") != expected_fusion:
        raise ExportContractError(
            "manifest.feature_fusion must reproduce the frozen image-then-text "
            "per-modality L2 concatenation"
        )
    expected_parity_tolerances = {
        "encoder_tensor_boundary": ENCODER_TENSOR_PARITY_TOLERANCES,
        "classifier_native_onnx": CLASSIFIER_PARITY_TOLERANCES,
        "raw_input_end_to_end": RAW_PIPELINE_PARITY_TOLERANCES,
    }
    if manifest.get("parity_tolerances") != expected_parity_tolerances:
        raise ExportContractError(
            "manifest parity tolerances must equal the complete frozen safe policy"
        )

    encoders = manifest.get("encoders")
    if not isinstance(encoders, Mapping):
        raise ExportContractError("manifest.encoders must be an object")
    encoder_dimensions: dict[str, int] = {}
    for modality, prefix in (("image", "image_encoder"), ("text", "text_encoder")):
        encoder = encoders.get(modality)
        if not isinstance(encoder, Mapping):
            raise ExportContractError(f"manifest.encoders.{modality} must be an object")
        for field in ("name", "repository"):
            if not isinstance(encoder.get(field), str) or not encoder[field].strip():
                raise ExportContractError(f"encoders.{modality}.{field} is invalid")
        revision = encoder.get("revision")
        if not isinstance(revision, str) or not _REVISION_RE.fullmatch(
            revision.lower()
        ):
            raise ExportContractError(
                f"encoders.{modality}.revision must be an immutable 40-64 hex commit"
            )
        _require_sha256(
            encoder.get("extraction_receipt_sha256"),
            f"encoders.{modality}.extraction_receipt_sha256",
        )
        _require_sha256(
            encoder.get("embedding_sha256"),
            f"encoders.{modality}.embedding_sha256",
        )
        extraction_commit = encoder.get("extraction_code_commit")
        if not isinstance(extraction_commit, str) or not _REVISION_RE.fullmatch(
            extraction_commit.lower()
        ):
            raise ExportContractError(
                f"encoders.{modality}.extraction_code_commit must be immutable"
            )
        if (
            not isinstance(encoder.get("pooling"), str)
            or not encoder["pooling"].strip()
        ):
            raise ExportContractError(f"encoders.{modality}.pooling must be explicit")
        if modality == "text":
            if not isinstance(encoder.get("prefix"), str):
                raise ExportContractError("text encoder prefix must be explicit")
            if type(encoder.get("max_length")) is not int or encoder["max_length"] < 1:
                raise ExportContractError("text encoder max_length must be positive")
        elif encoder.get("prefix") is not None or encoder.get("max_length") is not None:
            raise ExportContractError("image encoder prefix/max_length must be null")
        preprocessing = encoder.get("preprocessing")
        try:
            validate_preprocessing_contract(
                preprocessing,
                modality=modality,
                pooling=encoder["pooling"],
                prefix=encoder.get("prefix"),
                max_length=encoder.get("max_length"),
                output_dtype=encoder.get("dtype"),
            )
        except PreprocessingContractError as exc:
            raise ExportContractError(
                f"encoders.{modality}.preprocessing: {exc}"
            ) from exc
        expected_preprocessing_hash = _require_sha256(
            encoder.get("preprocessing_sha256"),
            f"encoders.{modality}.preprocessing_sha256",
        )
        if preprocessing_sha256(preprocessing) != expected_preprocessing_hash:
            raise ExportContractError(
                f"encoders.{modality}.preprocessing semantic digest mismatch"
            )
        declared_assets = {
            str(item["path"]): str(item["sha256"])
            for item in preprocessing["implementation"]["assets"]
        }
        bundled_assets = {
            path[len(prefix) + 1 :]: record
            for path, record in by_path.items()
            if path.startswith(prefix + "/")
        }
        model_files = {"model.onnx", "model.onnx_data", "model.onnx.data"}
        undeclared_assets = sorted(
            set(bundled_assets).difference(declared_assets).difference(model_files)
        )
        missing_assets = sorted(set(declared_assets).difference(bundled_assets))
        if undeclared_assets or missing_assets:
            raise ExportContractError(
                f"encoders.{modality} preprocessing assets differ from the bundle; "
                f"missing={missing_assets}, undeclared={undeclared_assets}"
            )
        for relative, expected_hash in declared_assets.items():
            if bundled_assets[relative].get("sha256") != expected_hash:
                raise ExportContractError(
                    f"encoders.{modality} preprocessing asset hash differs: {relative}"
                )
        dimension = encoder.get("dimension")
        if type(dimension) is not int or dimension < 1:
            raise ExportContractError(f"encoders.{modality}.dimension must be positive")
        if encoder.get("dtype") not in {"float16", "float32", "float64"}:
            raise ExportContractError(
                f"encoders.{modality}.dtype must be an explicit floating dtype"
            )
        encoder_dimensions[modality] = dimension
        expected_tree = _require_sha256(
            encoder.get("artifact_tree_sha256"),
            f"encoders.{modality}.artifact_tree_sha256",
        )
        if artifact_tree_sha256(artifacts, prefix=prefix) != expected_tree:
            raise ExportContractError(
                f"{modality} encoder artifact-tree digest mismatch"
            )
    if sum(encoder_dimensions.values()) != model["classifier_feature_count"]:
        raise ExportContractError(
            "encoder dimensions do not sum to model.classifier_feature_count"
        )
    return manifest
