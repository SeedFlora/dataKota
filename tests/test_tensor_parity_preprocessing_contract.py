from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import tools.check_onnx_tensor_parity as tensor_parity
from crm.preprocessing_contract import preprocessing_sha256
from tests.preprocessing_examples import text_preprocessing
from tools.check_onnx_tensor_parity import (
    sha256_file,
    validate_preprocessing_contract,
)


def _contract(tmp_path: Path) -> tuple[Path, Path, Path]:
    inputs = tmp_path / "inputs.npz"
    reference = tmp_path / "reference.npy"
    inputs.write_bytes(b"tensor-input")
    reference.write_bytes(b"native-output")
    embedding_cache = tmp_path / "selected_text.npy"
    np.save(embedding_cache, np.zeros((2, 3), dtype=np.float32), allow_pickle=False)
    preprocessing = text_preprocessing()
    encoder = {
        "repository": "example/tiny-text",
        "revision": "3" * 40,
    }
    extraction_receipt = {
        "schema_version": 2,
        "modality": "text",
        "encoder_name": "tiny_text",
        "embedding_sha256": sha256_file(embedding_cache),
        "encoder": encoder,
        "extraction_code_commit": "4" * 40,
        "preprocessing": preprocessing,
        "preprocessing_sha256": preprocessing_sha256(preprocessing),
        "pooling": "e5_avg",
        "prefix": "query: ",
        "max_length": 16,
        "dtype": "float32",
        "embedding_index_column": "embedding_index",
    }
    extraction_path = tmp_path / "selected_text.receipt.json"
    extraction_path.write_text(json.dumps(extraction_receipt), encoding="utf-8")
    contract = {
        "component": "text_encoder",
        "encoder_name": "tiny_text",
        "tensor_input_sha256": sha256_file(inputs),
        "native_reference_sha256": sha256_file(reference),
        "rows": 2,
        "ordered_test_ids_sha256": "a" * 64,
        "split_manifest_sha256": "b" * 64,
        "encoder": encoder,
        "extraction_code_commit": "4" * 40,
        "preprocessing": preprocessing,
        "preprocessing_sha256": preprocessing_sha256(preprocessing),
        "pooling": "e5_avg",
        "prefix": "query: ",
        "max_length": 16,
        "embedding_dtype": "float32",
        "embedding_cache": embedding_cache.name,
        "embedding_cache_sha256": sha256_file(embedding_cache),
        "embedding_extraction_receipt": extraction_path.name,
        "embedding_extraction_receipt_sha256": sha256_file(extraction_path),
        "embedding_index_column": "embedding_index",
    }
    path = tmp_path / "preprocessing.json"
    path.write_text(json.dumps(contract), encoding="utf-8")
    return path, inputs, reference


def test_tensor_parity_contract_requires_complete_extraction_preprocessing(
    tmp_path: Path,
) -> None:
    path, inputs, reference = _contract(tmp_path)
    receipt = validate_preprocessing_contract(
        path,
        component="text_encoder",
        input_path=inputs,
        reference_path=reference,
        rows=2,
        ordered_ids_digest="a" * 64,
        split_manifest_digest="b" * 64,
    )
    assert receipt["preprocessing_sha256"]


def test_tensor_parity_contract_rejects_missing_cleaning_policy(
    tmp_path: Path,
) -> None:
    path, inputs, reference = _contract(tmp_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    del receipt["preprocessing"]["cleaning"]["url_policy"]
    receipt["preprocessing_sha256"] = preprocessing_sha256(receipt["preprocessing"])
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="url_policy"):
        validate_preprocessing_contract(
            path,
            component="text_encoder",
            input_path=inputs,
            reference_path=reference,
            rows=2,
            ordered_ids_digest="a" * 64,
            split_manifest_digest="b" * 64,
        )


