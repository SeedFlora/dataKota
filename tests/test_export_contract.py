from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.export_contract import (
    EXPORT_KIND,
    EXPORT_SCHEMA_VERSION,
    ExportContractError,
    artifact_record,
    artifact_tree_sha256,
    manifest_digest,
    object_sha256,
    sha256_file,
    validate_export_manifest,
)
from crm.preprocessing_contract import preprocessing_sha256
from tests.preprocessing_examples import image_preprocessing, text_preprocessing

CLASSES = ("A", "B")


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "export"
    (root / "image_encoder").mkdir(parents=True)
    (root / "text_encoder").mkdir()
    (root / "classifiers").mkdir()
    files = {
        "image_encoder/model.onnx": b"image-onnx",
        "image_encoder/preprocessor_config.json": b"{}",
        "text_encoder/model.onnx": b"text-onnx",
        "text_encoder/tokenizer.json": b"{}",
    }
    for seed in (1, 2, 3, 4, 5):
        files[f"classifiers/seed_{seed}.onnx"] = f"onnx-{seed}".encode()
        files[f"classifiers/seed_{seed}.cbm"] = f"native-{seed}".encode()
    for relative, content in files.items():
        (root / relative).write_bytes(content)
    role_by_path = {
        "image_encoder/model.onnx": "image_encoder_onnx",
        "image_encoder/preprocessor_config.json": "image_preprocessor",
        "text_encoder/model.onnx": "text_encoder_onnx",
        "text_encoder/tokenizer.json": "text_tokenizer_asset",
    }
    for seed in (1, 2, 3, 4, 5):
        role_by_path[f"classifiers/seed_{seed}.onnx"] = "classifier_onnx"
        role_by_path[f"classifiers/seed_{seed}.cbm"] = "classifier_native"
    artifacts = [
        artifact_record(root / relative, root=root, role=role_by_path[relative])
        for relative in sorted(files)
    ]
    class_rows = [
        {"label_id": index, "label_name": label} for index, label in enumerate(CLASSES)
    ]
    image_contract = image_preprocessing()
    text_contract = text_preprocessing(max_length=256)
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "kind": EXPORT_KIND,
        "created_at_utc": "2026-08-25T00:00:00+00:00",
        "model": {
            "name": "test-model",
            "version": "q2-run-001",
            "candidate": "cb_fusion",
            "seeds": [1, 2, 3, 4, 5],
            "ensemble_size": 5,
            "probability_aggregation": "equal_weight_arithmetic_mean",
            "class_count": 2,
            "classifier_feature_count": 8,
            "training_posterior_sampling": False,
            "checkpoint_tree_policy": (
                "full_early_stopped_trajectory_for_both_point_and_pgs"
            ),
            "default_inference_method": "onnx_equal_weight_seed_ensemble",
        },
        "protocol": {
            "export_policy": "locked_test_complete",
            "protocol_digest": "1" * 64,
            "input_manifest_digest": "2" * 64,
            "selection_receipt_digest": "3" * 64,
            "locked_test_receipt_digest": "4" * 64,
            "source_members": [
                {
                    "seed": seed,
                    "checkpoint_sha256": next(
                        item["sha256"]
                        for item in artifacts
                        if item["path"] == f"classifiers/seed_{seed}.cbm"
                    ),
                    "unit_receipt_sha256": str(seed) * 64,
                    "tree_count": 100,
                }
                for seed in (1, 2, 3, 4, 5)
            ],
            "source_class_map_sha256": "7" * 64,
            "deployment_seed_rule": "all_preregistered_seeds_equal_weight",
            "deployment_eligible_candidates": ["cb_fusion"],
            "selection_eligibility_rule": (
                "only candidates listed in protocol.deployment_eligible_candidates "
                "may define the primary selected/deployed system; all other "
                "evaluated candidates are secondary baselines or ablations"
            ),
            "virtual_ensembles_per_seed": None,
        },
        "class_map": {
            "classes": class_rows,
            "semantic_sha256": object_sha256(class_rows),
        },
        "calibration": {
            "family": "identity_no_posthoc_calibration",
            "fitting_objective": "not_applicable_identity",
            "probability_scope": "equal_weight_seed_ensemble_probabilities",
            "claim": "uncalibrated_probabilities",
            "ece": {
                "family": "top_label",
                "binning": "equal_width_0_1",
                "bins": 15,
                "bin_interval_semantics": "left_closed_right_open_final_closed",
            },
        },
        "review_policy": {
            "candidate": "cb_fusion",
            "threshold_source": "validation_seed_ensemble",
            "selection_split": "validation",
            "operating_criterion": "fixed_target_joint_validation_coverage_on_predicted_routable_labels",
            "target_coverage": 0.8,
            "target_population": "predicted_routable_labels_only",
            "tie_policy": "include_all_at_boundary",
            "policy_scope": "model_review_gates_plus_unconditional_labels_excluding_registry",
            "marginal_quantile_coverage": 0.8,
            "minimum_confidence": 0.7,
            "maximum_one_minus_confidence": 0.3,
            "maximum_epistemic_mutual_information": None,
            "validation_realized_confidence_coverage": 0.8,
            "validation_confidence_selective_risk": 0.2,
            "validation_realized_epistemic_coverage": None,
            "validation_epistemic_selective_risk": None,
            "validation_joint_realized_coverage": 0.8,
            "validation_joint_overall_realized_coverage": 0.8,
            "validation_joint_selective_risk": 0.2,
            "validation_target_population_count": 10,
            "validation_unconditionally_reviewed_count": 0,
            "unconditionally_reviewed_labels": [],
            "routable_labels": list(CLASSES),
        },
        "encoders": {
            "image": {
                "name": "image",
                "repository": "org/image",
                "revision": "a" * 40,
                "extraction_receipt_sha256": "c" * 64,
                "embedding_sha256": "d" * 64,
                "extraction_code_commit": "e" * 40,
                "preprocessing": image_contract,
                "preprocessing_sha256": preprocessing_sha256(image_contract),
                "pooling": "cls_token",
                "prefix": None,
                "max_length": None,
                "dimension": 3,
                "dtype": "float32",
                "artifact_tree_sha256": artifact_tree_sha256(
                    artifacts, prefix="image_encoder"
                ),
            },
            "text": {
                "name": "text",
                "repository": "org/text",
                "revision": "b" * 40,
                "extraction_receipt_sha256": "f" * 64,
                "embedding_sha256": "1" * 64,
                "extraction_code_commit": "2" * 40,
                "preprocessing": text_contract,
                "preprocessing_sha256": preprocessing_sha256(text_contract),
                "pooling": "e5_avg",
                "prefix": "query: ",
                "max_length": 256,
                "dimension": 5,
                "dtype": "float32",
                "artifact_tree_sha256": artifact_tree_sha256(
                    artifacts, prefix="text_encoder"
                ),
            },
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
            "encoder_tensor_boundary": {
                "absolute_tolerance": 1e-5,
                "minimum_cosine_similarity": 0.99999,
            },
            "classifier_native_onnx": {
                "probability_tolerance": 1e-5,
                "minimum_top1_agreement": 1.0,
            },
            "raw_input_end_to_end": {
                "max_absolute_probability_error": 1e-5,
                "minimum_top1_agreement": 1.0,
            },
        },
        "runtime": {
            "classifier_members": [
                {
                    "seed": seed,
                    "tree_count": 100,
                    "onnx": f"classifiers/seed_{seed}.onnx",
                    "native": f"classifiers/seed_{seed}.cbm",
                }
                for seed in (1, 2, 3, 4, 5)
            ],
            "image_model": "image_encoder/model.onnx",
            "image_preprocessor": "image_encoder/preprocessor_config.json",
            "text_model": "text_encoder/model.onnx",
            "text_tokenizer_dir": "text_encoder",
            "text_pooling": "e5_avg",
            "text_prefix": "query: ",
            "text_max_length": 256,
        },
        "artifacts": artifacts,
    }
    manifest["manifest_digest"] = manifest_digest(manifest)
    manifest_path = root / "export_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return root, sha256_file(manifest_path)


