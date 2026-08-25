#!/usr/bin/env python3
"""Export every head of a receipt-bound Q2 seed ensemble.

This is the only receipt-bound selected-model deployment exporter. The historical notebook
export is retained for exploration, but it does not validate selection/test
receipts and must not be used for a paper/deployment claim.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm import TARGET_CLASSES
from crm.experiments.artifacts import (
    object_sha256 as experiment_object_sha256,
)
from crm.experiments.artifacts import (
    read_json,
    resolve_artifact_path,
)
from crm.experiments.config import load_resolved_config
from crm.experiments.data import sha256_file, verify_input_manifest
from crm.experiments.runner import _verify_selection_receipt, _verify_unit_index
from crm.export_contract import (
    CLASSIFIER_PARITY_TOLERANCES,
    ENCODER_TENSOR_PARITY_TOLERANCES,
    EXPORT_KIND,
    EXPORT_SCHEMA_VERSION,
    MANIFEST_FILENAME,
    RAW_PIPELINE_PARITY_TOLERANCES,
    ExportContractError,
    artifact_record,
    artifact_tree_sha256,
    manifest_digest,
    object_sha256,
    validate_export_manifest,
)
from crm.export_contract import sha256_file as export_sha256_file
from crm.pgs import validate_pgs_model
from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
    validate_preprocessing_contract,
)


class ExportError(RuntimeError):
    """Raised when a run or source artifact is not eligible for export."""


def _receipt_without_digest(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    value.pop("receipt_digest", None)
    return value


def _verify_receipt(path: Path, expected_phase: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExportError(f"required receipt is missing: {path}")
    receipt = read_json(path)
    if not isinstance(receipt, dict) or receipt.get("phase") != expected_phase:
        raise ExportError(f"unexpected receipt phase in {path}")
    stored = receipt.get("receipt_digest")
    if stored != experiment_object_sha256(_receipt_without_digest(receipt)):
        raise ExportError(f"receipt digest mismatch: {path}")
    return receipt


def _verify_artifact_record(run_dir: Path, record: Mapping[str, Any]) -> Path:
    path = resolve_artifact_path(dict(record), base_dir=run_dir)
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ExportError(f"run artifact is missing or changed: {path}")
    if path.stat().st_size != record.get("size_bytes"):
        raise ExportError(f"run artifact size changed: {path}")
    return path


def _selected_unit_receipt(
    run_dir: Path, candidate: str, seed: int
) -> tuple[Path, dict[str, Any]]:
    path = run_dir / "selection" / candidate / f"seed_{seed}" / "unit_receipt.json"
    receipt = _verify_receipt(path, "selection")
    if receipt.get("candidate") != candidate or receipt.get("seed") != seed:
        raise ExportError("selected unit receipt identity mismatch")
    return path, receipt


def _verify_locked_test_receipt(
    run_dir: Path,
    *,
    selection_receipt: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    path = run_dir / "test" / "TEST_EVALUATION_COMPLETE.json"
    receipt = _verify_receipt(path, "locked_test_complete")
    if receipt.get("protocol_digest") != selection_receipt.get("protocol_digest"):
        raise ExportError("locked-test receipt protocol digest mismatch")
    if receipt.get("selection_receipt_digest") != selection_receipt.get(
        "receipt_digest"
    ):
        raise ExportError("locked-test receipt binds a different selection receipt")
    if receipt.get("input_manifest_digest") != experiment_object_sha256(input_manifest):
        raise ExportError("locked-test receipt binds a different input manifest")
    if receipt.get("class_map_sha256") != input_manifest.get("class_map_sha256"):
        raise ExportError("locked-test receipt class-map digest mismatch")
    if receipt.get("test_ranking_performed") is not False:
        raise ExportError(
            "locked-test receipt does not attest that test ranking was avoided"
        )
    required_artifacts = {
        "seed_ensemble_predictions",
        "seed_ensemble_metrics",
        "seed_ensemble_risk_coverage_at_validation_thresholds",
        "unit_artifact_index",
    }
    if missing := sorted(required_artifacts - set(receipt.get("artifacts", {}))):
        raise ExportError(f"locked-test receipt lacks ensemble artifacts: {missing}")
    for record in receipt.get("artifacts", {}).values():
        _verify_artifact_record(run_dir, record)
    unit_index = receipt.get("artifacts", {}).get("unit_artifact_index")
    if not isinstance(unit_index, dict):
        raise ExportError("locked-test receipt lacks its unit artifact index")
    _verify_unit_index(run_dir, unit_index)
    if receipt.get("calibration_protocol") != selection_receipt.get(
        "calibration_protocol"
    ):
        raise ExportError("locked test changed the frozen calibration protocol")
    if receipt.get("review_policy_applied_unchanged") != selection_receipt.get(
        "review_policy"
    ):
        raise ExportError("locked test changed the validation-frozen review policy")
    return receipt


def _copy_regular_file(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise ExportError(f"source must be a regular, non-symlink file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_regular_tree(source: Path, destination: Path) -> list[Path]:
    if not source.is_dir() or source.is_symlink():
        raise ExportError(f"source must be a non-symlink directory: {source}")
    copied: list[Path] = []
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ExportError(f"symlinks are forbidden in encoder artifacts: {item}")
        if item.is_file():
            relative = item.relative_to(source)
            target = destination / relative
            _copy_regular_file(item, target)
            copied.append(target)
    if not copied:
        raise ExportError(f"encoder artifact directory is empty: {source}")
    return copied


def _class_map(input_manifest: Mapping[str, Any]) -> dict[str, Any]:
    raw = input_manifest.get("class_map")
    if not isinstance(raw, Mapping):
        raise ExportError("input manifest lacks a class map")
    rows = [
        {"label_id": int(item["label_id"]), "label_name": str(item["label_name"])}
        for item in raw.get("classes", [])
    ]
    if [row["label_id"] for row in rows] != list(range(len(rows))):
        raise ExportError("input class ids are not contiguous and ordered")
    if [row["label_name"] for row in rows] != list(TARGET_CLASSES):
        raise ExportError("input class map differs from crm.TARGET_CLASSES")
    semantic = object_sha256(rows)
    if raw.get("sha256") != input_manifest.get("class_map_sha256"):
        raise ExportError("input class-map receipt digest mismatch")
    return {"classes": rows, "semantic_sha256": semantic}


def _encoder_provenance(
    input_manifest: Mapping[str, Any], modality: str, name: str
) -> dict[str, Any]:
    key = f"{modality}:{name}"
    record = input_manifest.get("embeddings", {}).get(key)
    if not isinstance(record, Mapping):
        raise ExportError(f"input manifest lacks encoder provenance for {key}")
    provenance = record.get("provenance")
    extraction_receipt = record.get("extraction_receipt")
    if not isinstance(provenance, Mapping) or not isinstance(
        extraction_receipt, Mapping
    ):
        raise ExportError(f"{key} lacks a validated extraction receipt")
    encoder = provenance.get("encoder")
    if not isinstance(encoder, Mapping):
        raise ExportError(f"{key} extraction receipt lacks encoder identity")
    result = {
        "name": name,
        "repository": encoder.get("repository"),
        "revision": encoder.get("revision"),
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
    try:
        validate_preprocessing_contract(
            result["preprocessing"],
            modality=modality,
            pooling=result["pooling"],
            prefix=result["prefix"],
            max_length=result["max_length"],
            output_dtype=result["dtype"],
        )
    except PreprocessingContractError as exc:
        raise ExportError(f"{key} preprocessing contract: {exc}") from exc
    if preprocessing_sha256(result["preprocessing"]) != result["preprocessing_sha256"]:
        raise ExportError(f"{key} preprocessing semantic digest mismatch")
    return result


def _verify_staged_preprocessing_assets(
    provenance: Mapping[str, Any],
    encoder_dir: Path,
) -> None:
    implementation = provenance["preprocessing"]["implementation"]
    declared = {
        str(item["path"]): str(item["sha256"]) for item in implementation["assets"]
    }
    actual = {
        path.relative_to(encoder_dir).as_posix(): path
        for path in encoder_dir.rglob("*")
        if path.is_file()
    }
    model_files = {"model.onnx", "model.onnx_data", "model.onnx.data"}
    undeclared = sorted(set(actual).difference(declared).difference(model_files))
    missing = sorted(set(declared).difference(actual))
    if missing or undeclared:
        raise ExportError(
            "exported preprocessing/tokenizer assets differ from extraction "
            f"provenance; missing={missing}, undeclared={undeclared}"
        )
    mismatched = sorted(
        relative
        for relative, expected_hash in declared.items()
        if export_sha256_file(actual[relative]) != expected_hash
    )
    if mismatched:
        raise ExportError(
            "exported preprocessing/tokenizer asset hashes differ from extraction "
            f"provenance: {mismatched}"
        )


def _validate_serving_preprocessing_support(
    image_provenance: Mapping[str, Any],
    text_provenance: Mapping[str, Any],
) -> None:
    image = image_provenance["preprocessing"]
    if (
        image["implementation"]["framework"] != "huggingface_transformers"
        or image["decode"]["exif_orientation"] != "apply_exif_transpose"
        or image["decode"]["color_mode"] != "RGB"
        or image["decode"]["alpha_channel_policy"] != "drop_after_rgb_conversion"
        or image["decode"]["animated_image_policy"] != "first_frame"
        or image["numeric"]["tensor_layout"] != "NCHW"
        or image["numeric"]["tensor_dtype"] != "float32"
    ):
        raise ExportError(
            "serve_model.py supports only the explicitly contracted Hugging Face "
            "RGB/exif-transposed NCHW float32 image path; retain TIMM contracts for "
            "experiments until a matching deployment runtime is implemented"
        )
    text = text_provenance["preprocessing"]
    cleaning = text["cleaning"]
    unsupported_cleaning = {
        "unicode_normalization": "none",
        "strip": False,
        "collapse_whitespace": False,
        "lowercase": False,
        "newline_policy": "preserve",
        "html_policy": "preserve",
        "url_policy": "preserve",
        "mention_policy": "preserve",
        "control_character_policy": "preserve",
    }
    tokenization = text["tokenization"]
    if (
        text["implementation"]["framework"] != "huggingface_transformers"
        or any(
            cleaning.get(key) != value for key, value in unsupported_cleaning.items()
        )
        or tokenization["add_special_tokens"] is not True
        or tokenization["truncation"] is not True
        or tokenization["padding"] != "longest"
        or tokenization["return_attention_mask"] is not True
        or tokenization["return_token_type_ids"] != "auto"
        or text["embedding"]["l2_normalize"] is not True
    ):
        raise ExportError(
            "text extraction preprocessing is scientifically valid but is not "
            "exactly reproducible by the current serve_model.py tokenizer path"
        )


def export_bundle(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    config = load_resolved_config(run_dir / "resolved_config.json")
    if config.l2_per_modality is not True:
        raise ExportError(
            "serve_model.py uses the frozen per-modality L2 fusion rule; runs with "
            "data.l2_per_modality=false are not deployable"
        )
    input_manifest = read_json(run_dir / "metadata" / "input_manifest.json")
    verify_input_manifest(input_manifest)
    selection = _verify_selection_receipt(config, run_dir, input_manifest)
    if (
        selection.get("primary_system") != "equal_weight_preregistered_seed_ensemble"
        or "equal-weight arithmetic mean" not in selection.get("selection_rule", "")
        or "ensemble_nll" not in selection.get("selection_rule", "")
        or "checkpoint size" not in selection.get("selection_rule", "")
    ):
        raise ExportError(
            "selection receipt does not bind candidate ranking to the seed ensemble"
        )
    eligible_names = selection.get("deployment_eligible_candidates")
    if eligible_names != list(config.deployment_eligible_candidates):
        raise ExportError(
            "selection receipt does not bind the preregistered deployment-eligible "
            "candidate set"
        )
    for eligible_name in config.deployment_eligible_candidates:
        eligible_candidate = config.candidate(eligible_name)
        if (
            eligible_candidate.model != "catboost"
            or eligible_candidate.image_encoder is None
            or eligible_candidate.text_encoder is None
        ):
            raise ExportError(
                "every primary-selection candidate must be exportable by the "
                "five-head CatBoost image+text runtime; unsupported candidate "
                f"{eligible_name!r} was preregistered as deployment eligible"
            )
    calibration_protocol = selection.get("calibration_protocol")
    review_policy = selection.get("review_policy")
    if not isinstance(calibration_protocol, Mapping) or not isinstance(
        review_policy, Mapping
    ):
        raise ExportError("selection receipt lacks calibration/review policy")
    if (
        calibration_protocol.get("family") != "identity_no_posthoc_calibration"
        or calibration_protocol.get("fitting_objective") != "not_applicable_identity"
        or calibration_protocol.get("probability_scope")
        != "equal_weight_seed_ensemble_probabilities"
        or calibration_protocol.get("claim") != "uncalibrated_probabilities"
    ):
        raise ExportError("unsupported or ambiguous calibration protocol")
    expected_unconditional = (
        ["Instansi lain"] if "Instansi lain" in TARGET_CLASSES else []
    )
    expected_routable = [label for label in TARGET_CLASSES if label != "Instansi lain"]
    if (
        review_policy.get("candidate") != selection.get("selected_candidate")
        or review_policy.get("threshold_source") != "validation_seed_ensemble"
        or review_policy.get("selection_split") != "validation"
        or review_policy.get("operating_criterion")
        != "fixed_target_joint_validation_coverage_on_predicted_routable_labels"
        or review_policy.get("target_population") != "predicted_routable_labels_only"
        or review_policy.get("policy_scope")
        != "model_review_gates_plus_unconditional_labels_excluding_registry"
        or review_policy.get("unconditionally_reviewed_labels")
        != expected_unconditional
        or review_policy.get("routable_labels") != expected_routable
    ):
        raise ExportError("selection review policy is not safe for deployment")
    candidate_name = selection["selected_candidate"]
    if candidate_name not in config.deployment_eligible_candidates:
        raise ExportError(
            "selected candidate was not preregistered as deployment eligible"
        )
    candidate = config.candidate(candidate_name)
    if candidate.model != "catboost":
        raise ExportError(
            f"selected candidate {candidate_name!r} is {candidate.model!r}; only a "
            "CatBoost seed ensemble can be exported by this deployment path"
        )
    if candidate.image_encoder is None or candidate.text_encoder is None:
        raise ExportError(
            "selected candidate is not a deployable image+text fusion model"
        )
    if len(config.seeds) < 5 or len(set(config.seeds)) != len(config.seeds):
        raise ExportError(
            "a deployable Q2 ensemble requires at least five distinct preregistered seeds"
        )
    if (
        not args.model_version.strip()
        or args.model_version.strip().lower() == "unversioned"
    ):
        raise ExportError(
            "--model-version must be a stable, non-'unversioned' identifier"
        )

    locked_test: dict[str, Any] | None = None
    if args.policy == "locked_test_complete":
        locked_test = _verify_locked_test_receipt(
            run_dir,
            selection_receipt=selection,
            input_manifest=input_manifest,
        )
        if candidate_name not in locked_test.get(
            "test_candidates_in_preregistered_order", []
        ):
            raise ExportError(
                "selected candidate was not included in the locked test plan"
            )

    source_members: list[dict[str, Any]] = []
    model_records = selection.get("model_records", {}).get(candidate_name, {})
    for seed in config.seeds:
        unit_path, unit = _selected_unit_receipt(run_dir, candidate_name, seed)
        if unit.get("protocol_digest") != selection.get("protocol_digest"):
            raise ExportError(f"selected unit protocol digest mismatch for seed {seed}")
        if unit.get("class_map_sha256") != input_manifest.get("class_map_sha256"):
            raise ExportError(
                f"selected unit class-map digest mismatch for seed {seed}"
            )
        checkpoint_record = model_records.get(str(seed))
        if not isinstance(checkpoint_record, Mapping):
            raise ExportError(
                f"selection receipt does not bind checkpoint for seed {seed}"
            )
        if unit.get("artifacts", {}).get("checkpoint") != checkpoint_record:
            raise ExportError(
                f"selection and unit receipts bind different checkpoints for seed {seed}"
            )
        checkpoint = _verify_artifact_record(run_dir, checkpoint_record)
        source_members.append(
            {
                "seed": int(seed),
                "unit_path": unit_path,
                "unit": unit,
                "checkpoint_record": dict(checkpoint_record),
                "checkpoint": checkpoint,
            }
        )

    image_provenance = _encoder_provenance(
        input_manifest, "image", candidate.image_encoder
    )
    text_provenance = _encoder_provenance(
        input_manifest, "text", candidate.text_encoder
    )
    if text_provenance.get("pooling") not in {"cls", "e5_avg"}:
        raise ExportError("text pooling contract is unsupported by serve_model.py")
    if not isinstance(text_provenance.get("prefix"), str):
        raise ExportError("text prefix is missing from the extraction receipt")
    if type(text_provenance.get("max_length")) is not int:
        raise ExportError("text max_length is missing from the extraction receipt")
    _validate_serving_preprocessing_support(image_provenance, text_provenance)

    output = args.output_dir.resolve()
    if output.exists():
        raise ExportError(
            f"refusing to overwrite immutable export directory: {output}; use a new version"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
    )
    try:
        from catboost import CatBoostClassifier

        classifier_feature_count: int | None = None
        expected_feature_count = int(image_provenance["dimension"]) + int(
            text_provenance["dimension"]
        )
        classifier_members: list[dict[str, Any]] = []
        classifier_artifacts: list[dict[str, Any]] = []
        for source in source_members:
            seed = int(source["seed"])
            model_metadata = source["unit"].get("model_metadata")
            if (
                not isinstance(model_metadata, Mapping)
                or model_metadata.get("checkpoint_tree_policy")
                != config.catboost.checkpoint_tree_policy
                or model_metadata.get("point_model_trimmed_to_validation_best")
                is not False
                or type(model_metadata.get("trained_tree_count")) is not int
                or model_metadata["trained_tree_count"] < 1
                or model_metadata.get("inference_tree_count")
                != model_metadata["trained_tree_count"]
            ):
                raise ExportError(
                    f"seed {seed} does not bind the matched point/PGS full-"
                    "trajectory checkpoint policy"
                )
            model = CatBoostClassifier()
            model.load_model(str(source["checkpoint"]))
            if int(model.tree_count_) != model_metadata["inference_tree_count"]:
                raise ExportError(
                    f"seed {seed} checkpoint tree count differs from its unit receipt"
                )
            classes = [int(value) for value in model.classes_]
            if classes != list(range(len(TARGET_CLASSES))):
                raise ExportError(
                    f"seed {seed} checkpoint class ids {classes} differ from the "
                    "frozen class map"
                )
            # CatBoost 1.2.x does not always restore ``n_features_in_`` after
            # loading a native checkpoint, while it does restore feature names.
            member_feature_count = int(model.n_features_in_) or len(
                model.feature_names_
            )
            if member_feature_count != expected_feature_count:
                raise ExportError(
                    f"seed {seed} checkpoint expects {member_feature_count} fused "
                    f"features, but encoder receipts declare {expected_feature_count}"
                )
            if classifier_feature_count is None:
                classifier_feature_count = member_feature_count
            elif member_feature_count != classifier_feature_count:
                raise ExportError("seed-ensemble classifier dimensions differ")
            if candidate.posterior_sampling:
                try:
                    validate_pgs_model(model, config.virtual_ensembles)
                except ValueError as exc:
                    raise ExportError(
                        f"seed {seed} cannot reproduce preregistered PGS inference: {exc}"
                    ) from exc
            classifier_onnx = staging / "classifiers" / f"seed_{seed}.onnx"
            classifier_onnx.parent.mkdir(parents=True, exist_ok=True)
            model.save_model(
                str(classifier_onnx),
                format="onnx",
                export_parameters={
                    "onnx_domain": "org.crmjakarta",
                    "onnx_model_version": 1,
                    "onnx_doc_string": (
                        f"Receipt-bound classifier {candidate_name}, seed {seed}"
                    ),
                    "onnx_graph_name": f"crm_jakarta_classifier_seed_{seed}",
                },
            )
            classifier_native = staging / "classifiers" / f"seed_{seed}.cbm"
            _copy_regular_file(source["checkpoint"], classifier_native)
            classifier_artifacts.extend(
                [
                    artifact_record(
                        classifier_onnx, root=staging, role="classifier_onnx"
                    ),
                    artifact_record(
                        classifier_native, root=staging, role="classifier_native"
                    ),
                ]
            )
            classifier_members.append(
                {
                    "seed": seed,
                    "tree_count": int(model.tree_count_),
                    "onnx": classifier_onnx.relative_to(staging).as_posix(),
                    "native": classifier_native.relative_to(staging).as_posix(),
                }
            )
        if classifier_feature_count is None:
            raise ExportError("no classifier heads were exported")

        image_model = staging / "image_encoder" / "model.onnx"
        image_preprocessor = staging / "image_encoder" / "preprocessor_config.json"
        _copy_regular_file(args.image_onnx.resolve(), image_model)
        _copy_regular_file(args.image_preprocessor.resolve(), image_preprocessor)
        text_files = _copy_regular_tree(
            args.text_model_dir.resolve(), staging / "text_encoder"
        )
        text_model = staging / "text_encoder" / "model.onnx"
        if text_model not in text_files:
            raise ExportError("--text-model-dir must contain model.onnx")
        _verify_staged_preprocessing_assets(image_provenance, staging / "image_encoder")
        _verify_staged_preprocessing_assets(text_provenance, staging / "text_encoder")

        artifacts = [
            *classifier_artifacts,
            artifact_record(image_model, root=staging, role="image_encoder_onnx"),
            artifact_record(
                image_preprocessor, root=staging, role="image_preprocessor"
            ),
        ]
        for path in text_files:
            role = "text_encoder_onnx" if path == text_model else "text_tokenizer_asset"
            artifacts.append(artifact_record(path, root=staging, role=role))
        artifacts.sort(key=lambda item: item["path"])

        image_provenance["artifact_tree_sha256"] = artifact_tree_sha256(
            artifacts, prefix="image_encoder"
        )
        text_provenance["artifact_tree_sha256"] = artifact_tree_sha256(
            artifacts, prefix="text_encoder"
        )
        manifest: dict[str, Any] = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "kind": EXPORT_KIND,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": {
                "name": args.model_name,
                "version": args.model_version,
                "candidate": candidate_name,
                "seeds": list(config.seeds),
                "ensemble_size": len(config.seeds),
                "probability_aggregation": "equal_weight_arithmetic_mean",
                "class_count": len(TARGET_CLASSES),
                "classifier_feature_count": classifier_feature_count,
                "training_posterior_sampling": bool(candidate.posterior_sampling),
                "checkpoint_tree_policy": config.catboost.checkpoint_tree_policy,
                "default_inference_method": (
                    "catboost_virtual_ensemble_seed_ensemble"
                    if candidate.posterior_sampling
                    else "onnx_equal_weight_seed_ensemble"
                ),
            },
            "protocol": {
                "export_policy": args.policy,
                "protocol_digest": selection["protocol_digest"],
                "input_manifest_digest": experiment_object_sha256(input_manifest),
                "selection_receipt_digest": selection["receipt_digest"],
                "locked_test_receipt_digest": (
                    locked_test["receipt_digest"] if locked_test is not None else None
                ),
                "source_members": [
                    {
                        "seed": source["seed"],
                        "checkpoint_sha256": source["checkpoint_record"]["sha256"],
                        "unit_receipt_sha256": export_sha256_file(source["unit_path"]),
                        "tree_count": source["unit"]["model_metadata"][
                            "inference_tree_count"
                        ],
                    }
                    for source in source_members
                ],
                "source_class_map_sha256": input_manifest["class_map_sha256"],
                "deployment_seed_rule": "all_preregistered_seeds_equal_weight",
                "deployment_eligible_candidates": list(
                    config.deployment_eligible_candidates
                ),
                "selection_eligibility_rule": selection["selection_eligibility_rule"],
                "virtual_ensembles_per_seed": (
                    config.virtual_ensembles if candidate.posterior_sampling else None
                ),
            },
            "class_map": _class_map(input_manifest),
            "calibration": dict(calibration_protocol),
            "review_policy": dict(review_policy),
            "encoders": {
                "image": image_provenance,
                "text": text_provenance,
            },
            "feature_fusion": {
                "operation": "concatenate",
                "modality_order": ["image", "text"],
                "axis": 1,
                "l2_per_modality": True,
                "l2_epsilon": 1e-9,
                "output_dtype": "float32",
            },
            "parity_tolerances": {
                "encoder_tensor_boundary": dict(ENCODER_TENSOR_PARITY_TOLERANCES),
                "classifier_native_onnx": dict(CLASSIFIER_PARITY_TOLERANCES),
                "raw_input_end_to_end": dict(RAW_PIPELINE_PARITY_TOLERANCES),
            },
            "runtime": {
                "classifier_members": classifier_members,
                "image_model": "image_encoder/model.onnx",
                "image_preprocessor": "image_encoder/preprocessor_config.json",
                "text_model": "text_encoder/model.onnx",
                "text_tokenizer_dir": "text_encoder",
                "text_pooling": text_provenance["pooling"],
                "text_prefix": text_provenance["prefix"],
                "text_max_length": text_provenance["max_length"],
            },
            "artifacts": artifacts,
        }
        manifest["manifest_digest"] = manifest_digest(manifest)
        manifest_path = staging / MANIFEST_FILENAME
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        manifest_hash = export_sha256_file(manifest_path)
        validate_export_manifest(
            staging,
            expected_manifest_sha256=manifest_hash,
            expected_classes=TARGET_CLASSES,
            expected_model_version=args.model_version,
        )
        os.replace(staging, output)
        return {
            "output_dir": str(output),
            "export_manifest": str(output / MANIFEST_FILENAME),
            "export_manifest_sha256": manifest_hash,
            "model_version": args.model_version,
            "candidate": candidate_name,
            "seeds": list(config.seeds),
            "ensemble_size": len(config.seeds),
            "export_policy": args.policy,
            "warning": (
                "Set EXPORT_MANIFEST_SHA256 to the printed digest. The bundle is "
                "not deployment-eligible until locked-test and parity gates required "
                "by the project protocol also pass."
            ),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--policy",
        choices=("selection_complete", "locked_test_complete"),
        default="locked_test_complete",
        help="locked_test_complete is required for a release deployment",
    )
    parser.add_argument("--image-onnx", type=Path, required=True)
    parser.add_argument("--image-preprocessor", type=Path, required=True)
    parser.add_argument("--text-model-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-name", default="smartcity-multiclass-classifier")
    parser.add_argument("--model-version", required=True)
    return parser


def main() -> int:
    try:
        result = export_bundle(build_parser().parse_args())
    except (ExportError, ExportContractError, OSError, ValueError) as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