def test_tensor_parity_main_binds_reference_to_selected_embedding_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    onnx_path = tmp_path / "model.onnx"
    onnx_path.write_bytes(b"synthetic-onnx")
    inputs_path = tmp_path / "inputs.npz"
    np.savez(
        inputs_path,
        input_ids=np.array([[1, 2], [3, 4]], dtype=np.int64),
        attention_mask=np.ones((2, 2), dtype=np.int64),
    )
    reference = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    reference_path = tmp_path / "reference.npy"
    cache_path = tmp_path / "selected_text.npy"
    np.save(reference_path, reference, allow_pickle=False)
    np.save(cache_path, reference, allow_pickle=False)
    test_csv = tmp_path / "test.csv"
    test_csv.write_text("row_id,embedding_index\na,0\nb,1\n", encoding="utf-8")
    split_manifest = {
        "strategy": "grouped_strict_temporal_holdout",
        "parameters": {"id_column": "row_id"},
        "embedding_index": {"column": "embedding_index"},
        "outputs": {"test": {"path": test_csv.name, "sha256": sha256_file(test_csv)}},
    }
    split_path = tmp_path / "split_manifest.json"
    split_path.write_text(json.dumps(split_manifest), encoding="utf-8")
    ids_path = tmp_path / "ids.json"
    ids_path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    preprocessing = text_preprocessing()
    encoder = {"repository": "example/tiny-text", "revision": "3" * 40}
    extraction = {
        "schema_version": 2,
        "modality": "text",
        "encoder_name": "tiny_text",
        "embedding_sha256": sha256_file(cache_path),
        "encoder": encoder,
        "extraction_code_commit": "4" * 40,
        "preprocessing": preprocessing,
        "preprocessing_sha256": preprocessing_sha256(preprocessing),
        "pooling": "e5_avg",
        "prefix": "query: ",
        "max_length": 16,
        "dtype": "float32",
        "embedding_index_column": "embedding_index",
    }
    extraction_path = tmp_path / "selected_text.receipt.json"
    extraction_path.write_text(json.dumps(extraction), encoding="utf-8")
    contract = {
        "component": "text_encoder",
        "encoder_name": "tiny_text",
        "tensor_input_sha256": sha256_file(inputs_path),
        "native_reference_sha256": sha256_file(reference_path),
        "rows": 2,
        "ordered_test_ids_sha256": tensor_parity.ordered_ids_sha256(["a", "b"]),
        "split_manifest_sha256": sha256_file(split_path),
        "encoder": encoder,
        "extraction_code_commit": "4" * 40,
        "preprocessing": preprocessing,
        "preprocessing_sha256": preprocessing_sha256(preprocessing),
        "pooling": "e5_avg",
        "prefix": "query: ",
        "max_length": 16,
        "embedding_dtype": "float32",
        "embedding_cache": cache_path.name,
        "embedding_cache_sha256": sha256_file(cache_path),
        "embedding_extraction_receipt": extraction_path.name,
        "embedding_extraction_receipt_sha256": sha256_file(extraction_path),
        "embedding_index_column": "embedding_index",
    }
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    report_path = tmp_path / "report.json"

    class FakeSession:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_inputs(self):
            return [
                SimpleNamespace(name="input_ids"),
                SimpleNamespace(name="attention_mask"),
            ]

        def run(self, *_args, **_kwargs):
            return [reference]

        def get_providers(self):
            return ["CPUExecutionProvider"]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=FakeSession, __version__="test"),
    )
    monkeypatch.setattr(tensor_parity, "onnx_opsets", lambda _path: [])
    monkeypatch.setattr(tensor_parity.metadata, "version", lambda _name: "test")
    monkeypatch.setattr(
        tensor_parity,
        "parse_args",
        lambda: Namespace(
            onnx=onnx_path,
            inputs=inputs_path,
            reference=reference_path,
            component="text_encoder",
            test_ids=ids_path,
            split_manifest=split_path,
            preprocessing_contract=contract_path,
            output_index=0,
            absolute_tolerance=1e-5,
            minimum_cosine_similarity=0.99999,
            report=report_path,
        ),
    )

    assert tensor_parity.main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["reference_cache_max_absolute_error"] == 0.0
    assert report["embedding_cache_sha256"] == sha256_file(cache_path)


def test_tensor_parity_contract_requires_top_level_embedding_dtype(
    tmp_path: Path,
) -> None:
    path, inputs, reference = _contract(tmp_path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    del receipt["embedding_dtype"]
    path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="output_dtype differs"):
        validate_preprocessing_contract(
            path,
            component="text_encoder",
            input_path=inputs,
            reference_path=reference,
            rows=2,
            ordered_ids_digest="a" * 64,
            split_manifest_digest="b" * 64,
        )
