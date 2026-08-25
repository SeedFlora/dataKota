#!/usr/bin/env python3
"""Gate native CatBoost -> ONNX classifier parity on saved fused features.

Example:
    python tools/check_classifier_parity.py \
      --seed 13 --native artifacts/export/classifiers/seed_13.cbm \
      --onnx artifacts/export/classifiers/seed_13.onnx \
      --seed 42 --native artifacts/export/classifiers/seed_42.cbm \
      --onnx artifacts/export/classifiers/seed_42.onnx \
      --seed 73 --native artifacts/export/classifiers/seed_73.cbm \
      --onnx artifacts/export/classifiers/seed_73.onnx \
      --seed 101 --native artifacts/export/classifiers/seed_101.cbm \
      --onnx artifacts/export/classifiers/seed_101.onnx \
      --seed 137 --native artifacts/export/classifiers/seed_137.cbm \
      --onnx artifacts/export/classifiers/seed_137.onnx \
      --features artifacts/parity/fused_validation.npy \
      --test-ids artifacts/parity/locked_test_ids.json \
      --split-manifest artifacts/splits_q2/split_manifest.json \
      --class-map artifacts/splits_q2/class_map.json \
      --feature-receipt artifacts/parity/fused_features.receipt.json \
      --output artifacts/parity/classifier_report.json

The command exits non-zero when the probability or top-1 agreement gate fails.
Use a fixed, versioned feature sample and retain the JSON report with the paper
artifacts; do not quote parity from an unrecorded ad-hoc run.
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

from crm.deployment import (
    classifier_parity_report,
    equal_weight_probability_mean,
    normalize_probability_output,
    validate_probability_matrix,
)
from crm.export_contract import CLASSIFIER_PARITY_TOLERANCES
from crm.splitting import class_map_sha256

IMMUTABLE_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sample_ids(path: Path, *, id_column: str) -> list[str]:
    """Load ordered sample identifiers without silently discarding duplicates."""
    suffix = path.suffix.lower()
    if suffix == ".npy":
        values = np.load(path, allow_pickle=False)
        if values.ndim != 1:
            raise ValueError("NumPy test IDs must be one-dimensional")
        result = values.tolist()
    if suffix == ".json":
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
    elif suffix not in {".npy", ".json"}:
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
    test_record = manifest.get("outputs", {}).get("test", {})
    raw_test_path = test_record.get("path")
    if not raw_test_path or not test_record.get("sha256"):
        raise ValueError("split manifest does not bind the test CSV")
    test_csv = Path(raw_test_path)
    if not test_csv.is_absolute():
        test_csv = split_manifest_path.parent / test_csv
    if not test_csv.is_file() or sha256_file(test_csv) != test_record["sha256"]:
        raise ValueError("manifested test CSV is missing or has changed")
    supplied = load_sample_ids(test_ids_path, id_column=id_column)
    manifested = load_sample_ids(test_csv, id_column=id_column)
    if supplied != manifested:
        raise ValueError(
            "ordered parity IDs must equal every row of the manifested locked test CSV"
        )
    return manifest, supplied


def onnx_opsets(path: Path) -> list[dict[str, int | str]]:
    import onnx

    model = onnx.load_model(str(path), load_external_data=False)
    return [
        {"domain": item.domain or "ai.onnx", "version": int(item.version)}
        for item in model.opset_import
    ]


def validate_class_map(
    path: Path, class_count: int, split_manifest: dict
) -> tuple[list[str], str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("class map must be the canonical schema-version 1 object")
    classes = value.get("classes")
    if not isinstance(classes, list) or len(classes) != class_count:
        raise ValueError(f"class map must have {class_count} ordered class objects")
    ids = [item.get("label_id") if isinstance(item, dict) else None for item in classes]
    labels = [
        item.get("label_name") if isinstance(item, dict) else None for item in classes
    ]
    if ids != list(range(class_count)):
        raise ValueError("class-map IDs/order must be contiguous from zero")
    if any(not isinstance(label, str) or not label.strip() for label in labels):
        raise ValueError("class-map names must be non-empty strings")
    if len(set(labels)) != len(labels):
        raise ValueError("class-map names must be unique")
    semantic_digest = class_map_sha256(value)
    if value.get("sha256") != semantic_digest:
        raise ValueError("class-map semantic digest is invalid")
    manifested = split_manifest.get("class_map")
    if not isinstance(manifested, dict) or manifested.get("sha256") != semantic_digest:
        raise ValueError("class map differs from the split-manifest class contract")
    if class_map_sha256(manifested) != semantic_digest:
        raise ValueError("split-manifest class-map semantic digest is invalid")
    return labels, semantic_digest


def onnx_class_order(path: Path) -> list[int]:
    import onnx

    model = onnx.load_model(str(path), load_external_data=False)
    for node in model.graph.node:
        if node.op_type == "ZipMap":
            for attribute in node.attribute:
                if attribute.name == "classlabels_int64s":
                    return [int(value) for value in attribute.ints]
    raise ValueError("classifier ONNX graph has no explicit integer ZipMap class order")


def validate_feature_receipt(
    path: Path,
    *,
    features_path: Path,
    features: np.ndarray,
    rows: int,
    dimension: int,
    test_ids_hash: str,
    split_manifest_hash: str,
    class_map_digest: str,
    split_manifest: dict,
    split_manifest_path: Path,
) -> dict:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "feature_sample_sha256": sha256_file(features_path),
        "rows": rows,
        "dimension": dimension,
        "ordered_test_ids_sha256": test_ids_hash,
        "split_manifest_sha256": split_manifest_hash,
        "class_map_semantic_sha256": class_map_digest,
    }
    mismatched = {
        key: {"expected": value, "observed": receipt.get(key)}
        for key, value in expected.items()
        if receipt.get(key) != value
    }
    if mismatched:
        raise ValueError(f"feature extraction receipt mismatch: {mismatched}")
    if not IMMUTABLE_REVISION_RE.fullmatch(
        str(receipt.get("extraction_code_commit", ""))
    ):
        raise ValueError("feature receipt needs an immutable extraction code commit")
    if receipt.get("schema_version") != 2:
        raise ValueError("feature receipt schema_version must be 2")
    if (
        not isinstance(receipt.get("selected_candidate"), str)
        or not receipt["selected_candidate"].strip()
    ):
        raise ValueError("feature receipt must name the selected candidate")
    index_column = receipt.get("embedding_index_column")
    if (
        not isinstance(index_column, str)
        or not index_column
        or split_manifest.get("embedding_index", {}).get("column") != index_column
    ):
        raise ValueError(
            "feature receipt embedding-index column differs from the split manifest"
        )
    fusion = receipt.get("fusion")
    if not isinstance(fusion, dict):
        raise TypeError("feature receipt must declare the exact fusion operation")
    expected_fusion_keys = {
        "operation",
        "modality_order",
        "axis",
        "l2_per_modality",
        "l2_epsilon",
        "output_dtype",
    }
    if set(fusion) != expected_fusion_keys:
        raise ValueError("feature receipt fusion fields are incomplete/ambiguous")
    if (
        fusion.get("operation") != "concatenate"
        or fusion.get("modality_order") != ["image", "text"]
        or fusion.get("axis") != 1
        or type(fusion.get("l2_per_modality")) is not bool
        or fusion.get("l2_epsilon") != 1e-9
        or fusion.get("output_dtype") != "float32"
    ):
        raise ValueError("feature receipt does not reproduce the frozen fusion rule")
    sources = receipt.get("source_embeddings")
    if not isinstance(sources, dict) or set(sources) != {"image", "text"}:
        raise ValueError("feature receipt must bind exact image and text embeddings")

    test_record = split_manifest.get("outputs", {}).get("test", {})
    test_csv = Path(str(test_record.get("path", "")))
    if not test_csv.is_absolute():
        test_csv = split_manifest_path.parent / test_csv
    with test_csv.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or index_column not in reader.fieldnames:
            raise ValueError(f"manifested test CSV lacks {index_column!r}")
        try:
            indices = np.asarray(
                [int(row[index_column]) for row in reader], dtype=np.int64
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("test embedding indices must be integers") from exc
    if len(indices) != rows or (indices < 0).any():
        raise ValueError("test embedding indices do not align with feature rows")

    parts: list[np.ndarray] = []
    expected_source_keys = {
        "key",
        "encoder_name",
        "path",
        "sha256",
        "extraction_receipt_path",
        "extraction_receipt_sha256",
        "preprocessing_sha256",
        "dimension",
        "dtype",
    }
    for modality in fusion["modality_order"]:
        record = sources[modality]
        if not isinstance(record, dict) or set(record) != expected_source_keys:
            raise ValueError(
                f"source embedding {modality!r} fields are incomplete/ambiguous"
            )
        encoder_name = record.get("encoder_name")
        if (
            not isinstance(encoder_name, str)
            or not encoder_name
            or record.get("key") != f"{modality}:{encoder_name}"
        ):
            raise ValueError(f"source embedding {modality!r} identity is invalid")
        for hash_field in (
            "sha256",
            "extraction_receipt_sha256",
            "preprocessing_sha256",
        ):
            if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(hash_field, ""))):
                raise ValueError(
                    f"source embedding {modality!r} lacks {hash_field} binding"
                )
        source_path = Path(str(record.get("path", "")))
        extraction_path = Path(str(record.get("extraction_receipt_path", "")))
        if not source_path.is_absolute():
            source_path = path.parent / source_path
        if not extraction_path.is_absolute():
            extraction_path = path.parent / extraction_path
        if (
            not source_path.is_file()
            or source_path.is_symlink()
            or sha256_file(source_path) != record["sha256"]
        ):
            raise ValueError(f"source embedding {modality!r} file/hash differs")
        if (
            not extraction_path.is_file()
            or extraction_path.is_symlink()
            or sha256_file(extraction_path) != record["extraction_receipt_sha256"]
        ):
            raise ValueError(
                f"source embedding {modality!r} extraction receipt differs"
            )
        extraction = json.loads(extraction_path.read_text(encoding="utf-8"))
        if (
            extraction.get("embedding_sha256") != record["sha256"]
            or extraction.get("preprocessing_sha256") != record["preprocessing_sha256"]
            or extraction.get("encoder_name") != encoder_name
            or extraction.get("dimension") != record.get("dimension")
            or extraction.get("dtype") != record.get("dtype")
        ):
            raise ValueError(
                f"source embedding {modality!r} differs from its extraction receipt"
            )
        array = np.load(source_path, mmap_mode="r", allow_pickle=False)
        if (
            array.ndim != 2
            or array.shape[1] != record.get("dimension")
            or str(array.dtype) != record.get("dtype")
            or indices.max(initial=-1) >= array.shape[0]
        ):
            raise ValueError(f"source embedding {modality!r} shape/dtype is invalid")
        part = np.asarray(array[indices], dtype=np.float32)
        if not np.isfinite(part).all():
            raise ValueError(f"source embedding {modality!r} contains non-finite rows")
        if fusion["l2_per_modality"]:
            norms = np.linalg.norm(part, axis=1, keepdims=True)
            part = part / np.clip(norms, fusion["l2_epsilon"], None)
        parts.append(part)
    reconstructed = np.concatenate(parts, axis=1).astype(np.float32, copy=False)
    if reconstructed.shape != features.shape or not np.array_equal(
        reconstructed, features
    ):
        maximum_error = (
            float(np.max(np.abs(reconstructed - features)))
            if reconstructed.shape == features.shape
            else None
        )
        raise ValueError(
            "feature sample is not the deterministic selected embedding fusion; "
            f"maximum_absolute_error={maximum_error}"
        )
    return receipt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native",
        type=Path,
        action="append",
        required=True,
        help="CatBoost .cbm; repeat once per preregistered seed in frozen order",
    )
    parser.add_argument(
        "--onnx",
        type=Path,
        action="append",
        required=True,
        help="Classifier .onnx; repeat in the same seed order as --native",
    )
    parser.add_argument(
        "--seed",
        type=int,
        action="append",
        help="preregistered seed for each native/ONNX pair; repeat in frozen order",
    )
    parser.add_argument(
        "--features", type=Path, required=True, help="(N, D) fused float .npy"
    )
    parser.add_argument(
        "--test-ids",
        type=Path,
        required=True,
        help="ordered IDs corresponding one-for-one to feature rows",
    )
    parser.add_argument(
        "--split-manifest", type=Path, required=True, help="locked split manifest"
    )
    parser.add_argument(
        "--class-map", type=Path, required=True, help="frozen ordered class-map JSON"
    )
    parser.add_argument(
        "--feature-receipt",
        type=Path,
        required=True,
        help="receipt binding fused rows/order to locked test embeddings",
    )
    parser.add_argument("--class-count", type=int, default=9)
    parser.add_argument("--probability-tolerance", type=float, default=1e-5)
    parser.add_argument("--minimum-top1-agreement", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if {
        "probability_tolerance": args.probability_tolerance,
        "minimum_top1_agreement": args.minimum_top1_agreement,
    } != CLASSIFIER_PARITY_TOLERANCES:
        raise ValueError(
            "classifier parity tolerances must equal the frozen export policy"
        )
    import onnxruntime as ort
    from catboost import CatBoostClassifier

    features = np.load(args.features, allow_pickle=False)
    if features.ndim != 2:
        raise ValueError(f"features must have shape (N, D), got {features.shape}")
    features = features.astype(np.float32, copy=False)
    split_manifest, ordered_ids = validate_locked_test_ids(
        args.test_ids, args.split_manifest
    )
    if len(ordered_ids) != features.shape[0]:
        raise ValueError("test-ID count must equal the number of feature rows")
    labels, class_map_digest = validate_class_map(
        args.class_map, args.class_count, split_manifest
    )
    ordered_ids_digest = ordered_ids_sha256(ordered_ids)
    validate_feature_receipt(
        args.feature_receipt,
        features_path=args.features,
        features=features,
        rows=features.shape[0],
        dimension=features.shape[1],
        test_ids_hash=ordered_ids_digest,
        split_manifest_hash=sha256_file(args.split_manifest),
        class_map_digest=class_map_digest,
        split_manifest=split_manifest,
        split_manifest_path=args.split_manifest,
    )

    if len(args.native) != len(args.onnx):
        raise ValueError(
            "--native and --onnx must be repeated the same number of times"
        )
    if args.seed is not None and len(args.seed) != len(args.native):
        raise ValueError("--seed must be supplied once for every classifier pair")
    member_seeds = args.seed or list(range(len(args.native)))
    if len(set(member_seeds)) != len(member_seeds):
        raise ValueError("classifier member seeds must be distinct")
    expected_class_order = list(range(args.class_count))
    native_probability_members: list[np.ndarray] = []
    deployed_probability_members: list[np.ndarray] = []
    member_reports: list[dict] = []
    execution_providers: set[str] = set()
    opset_members: list[dict] = []
    for index, (native_path, onnx_path) in enumerate(
        zip(args.native, args.onnx, strict=True)
    ):
        native = CatBoostClassifier()
        native.load_model(str(native_path))
        native_class_order = [int(value) for value in native.classes_]
        if native_class_order != expected_class_order:
            raise ValueError(
                f"native member {index} class order {native_class_order} differs "
                f"from {expected_class_order}"
            )
        exported_class_order = onnx_class_order(onnx_path)
        if exported_class_order != expected_class_order:
            raise ValueError(
                f"ONNX member {index} class order {exported_class_order} differs "
                f"from {expected_class_order}"
            )
        native_probs = validate_probability_matrix(
            native.predict_proba(features), args.class_count
        )
        session = ort.InferenceSession(
            str(onnx_path), providers=["CPUExecutionProvider"]
        )
        model_input = session.get_inputs()[0]
        if (
            len(model_input.shape) == 2
            and isinstance(model_input.shape[1], int)
            and features.shape[1] != model_input.shape[1]
        ):
            raise ValueError(
                f"feature dimension {features.shape[1]} does not match ONNX member "
                f"{index} input {model_input.shape[1]}"
            )
        outputs = session.run(None, {model_input.name: features})
        deployed_probs = normalize_probability_output(
            outputs[-1], range(args.class_count)
        )
        member_report = classifier_parity_report(
            native_probs,
            deployed_probs,
            probability_tolerance=args.probability_tolerance,
            minimum_top1_agreement=args.minimum_top1_agreement,
        )
        native_probability_members.append(native_probs)
        deployed_probability_members.append(deployed_probs)
        execution_providers.update(session.get_providers())
        member_opsets = onnx_opsets(onnx_path)
        opset_members.append({"member_index": index, "imports": member_opsets})
        member_reports.append(
            {
                "member_index": index,
                "seed": int(member_seeds[index]),
                "native_model": str(native_path),
                "native_model_sha256": sha256_file(native_path),
                "onnx_model": str(onnx_path),
                "onnx_model_sha256": sha256_file(onnx_path),
                "native_class_order": native_class_order,
                "onnx_class_order": exported_class_order,
                "execution_providers": session.get_providers(),
                "onnx_opset_imports": member_opsets,
                **member_report.to_dict(),
            }
        )
    native_probs = equal_weight_probability_mean(
        native_probability_members,
        args.class_count,
        expected_members=len(member_reports),
    )
    deployed_probs = equal_weight_probability_mean(
        deployed_probability_members,
        args.class_count,
        expected_members=len(member_reports),
    )
    report = classifier_parity_report(
        native_probs,
        deployed_probs,
        probability_tolerance=args.probability_tolerance,
        minimum_top1_agreement=args.minimum_top1_agreement,
    )
    payload = {
        **report.to_dict(),
        "tolerance_source": "frozen_export_contract_v4",
        "ensemble_size": len(member_reports),
        "seeds": [int(seed) for seed in member_seeds],
        "probability_aggregation": "equal_weight_arithmetic_mean",
        "members": member_reports,
        "feature_sample": str(args.features),
        "feature_sample_sha256": sha256_file(args.features),
        "component": "classifier",
        "modality": "fused_features",
        "parity_scope": "equal_weight_native_and_onnx_seed_ensemble",
        "evaluation_split": "locked_test",
        "test_ids": str(args.test_ids),
        "test_ids_sha256": sha256_file(args.test_ids),
        "ordered_test_ids_sha256": ordered_ids_digest,
        "split_manifest": str(args.split_manifest),
        "split_manifest_sha256": sha256_file(args.split_manifest),
        "class_map": str(args.class_map),
        "class_map_sha256": sha256_file(args.class_map),
        "class_map_semantic_sha256": class_map_digest,
        "ordered_class_names": labels,
        "native_class_order": expected_class_order,
        "onnx_class_order": expected_class_order,
        "feature_receipt": str(args.feature_receipt),
        "feature_receipt_sha256": sha256_file(args.feature_receipt),
        "execution_providers": sorted(execution_providers),
        "onnx_opset_imports": opset_members,
        "software_versions": {
            "numpy": np.__version__,
            "onnxruntime": ort.__version__,
            "catboost": metadata.version("catboost"),
            "onnx": metadata.version("onnx"),
        },
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
