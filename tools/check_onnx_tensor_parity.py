#!/usr/bin/env python3
"""Gate a single ONNX component against saved reference tensor outputs.

Store the exact native-framework inputs in an ``.npz`` whose keys match the
ONNX input names, and the native output in ``.npy``. This works for both image
and text encoders and avoids needing PyTorch in the deployment environment.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from importlib import metadata
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.export_contract import ENCODER_TENSOR_PARITY_TOLERANCES
from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
)
from crm.preprocessing_contract import (
    validate_preprocessing_contract as validate_modality_preprocessing,
)

IMMUTABLE_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def onnx_component_hashes(model_path: Path) -> dict[str, str]:
    """Hash the graph and conventional sibling external-data artifacts."""
    paths = [model_path]
    for candidate in (
        model_path.with_name(f"{model_path.name}_data"),
        model_path.with_suffix(f"{model_path.suffix}.data"),
    ):
        if candidate.is_file() and candidate not in paths:
            paths.append(candidate)
    return {path.name: sha256_file(path) for path in paths}


def load_sample_ids(path: Path, *, id_column: str) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".npy":
        values = np.load(path, allow_pickle=False)
        if values.ndim != 1:
            raise ValueError("NumPy test IDs must be one-dimensional")
        result = values.tolist()
    elif suffix == ".json":
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, list):
            result = value
        elif isinstance(value, dict) and isinstance(value.get("ids"), list):
            result = value["ids"]
        else:
            raise ValueError(
                "JSON test IDs must be a list or an object with an ids list"
            )
    elif suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or id_column not in reader.fieldnames:
                raise ValueError(f"CSV test IDs must contain {id_column!r}")
            result = [row[id_column] for row in reader]
    else:
        result = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    normalized = [str(value) for value in result]
    if not normalized or any(not value for value in normalized):
        raise ValueError("test IDs must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("test IDs must be unique")
    return normalized


def ordered_ids_sha256(ids: list[str]) -> str:
    encoded = json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_locked_test_ids(
    test_ids_path: Path, split_manifest_path: Path
) -> tuple[dict, list[str]]:
    manifest = json.loads(split_manifest_path.read_text(encoding="utf-8"))
    if manifest.get("strategy") != "grouped_strict_temporal_holdout":
        raise ValueError("split manifest is not a grouped strict temporal holdout")
    id_column = manifest.get("parameters", {}).get("id_column")
    if not isinstance(id_column, str) or not id_column:
        raise ValueError("split manifest does not declare parameters.id_column")
    record = manifest.get("outputs", {}).get("test", {})
    raw_path = record.get("path")
    if not raw_path or not record.get("sha256"):
        raise ValueError("split manifest does not bind the test CSV")
    test_csv = Path(raw_path)
    if not test_csv.is_absolute():
        test_csv = split_manifest_path.parent / test_csv
    if not test_csv.is_file() or sha256_file(test_csv) != record["sha256"]:
        raise ValueError("manifested test CSV is missing or has changed")
    supplied = load_sample_ids(test_ids_path, id_column=id_column)
    manifested = load_sample_ids(test_csv, id_column=id_column)
    if supplied != manifested:
        raise ValueError(
            "ordered parity IDs must equal every row of the manifested locked test CSV"
        )
    return manifest, supplied


def validate_preprocessing_contract(
    path: Path,
    *,
    component: str,
    input_path: Path,
    reference_path: Path,
    rows: int,
    ordered_ids_digest: str,
    split_manifest_digest: str,
) -> dict:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "component": component,
        "tensor_input_sha256": sha256_file(input_path),
        "native_reference_sha256": sha256_file(reference_path),
        "rows": rows,
        "ordered_test_ids_sha256": ordered_ids_digest,
        "split_manifest_sha256": split_manifest_digest,
    }
    mismatched = {
        key: {"expected": value, "observed": receipt.get(key)}
        for key, value in expected.items()
        if receipt.get(key) != value
    }
    if mismatched:
        raise ValueError(f"preprocessing contract mismatch: {mismatched}")
    encoder = receipt.get("encoder")
    encoder_name = receipt.get("encoder_name")
    if not isinstance(encoder_name, str) or not encoder_name.strip():
        raise ValueError("preprocessing contract must name the selected encoder")
    if not isinstance(encoder, dict) or not str(encoder.get("repository", "")).strip():
        raise ValueError("preprocessing contract must name the encoder repository")
    if not IMMUTABLE_REVISION_RE.fullmatch(str(encoder.get("revision", ""))):
        raise ValueError("encoder revision must be an immutable 40-64 hex commit")
    if not IMMUTABLE_REVISION_RE.fullmatch(
        str(receipt.get("extraction_code_commit", ""))
    ):
        raise ValueError("extraction code commit must be immutable")
    if not str(receipt.get("pooling", "")).strip():
        raise ValueError("pooling must be explicit")
    if component == "text_encoder":
        if not isinstance(receipt.get("prefix"), str):
            raise ValueError("text prefix must be explicit (empty is allowed)")
        if not isinstance(receipt.get("max_length"), int) or receipt["max_length"] < 1:
            raise ValueError("text max_length must be a positive integer")
    elif receipt.get("prefix") is not None or receipt.get("max_length") is not None:
        raise ValueError("image prefix/max_length must be null")
    modality = "text" if component == "text_encoder" else "image"
    try:
        validate_modality_preprocessing(
            receipt.get("preprocessing"),
            modality=modality,
            pooling=receipt.get("pooling"),
            prefix=receipt.get("prefix"),
            max_length=receipt.get("max_length"),
            output_dtype=receipt.get("embedding_dtype"),
        )
    except PreprocessingContractError as exc:
        raise ValueError(f"preprocessing contract is incomplete: {exc}") from exc
    declared_hash = receipt.get("preprocessing_sha256")
    if (
        not isinstance(declared_hash, str)
        or preprocessing_sha256(receipt["preprocessing"]) != declared_hash
    ):
        raise ValueError("preprocessing semantic digest mismatch")
    for file_field, hash_field in (
        ("embedding_cache", "embedding_cache_sha256"),
        (
            "embedding_extraction_receipt",
            "embedding_extraction_receipt_sha256",
        ),
    ):
        raw_file = receipt.get(file_field)
        expected_hash = receipt.get(hash_field)
        if not isinstance(raw_file, str) or not raw_file.strip():
            raise ValueError(f"{file_field} must identify the selected extraction file")
        if not isinstance(expected_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise ValueError(f"{hash_field} must be a lowercase SHA-256 digest")
        linked = Path(raw_file)
        if not linked.is_absolute():
            linked = path.parent / linked
        linked = linked.resolve()
        if not linked.is_file() or linked.is_symlink():
            raise ValueError(f"{file_field} is missing or not a regular file")
        if sha256_file(linked) != expected_hash:
            raise ValueError(f"{file_field} differs from its declared SHA-256")
    index_column = receipt.get("embedding_index_column")
    if not isinstance(index_column, str) or not index_column.strip():
        raise ValueError("embedding_index_column must be explicit")

    extraction_path = Path(receipt["embedding_extraction_receipt"])
    if not extraction_path.is_absolute():
        extraction_path = path.parent / extraction_path
    extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
    extraction_expected = {
        "schema_version": 2,
        "modality": modality,
        "encoder_name": encoder_name,
        "embedding_sha256": receipt["embedding_cache_sha256"],
        "encoder": encoder,
        "extraction_code_commit": receipt.get("extraction_code_commit"),
        "preprocessing": receipt.get("preprocessing"),
        "preprocessing_sha256": receipt.get("preprocessing_sha256"),
        "pooling": receipt.get("pooling"),
        "prefix": receipt.get("prefix"),
        "max_length": receipt.get("max_length"),
        "dtype": receipt.get("embedding_dtype"),
        "embedding_index_column": index_column,
    }
    extraction_mismatches = {
        key: {"expected": expected, "observed": extraction.get(key)}
        for key, expected in extraction_expected.items()
        if extraction.get(key) != expected
    }
    if extraction_mismatches:
        raise ValueError(
            "parity preprocessing differs from the selected embedding extraction "
            f"receipt: {extraction_mismatches}"
        )
    return receipt


def _postprocess_embedding_output(
    value: np.ndarray,
    *,
    contract: dict,
    feed: dict[str, np.ndarray],
) -> np.ndarray:
    """Apply the receipt-bound pooling/normalization to an encoder tensor."""
    output = np.asarray(value)
    modality = "text" if contract["component"] == "text_encoder" else "image"
    pooling = str(contract["pooling"])
    if output.ndim == 3:
        if pooling == "cls":
            output = output[:, 0]
        elif modality == "text" and pooling in {"mean", "e5_avg"}:
            mask = feed.get("attention_mask")
            if mask is None or mask.shape != output.shape[:2]:
                raise ValueError(
                    "text mean pooling requires an aligned attention_mask input"
                )
            weights = np.asarray(mask, dtype=np.float64)[..., None]
            denominator = weights.sum(axis=1)
            if (denominator <= 0).any():
                raise ValueError("text attention_mask contains an empty sequence")
            output = (output.astype(np.float64) * weights).sum(axis=1) / denominator
        elif modality == "image" and pooling == "mean":
            output = output.astype(np.float64).mean(axis=1)
        else:
            raise ValueError(
                f"cannot reproduce {modality} pooling {pooling!r} from rank-3 output"
            )
    if output.ndim != 2:
        raise ValueError(
            f"postprocessed encoder output must have shape (rows, dimension), got "
            f"{output.shape}"
        )
    values = np.asarray(output, dtype=np.float64)
    if contract["preprocessing"]["embedding"]["l2_normalize"]:
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if (norms <= 0.0).any():
            raise ValueError("cannot L2-normalize a zero encoder output row")
        values = values / norms
    return values


def _selected_embedding_rows(
    contract: dict,
    *,
    split_manifest: dict,
    split_manifest_path: Path,
    contract_path: Path,
) -> np.ndarray:
    index_column = contract["embedding_index_column"]
    manifested_index = split_manifest.get("embedding_index", {}).get("column")
    if manifested_index != index_column:
        raise ValueError(
            "parity embedding_index_column differs from the split manifest"
        )
    test_record = split_manifest.get("outputs", {}).get("test", {})
    test_csv = Path(str(test_record.get("path", "")))
    if not test_csv.is_absolute():
        test_csv = split_manifest_path.parent / test_csv
    with test_csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or index_column not in reader.fieldnames:
            raise ValueError(
                f"manifested test CSV lacks embedding index {index_column!r}"
            )
        try:
            indices = np.asarray(
                [int(row[index_column]) for row in reader], dtype=np.int64
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("test embedding indices must be integers") from exc
    if (indices < 0).any():
        raise ValueError("test embedding indices must be non-negative")
    cache_path = Path(contract["embedding_cache"])
    if not cache_path.is_absolute():
        cache_path = contract_path.parent / cache_path
    cache = np.load(cache_path.resolve(), mmap_mode="r", allow_pickle=False)
    if cache.ndim != 2 or indices.max(initial=-1) >= cache.shape[0]:
        raise ValueError("selected embedding cache cannot satisfy test row indices")
    return np.asarray(cache[indices], dtype=np.float64)


def onnx_opsets(path: Path) -> list[dict[str, int | str]]:
    import onnx

    model = onnx.load_model(str(path), load_external_data=False)
    return [
        {"domain": item.domain or "ai.onnx", "version": int(item.version)}
        for item in model.opset_import
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True, help="Named .npz inputs")
    parser.add_argument("--reference", type=Path, required=True, help="Reference .npy")
    parser.add_argument(
        "--component",
        choices=("image_encoder", "text_encoder"),
        required=True,
    )
    parser.add_argument(
        "--test-ids",
        type=Path,
        required=True,
        help="ordered IDs corresponding one-for-one to tensor rows",
    )
    parser.add_argument("--split-manifest", type=Path, required=True)
    parser.add_argument(
        "--preprocessing-contract",
        type=Path,
        required=True,
        help="JSON receipt freezing encoder revision, preprocessing/tokenization, and pooling",
    )
    parser.add_argument("--output-index", type=int, default=0)
    parser.add_argument("--absolute-tolerance", type=float, default=1e-5)
    parser.add_argument("--minimum-cosine-similarity", type=float, default=0.99999)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    import onnxruntime as ort

    if {
        "absolute_tolerance": args.absolute_tolerance,
        "minimum_cosine_similarity": args.minimum_cosine_similarity,
    } != ENCODER_TENSOR_PARITY_TOLERANCES:
        raise ValueError(
            "encoder parity tolerances must equal the frozen export policy"
        )
    session = ort.InferenceSession(
        str(args.onnx),
        providers=["CPUExecutionProvider"],
    )
    with np.load(args.inputs, allow_pickle=False) as archive:
        available = set(archive.files)
        required = {model_input.name for model_input in session.get_inputs()}
        if available != required:
            raise ValueError(
                f"input keys must exactly match ONNX inputs: expected {required}, "
                f"got {available}"
            )
        feed = {name: archive[name] for name in required}

    deployed = np.asarray(session.run(None, feed)[args.output_index])
    reference = np.asarray(np.load(args.reference, allow_pickle=False))
    if reference.ndim == 0 or reference.shape[0] == 0:
        raise ValueError("reference output must contain at least one sample")
    if reference.shape != deployed.shape:
        raise ValueError(
            f"output shape mismatch: reference {reference.shape}, ONNX {deployed.shape}"
        )
    if not np.isfinite(reference).all() or not np.isfinite(deployed).all():
        raise ValueError("reference or ONNX output contains NaN/infinite values")
    split_manifest, ordered_ids = validate_locked_test_ids(
        args.test_ids, args.split_manifest
    )
    if len(ordered_ids) != reference.shape[0]:
        raise ValueError("test-ID count must equal the number of reference rows")
    ordered_ids_digest = ordered_ids_sha256(ordered_ids)
    contract = validate_preprocessing_contract(
        args.preprocessing_contract,
        component=args.component,
        input_path=args.inputs,
        reference_path=args.reference,
        rows=reference.shape[0],
        ordered_ids_digest=ordered_ids_digest,
        split_manifest_digest=sha256_file(args.split_manifest),
    )

    reference = _postprocess_embedding_output(reference, contract=contract, feed=feed)
    deployed = _postprocess_embedding_output(deployed, contract=contract, feed=feed)
    selected_cache_rows = _selected_embedding_rows(
        contract,
        split_manifest=split_manifest,
        split_manifest_path=args.split_manifest,
        contract_path=args.preprocessing_contract,
    )
    if selected_cache_rows.shape != reference.shape:
        raise ValueError(
            "selected extraction-cache rows differ in shape from the native "
            f"reference: {selected_cache_rows.shape} != {reference.shape}"
        )
    cache_error = np.abs(selected_cache_rows - reference.astype(np.float64))
    cache_max_error = float(cache_error.max(initial=0.0))
    if cache_max_error > 1e-6:
        raise ValueError(
            "native reference is not the selected extraction-cache output; "
            f"maximum absolute difference is {cache_max_error}"
        )

    error = np.abs(reference.astype(np.float64) - deployed.astype(np.float64))
    max_error = float(error.max(initial=0.0))
    mean_error = float(error.mean()) if error.size else 0.0

    ref_rows = reference.reshape(reference.shape[0], -1).astype(np.float64)
    dep_rows = deployed.reshape(deployed.shape[0], -1).astype(np.float64)
    denominator = np.linalg.norm(ref_rows, axis=1) * np.linalg.norm(dep_rows, axis=1)
    cosine = np.divide(
        np.sum(ref_rows * dep_rows, axis=1),
        denominator,
        out=np.ones_like(denominator),
        where=denominator > 0,
    )
    minimum_cosine = float(cosine.min(initial=1.0))
    passed = (
        max_error <= args.absolute_tolerance
        and minimum_cosine >= args.minimum_cosine_similarity
    )
    payload = {
        "samples": int(reference.shape[0]),
        "shape": list(reference.shape),
        "max_absolute_error": max_error,
        "mean_absolute_error": mean_error,
        "p50_absolute_error": float(np.percentile(error, 50)),
        "p95_absolute_error": float(np.percentile(error, 95)),
        "p99_absolute_error": float(np.percentile(error, 99)),
        "minimum_row_cosine_similarity": minimum_cosine,
        "reference_cache_max_absolute_error": cache_max_error,
        "reference_cache_tolerance": 1e-6,
        "absolute_tolerance": args.absolute_tolerance,
        "minimum_cosine_similarity": args.minimum_cosine_similarity,
        "tolerance_source": "frozen_export_contract_v4",
        "passed": passed,
        "onnx_model": str(args.onnx),
        "onnx_component_sha256": onnx_component_hashes(args.onnx),
        "input_sample": str(args.inputs),
        "input_sample_sha256": sha256_file(args.inputs),
        "reference_output": str(args.reference),
        "reference_output_sha256": sha256_file(args.reference),
        "component": args.component,
        "modality": "image" if args.component == "image_encoder" else "text",
        "parity_scope": "native_reference_vs_onnx_at_tensor_boundary",
        "raw_input_end_to_end": False,
        "evaluation_split": "locked_test",
        "test_ids": str(args.test_ids),
        "test_ids_sha256": sha256_file(args.test_ids),
        "ordered_test_ids_sha256": ordered_ids_digest,
        "split_manifest": str(args.split_manifest),
        "split_manifest_sha256": sha256_file(args.split_manifest),
        "preprocessing_contract": str(args.preprocessing_contract),
        "preprocessing_contract_sha256": sha256_file(args.preprocessing_contract),
        "encoder_name": contract["encoder_name"],
        "embedding_cache": contract["embedding_cache"],
        "embedding_cache_sha256": contract["embedding_cache_sha256"],
        "embedding_extraction_receipt": contract["embedding_extraction_receipt"],
        "embedding_extraction_receipt_sha256": contract[
            "embedding_extraction_receipt_sha256"
        ],
        "execution_providers": session.get_providers(),
        "onnx_opset_imports": onnx_opsets(args.onnx),
        "software_versions": {
            "numpy": np.__version__,
            "onnxruntime": ort.__version__,
            "onnx": metadata.version("onnx"),
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