def _rewrite_manifest(root: Path, manifest: dict) -> str:
    manifest["manifest_digest"] = manifest_digest(manifest)
    path = root / "export_manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return sha256_file(path)


def test_complete_bundle_validates_against_external_trust_anchor(
    tmp_path: Path,
) -> None:
    root, manifest_hash = _bundle(tmp_path)
    manifest = validate_export_manifest(
        root,
        expected_manifest_sha256=manifest_hash,
        expected_classes=CLASSES,
        expected_model_version="q2-run-001",
    )
    assert manifest["model"]["candidate"] == "cb_fusion"


def test_pgs_bundle_binds_joint_seed_virtual_member_mi_semantics(
    tmp_path: Path,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["model"]["training_posterior_sampling"] = True
    manifest["model"]["default_inference_method"] = (
        "catboost_virtual_ensemble_seed_ensemble"
    )
    manifest["protocol"]["virtual_ensembles_per_seed"] = 30
    policy = manifest["review_policy"]
    policy["maximum_epistemic_mutual_information"] = 0.05
    policy["epistemic_uncertainty_semantics"] = (
        "joint_training_seed_pgs_component_mutual_information_nats"
    )
    policy["epistemic_component_axis"] = "training_seed_x_pgs_virtual_member"
    policy["epistemic_component_count"] = 150
    policy["epistemic_training_seed_count"] = 5
    policy["epistemic_virtual_ensembles_per_seed"] = 30
    anchor = _rewrite_manifest(root, manifest)

    validate_export_manifest(
        root,
        expected_manifest_sha256=anchor,
        expected_classes=CLASSES,
    )

    manifest["review_policy"]["epistemic_uncertainty_semantics"] = (
        "mutual_information_nats"
    )
    anchor = _rewrite_manifest(root, manifest)
    with pytest.raises(ExportContractError, match="joint training-seed"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=anchor,
            expected_classes=CLASSES,
        )


def test_bundle_rejects_selected_model_outside_preregistered_exportable_subset(
    tmp_path: Path,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["protocol"]["deployment_eligible_candidates"] = ["other_model"]
    anchor = _rewrite_manifest(root, manifest)

    with pytest.raises(ExportContractError, match="selected model"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=anchor,
            expected_classes=CLASSES,
        )


def test_bundle_rejects_training_serving_fusion_normalization_mismatch(
    tmp_path: Path,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["feature_fusion"]["l2_per_modality"] = False
    manifest_hash = _rewrite_manifest(root, manifest)
    with pytest.raises(ExportContractError, match="feature_fusion"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=manifest_hash,
            expected_classes=CLASSES,
        )


def test_bundle_rejects_loosened_raw_pipeline_parity_tolerance(
    tmp_path: Path,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["parity_tolerances"]["raw_input_end_to_end"][
        "max_absolute_probability_error"
    ] = 0.1
    manifest_hash = _rewrite_manifest(root, manifest)
    with pytest.raises(ExportContractError, match="parity tolerances"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=manifest_hash,
            expected_classes=CLASSES,
        )


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("encoder_tensor_boundary", "absolute_tolerance"),
        ("classifier_native_onnx", "probability_tolerance"),
    ],
)
def test_bundle_rejects_loosened_component_parity_tolerance(
    tmp_path: Path,
    section: str,
    field: str,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["parity_tolerances"][section][field] = 1.0
    manifest_hash = _rewrite_manifest(root, manifest)
    with pytest.raises(ExportContractError, match="parity tolerances"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=manifest_hash,
            expected_classes=CLASSES,
        )


def test_missing_external_manifest_hash_fails_closed(tmp_path: Path) -> None:
    root, _ = _bundle(tmp_path)
    with pytest.raises(ExportContractError, match="expected_manifest_sha256"):
        validate_export_manifest(
            root, expected_manifest_sha256=None, expected_classes=CLASSES
        )


def test_substituted_manifest_or_artifact_is_rejected(tmp_path: Path) -> None:
    root, manifest_hash = _bundle(tmp_path)
    (root / "classifiers" / "seed_1.onnx").write_bytes(b"tampered")
    with pytest.raises(ExportContractError, match="size changed|hash changed"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=manifest_hash,
            expected_classes=CLASSES,
        )


def test_class_column_reinterpretation_is_rejected(tmp_path: Path) -> None:
    root, manifest_hash = _bundle(tmp_path)
    with pytest.raises(ExportContractError, match="class map differs"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=manifest_hash,
            expected_classes=("B", "A"),
        )


def test_preprocessing_asset_must_match_the_exported_runtime_file(
    tmp_path: Path,
) -> None:
    root, _ = _bundle(tmp_path)
    path = root / "export_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    preprocessing = manifest["encoders"]["image"]["preprocessing"]
    preprocessing["implementation"]["assets"][0]["sha256"] = "0" * 64
    manifest["encoders"]["image"]["preprocessing_sha256"] = preprocessing_sha256(
        preprocessing
    )
    anchor = _rewrite_manifest(root, manifest)
    with pytest.raises(ExportContractError, match="asset hash differs"):
        validate_export_manifest(
            root,
            expected_manifest_sha256=anchor,
            expected_classes=CLASSES,
        )
