from __future__ import annotations

import json
import sys
from argparse import Namespace
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from crm.experiments.config import CandidateConfig
from crm.experiments.runner import run_locked_test, run_selection
from crm.export_contract import validate_export_manifest
from crm.preprocessing_contract import preprocessing_sha256
from tests.preprocessing_examples import text_preprocessing
from tests.test_q2_experiment_protocol import _tiny_protocol
from tools import export_q2_model, q2_readiness


def test_scripted_export_binds_real_catboost_checkpoint_and_receipts(
    tmp_path: Path, monkeypatch
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    image_receipt_path = config.image_embeddings_dir / "tiny_image.receipt.json"
    image_receipt = json.loads(image_receipt_path.read_text(encoding="utf-8"))
    image_receipt["preprocessing"]["implementation"].update(
        {
            "framework": "huggingface_transformers",
            "library": "transformers",
            "library_version": "4.55.0",
            "processor_class": "transformers.AutoImageProcessor",
            "configuration_source": "repository_assets",
            "processor_repository": "example/tiny-image-encoder",
            "processor_revision": "1" * 40,
        }
    )
    image_receipt["preprocessing_sha256"] = preprocessing_sha256(
        image_receipt["preprocessing"]
    )
    image_receipt_path.write_text(json.dumps(image_receipt), encoding="utf-8")
    text_embedding = config.text_embeddings_dir / "tiny_text.npy"
    source_path = tmp_path / "source_snapshot.csv"
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    mapping_hash = sha256(
        json.dumps(list(range(18)), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    text_contract = text_preprocessing()
    text_contract["implementation"].update(
        {
            "framework": "huggingface_transformers",
            "library": "transformers",
            "library_version": "4.55.0",
            "tokenizer_class": "transformers.AutoTokenizer",
        }
    )
    text_receipt = {
        "schema_version": 2,
        "modality": "text",
        "encoder_name": "tiny_text",
        "embedding_file": text_embedding.name,
        "embedding_sha256": sha256(text_embedding.read_bytes()).hexdigest(),
        "source_snapshot_sha256": source_hash,
        "source_row_order_sha256": source_hash,
        "embedding_index_column": "embedding_index",
        "embedding_index_mapping_sha256": mapping_hash,
        "encoder": {"repository": "example/tiny-text", "revision": "3" * 40},
        "preprocessing": text_contract,
        "preprocessing_sha256": preprocessing_sha256(text_contract),
        "pooling": "e5_avg",
        "prefix": "query: ",
        "max_length": 16,
        "rows": 18,
        "dimension": 3,
        "dtype": "float32",
        "extraction_code_commit": "4" * 40,
    }
    text_embedding.with_suffix(".receipt.json").write_text(
        json.dumps(text_receipt), encoding="utf-8"
    )

    candidate = CandidateConfig(
        name="cb_tiny_fusion",
        model="catboost",
        image_encoder="tiny_image",
        text_encoder="tiny_text",
    )
    test_plan = replace(
        config.test,
        fixed_candidates=(),
        paired_reference="cb_tiny_fusion",
        paired_comparisons=(),
    )
    config = replace(
        config,
        candidates=(candidate,),
        deployment_eligible_candidates=(candidate.name,),
        test=test_plan,
    )
    run_dir = tmp_path / "run"
    run_selection(config, run_dir=run_dir)
    run_locked_test(run_dir)

    image_model = tmp_path / "image.onnx"
    image_config = tmp_path / "preprocessor_config.json"
    text_dir = tmp_path / "text_export"
    text_dir.mkdir()
    image_model.write_bytes(b"synthetic image onnx")
    image_config.write_text("{}", encoding="utf-8")
    (text_dir / "model.onnx").write_bytes(b"synthetic text onnx")
    (text_dir / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(export_q2_model, "TARGET_CLASSES", ["class_0", "class_1"])
    output = tmp_path / "release-q2"
    result = export_q2_model.export_bundle(
        Namespace(
            run_dir=run_dir,
            policy="locked_test_complete",
            image_onnx=image_model,
            image_preprocessor=image_config,
            text_model_dir=text_dir,
            output_dir=output,
            model_name="synthetic-test-model",
            model_version="synthetic-q2-001",
        )
    )
    manifest = validate_export_manifest(
        output,
        expected_manifest_sha256=result["export_manifest_sha256"],
        expected_classes=["class_0", "class_1"],
        expected_model_version="synthetic-q2-001",
    )
    assert manifest["protocol"]["export_policy"] == "locked_test_complete"
    assert (
        manifest["protocol"]["deployment_seed_rule"]
        == "all_preregistered_seeds_equal_weight"
    )
    assert manifest["model"]["seeds"] == [1, 2, 3, 4, 5]
    assert manifest["model"]["ensemble_size"] == 5
    assert len(manifest["runtime"]["classifier_members"]) == 5
    assert manifest["model"]["checkpoint_tree_policy"] == (
        "full_early_stopped_trajectory_for_both_point_and_pgs"
    )
    assert all(
        member["tree_count"] > 0 for member in manifest["runtime"]["classifier_members"]
    )
    assert len(manifest["protocol"]["source_members"]) == 5
    assert manifest["model"]["classifier_feature_count"] == 7
    monkeypatch.setattr(q2_readiness, "TARGET_CLASSES", ["class_0", "class_1"])
    readiness_gate = q2_readiness._check_export_bundle(
        output,
        result["export_manifest_sha256"],
        run_dir,
    )
    assert readiness_gate.passed, readiness_gate.detail
