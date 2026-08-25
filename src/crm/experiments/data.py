"""Leakage guards, immutable input fingerprints, and embedding access."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from crm.preprocessing_contract import (
    PreprocessingContractError,
    preprocessing_sha256,
    validate_preprocessing_contract,
)
from crm.splitting import (
    SplitBuildError,
    class_map_sha256,
    validate_split_preregistration,
)

from .config import CandidateConfig, ExperimentConfig


class DataProtocolError(RuntimeError):
    """Raised when split or feature integrity would invalidate evaluation."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_IMMUTABLE_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)


@dataclass(frozen=True)
class SplitBundle:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame | None = None


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def file_fingerprint(path: Path, *, content_hash: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise DataProtocolError(f"required input does not exist: {path}")
    stat = path.stat()
    fingerprint: dict[str, Any] = {
        "path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if content_hash:
        fingerprint["sha256"] = sha256_file(path)
    return fingerprint


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise DataProtocolError(f"{field} must be a 64-character SHA-256 digest")
    return value.lower()


def _validate_embedding_receipt(
    embedding_path: Path,
    *,
    modality: str,
    encoder_name: str,
    split_manifest: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Validate an embedding cache's immutable extraction provenance."""
    receipt_path = embedding_path.with_suffix(".receipt.json")
    if not receipt_path.is_file():
        raise DataProtocolError(
            f"missing extraction receipt for {modality}:{encoder_name}: "
            f"{receipt_path}. A .npy hash alone is insufficient provenance."
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DataProtocolError(
            f"invalid embedding extraction receipt: {receipt_path}"
        ) from exc
    if not isinstance(receipt, dict):
        raise DataProtocolError(f"embedding receipt must be an object: {receipt_path}")

    expected_scalars = {
        "schema_version": 2,
        "modality": modality,
        "encoder_name": encoder_name,
        "embedding_file": embedding_path.name,
    }
    for field, expected in expected_scalars.items():
        if receipt.get(field) != expected:
            raise DataProtocolError(
                f"{receipt_path.name} {field!r} must be {expected!r}, "
                f"got {receipt.get(field)!r}"
            )

    expected_embedding_hash = _require_sha256(
        receipt.get("embedding_sha256"),
        f"{receipt_path.name}.embedding_sha256",
    )
    if sha256_file(embedding_path) != expected_embedding_hash:
        raise DataProtocolError(
            f"{embedding_path} does not match its extraction receipt hash"
        )

    source = split_manifest.get("source")
    embedding_index = split_manifest.get("embedding_index")
    if not isinstance(source, Mapping) or not isinstance(embedding_index, Mapping):
        raise DataProtocolError(
            "split manifest must bind source and embedding-index provenance"
        )
    source_hash = _require_sha256(source.get("sha256"), "split_manifest.source.sha256")
    source_order_hash = _require_sha256(
        embedding_index.get("source_order_sha256"),
        "split_manifest.embedding_index.source_order_sha256",
    )
    mapping_hash = _require_sha256(
        embedding_index.get("mapping_sha256"),
        "split_manifest.embedding_index.mapping_sha256",
    )
    if receipt.get("embedding_index_column") != embedding_index.get("column"):
        raise DataProtocolError(
            f"{receipt_path.name} embedding-index column differs from the split manifest"
        )
    if (
        _require_sha256(
            receipt.get("embedding_index_mapping_sha256"),
            f"{receipt_path.name}.embedding_index_mapping_sha256",
        )
        != mapping_hash
    ):
        raise DataProtocolError(
            f"{receipt_path.name} embedding-index mapping differs from the split manifest"
        )
    if (
        _require_sha256(
            receipt.get("source_snapshot_sha256"),
            f"{receipt_path.name}.source_snapshot_sha256",
        )
        != source_hash
    ):
        raise DataProtocolError(
            f"{receipt_path.name} was not extracted from the manifested source snapshot"
        )
    if (
        _require_sha256(
            receipt.get("source_row_order_sha256"),
            f"{receipt_path.name}.source_row_order_sha256",
        )
        != source_order_hash
    ):
        raise DataProtocolError(
            f"{receipt_path.name} source row order differs from the split manifest"
        )

    encoder = receipt.get("encoder")
    if not isinstance(encoder, Mapping):
        raise DataProtocolError(f"{receipt_path.name}.encoder must be an object")
    repository = encoder.get("repository")
    revision = encoder.get("revision")
    if not isinstance(repository, str) or not repository.strip():
        raise DataProtocolError(
            f"{receipt_path.name}.encoder.repository must be non-empty"
        )
    if not isinstance(revision, str) or not _IMMUTABLE_REVISION_RE.fullmatch(revision):
        raise DataProtocolError(
            f"{receipt_path.name}.encoder.revision must be an exact 40-64 hex commit, "
            "not a mutable branch/tag"
        )
    code_commit = receipt.get("extraction_code_commit")
    if not isinstance(code_commit, str) or not _IMMUTABLE_REVISION_RE.fullmatch(
        code_commit
    ):
        raise DataProtocolError(
            f"{receipt_path.name}.extraction_code_commit must be a 40-64 hex commit"
        )
    pooling = receipt.get("pooling")
    if not isinstance(pooling, str) or not pooling.strip():
        raise DataProtocolError(f"{receipt_path.name}.pooling must be non-empty")
    if "prefix" not in receipt or "max_length" not in receipt:
        raise DataProtocolError(
            f"{receipt_path.name} must declare prefix and max_length (null when "
            "not applicable)"
        )
    if modality == "text":
        if not isinstance(receipt["prefix"], str):
            raise DataProtocolError(f"{receipt_path.name}.prefix must be a string")
        if not isinstance(receipt["max_length"], int) or receipt["max_length"] < 1:
            raise DataProtocolError(
                f"{receipt_path.name}.max_length must be a positive integer"
            )
    elif receipt["prefix"] is not None or receipt["max_length"] is not None:
        raise DataProtocolError(
            f"{receipt_path.name} image prefix/max_length must be null"
        )
    preprocessing = receipt.get("preprocessing")
    try:
        validate_preprocessing_contract(
            preprocessing,
            modality=modality,
            pooling=pooling,
            prefix=receipt["prefix"],
            max_length=receipt["max_length"],
            output_dtype=receipt.get("dtype"),
        )
    except PreprocessingContractError as exc:
        raise DataProtocolError(
            f"{receipt_path.name} preprocessing contract: {exc}"
        ) from exc
    declared_preprocessing_hash = _require_sha256(
        receipt.get("preprocessing_sha256"),
        f"{receipt_path.name}.preprocessing_sha256",
    )
    observed_preprocessing_hash = preprocessing_sha256(preprocessing)
    if declared_preprocessing_hash != observed_preprocessing_hash:
        raise DataProtocolError(
            f"{receipt_path.name}.preprocessing_sha256 semantic digest mismatch"
        )

    array = np.load(embedding_path, mmap_mode="r")
    if array.ndim != 2 or array.shape[1] < 1:
        raise DataProtocolError(
            f"{embedding_path} must have shape (rows, features), got {array.shape}"
        )
    expected_rows = source.get("rows")
    if type(expected_rows) is not int or expected_rows < 1:
        raise DataProtocolError("split_manifest.source.rows must be a positive integer")
    if (
        type(receipt.get("rows")) is not int
        or type(receipt.get("dimension")) is not int
    ):
        raise DataProtocolError(
            f"{receipt_path.name} rows/dimension must be positive integers"
        )
    if receipt["rows"] < 1 or receipt["dimension"] < 1:
        raise DataProtocolError(
            f"{receipt_path.name} rows/dimension must be positive integers"
        )
    receipt_shape = (receipt.get("rows"), receipt.get("dimension"))
    if receipt_shape != array.shape:
        raise DataProtocolError(
            f"{receipt_path.name} declares shape {receipt_shape}, actual {array.shape}"
        )
    if array.shape[0] != expected_rows:
        raise DataProtocolError(
            f"{embedding_path} has {array.shape[0]} rows but manifested source has "
            f"{expected_rows}"
        )
    if receipt.get("dtype") != str(array.dtype):
        raise DataProtocolError(
            f"{receipt_path.name} dtype {receipt.get('dtype')!r} differs from "
            f"actual {str(array.dtype)!r}"
        )
    return receipt_path, receipt


def build_input_manifest(config: ExperimentConfig) -> dict[str, Any]:
    """Fingerprint inputs without parsing the locked test table.

    Reading raw bytes for a hash cannot expose labels to model selection, while
    still binding the future one-shot test evaluation to an exact file.
    """
    split_manifest = validate_split_manifest(config)
    if split_manifest is None:  # Config validation normally makes this unreachable.
        raise DataProtocolError("locked protocol requires a split manifest")
    split_files = {
        name: config.split_dir / f"{name}.csv" for name in ("train", "val", "test")
    }
    image_encoders = sorted(
        {x.image_encoder for x in config.candidates if x.image_encoder is not None}
    )
    text_encoders = sorted(
        {x.text_encoder for x in config.candidates if x.text_encoder is not None}
    )
    embeddings: dict[str, dict[str, Any]] = {}
    for modality, directory, names in (
        ("image", config.image_embeddings_dir, image_encoders),
        ("text", config.text_embeddings_dir, text_encoders),
    ):
        for name in names:
            path = directory / f"{name}.npy"
            embedding_record = file_fingerprint(
                path, content_hash=config.hash_embeddings
            )
            if config.require_embedding_receipts:
                receipt_path, receipt = _validate_embedding_receipt(
                    path,
                    modality=modality,
                    encoder_name=name,
                    split_manifest=split_manifest,
                )
                embedding_record["extraction_receipt"] = file_fingerprint(
                    receipt_path, content_hash=True
                )
                embedding_record["provenance"] = {
                    "source_snapshot_sha256": receipt["source_snapshot_sha256"],
                    "source_row_order_sha256": receipt["source_row_order_sha256"],
                    "embedding_index_column": receipt["embedding_index_column"],
                    "embedding_index_mapping_sha256": receipt[
                        "embedding_index_mapping_sha256"
                    ],
                    "embedding_sha256": receipt["embedding_sha256"],
                    "encoder": dict(receipt["encoder"]),
                    "preprocessing": dict(receipt["preprocessing"]),
                    "preprocessing_sha256": receipt["preprocessing_sha256"],
                    "pooling": receipt["pooling"],
                    "prefix": receipt["prefix"],
                    "max_length": receipt["max_length"],
                    "rows": receipt["rows"],
                    "dimension": receipt["dimension"],
                    "dtype": receipt["dtype"],
                    "extraction_code_commit": receipt["extraction_code_commit"],
                }
            embeddings[f"{modality}:{name}"] = embedding_record
    result = {
        "schema_version": 1,
        "test_csv_was_parsed": False,
        "class_map": split_manifest["class_map"],
        "class_map_sha256": split_manifest["class_map"]["sha256"],
        "splits": {
            name: file_fingerprint(path, content_hash=True)
            for name, path in split_files.items()
        },
        "embeddings": embeddings,
    }
    split_manifest_path = config.split_dir / "split_manifest.json"
    result["split_manifest"] = file_fingerprint(split_manifest_path, content_hash=True)
    return result


def verify_input_manifest(manifest: dict[str, Any]) -> None:
    """Fail if any frozen input changed after validation-only selection."""
    if manifest.get("test_csv_was_parsed") is not False:
        raise DataProtocolError("input manifest does not attest an unopened test table")
    class_map = manifest.get("class_map")
    stored_class_hash = manifest.get("class_map_sha256")
    if (
        not isinstance(class_map, dict)
        or not isinstance(stored_class_hash, str)
        or class_map.get("sha256") != stored_class_hash
        or class_map_sha256(class_map) != stored_class_hash
    ):
        raise DataProtocolError("frozen input class-map digest mismatch")
    entries = list(manifest.get("splits", {}).values()) + list(
        manifest.get("embeddings", {}).values()
    )
    if "split_manifest" in manifest:
        entries.append(manifest["split_manifest"])
    for expected in entries:
        path = Path(expected["path"])
        if not path.is_file():
            raise DataProtocolError(f"frozen input disappeared: {path}")
        stat = path.stat()
        if stat.st_size != expected["size_bytes"]:
            raise DataProtocolError(f"frozen input size changed: {path}")
        if "sha256" in expected and sha256_file(path) != expected["sha256"]:
            raise DataProtocolError(f"frozen input hash changed: {path}")
        extraction_receipt = expected.get("extraction_receipt")
        if extraction_receipt is not None:
            receipt_path = Path(extraction_receipt["path"])
            if not receipt_path.is_file():
                raise DataProtocolError(
                    f"frozen extraction receipt disappeared: {receipt_path}"
                )
            if receipt_path.stat().st_size != extraction_receipt.get("size_bytes"):
                raise DataProtocolError(
                    f"frozen extraction receipt size changed: {receipt_path}"
                )
            if sha256_file(receipt_path) != extraction_receipt.get("sha256"):
                raise DataProtocolError(
                    f"frozen extraction receipt hash changed: {receipt_path}"
                )


def _read_split(config: ExperimentConfig, name: str) -> pd.DataFrame:
    path = config.split_dir / f"{name}.csv"
    if not path.is_file():
        raise DataProtocolError(f"missing {name} split: {path}")
    frame = pd.read_csv(path)
    required = {
        config.id_column,
        config.embedding_index_column,
        config.label_column,
        config.label_name_column,
        config.time_column,
        *config.group_columns,
    }
    if config.text_column is not None:
        required.add(config.text_column)
    if config.image_column is not None:
        required.add(config.image_column)
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataProtocolError(f"{name}.csv is missing columns: {missing}")
    if frame.empty:
        raise DataProtocolError(f"{name}.csv is empty")
    if (
        frame[config.id_column].isna().any()
        or frame[config.label_column].isna().any()
        or frame[config.label_name_column].isna().any()
    ):
        raise DataProtocolError(f"{name}.csv has null IDs, label IDs, or label names")
    for group_column in config.group_columns:
        if (
            frame[group_column].isna().any()
            or frame[group_column].astype(str).str.strip().eq("").any()
        ):
            raise DataProtocolError(
                f"{name}.csv has null/empty leakage groups in {group_column!r}"
            )
    numeric_ids = pd.to_numeric(frame[config.id_column], errors="raise")
    numeric_embedding_indices = pd.to_numeric(
        frame[config.embedding_index_column], errors="raise"
    )
    numeric_labels = pd.to_numeric(frame[config.label_column], errors="raise")
    if not np.all(numeric_ids.to_numpy() == np.floor(numeric_ids.to_numpy())):
        raise DataProtocolError(f"{name}.csv contains non-integer row IDs")
    if not np.all(numeric_labels.to_numpy() == np.floor(numeric_labels.to_numpy())):
        raise DataProtocolError(f"{name}.csv contains non-integer labels")
    if not np.all(
        numeric_embedding_indices.to_numpy()
        == np.floor(numeric_embedding_indices.to_numpy())
    ):
        raise DataProtocolError(f"{name}.csv contains non-integer embedding indices")
    frame = frame.copy()
    frame[config.id_column] = numeric_ids.astype(np.int64)
    frame[config.embedding_index_column] = numeric_embedding_indices.astype(np.int64)
    frame[config.label_column] = numeric_labels.astype(np.int64)
    if (frame[config.id_column] < 0).any():
        raise DataProtocolError(f"{name}.csv contains negative row IDs")
    if frame[config.id_column].duplicated().any():
        raise DataProtocolError(f"{name}.csv contains duplicate row IDs")
    if (frame[config.embedding_index_column] < 0).any():
        raise DataProtocolError(f"{name}.csv contains negative embedding indices")
    if frame[config.embedding_index_column].duplicated().any():
        raise DataProtocolError(f"{name}.csv contains duplicate embedding indices")
    parsed_time = pd.to_datetime(frame[config.time_column], errors="coerce", utc=True)
    if parsed_time.isna().any():
        raise DataProtocolError(
            f"{name}.csv contains missing or invalid {config.time_column!r} values"
        )
    frame[config.time_column] = parsed_time
    invalid_labels = frame.loc[
        ~frame[config.label_column].between(0, config.expected_num_classes - 1),
        config.label_column,
    ].unique()
    if len(invalid_labels):
        raise DataProtocolError(
            f"{name}.csv labels outside [0, {config.expected_num_classes - 1}]: "
            f"{invalid_labels.tolist()}"
        )
    if config.require_all_classes:
        observed = set(frame[config.label_column].unique().tolist())
        expected = set(range(config.expected_num_classes))
        missing_classes = sorted(expected.difference(observed))
        if missing_classes:
            raise DataProtocolError(
                f"{name}.csv does not contain required classes: {missing_classes}"
            )
    manifest = validate_split_manifest(config)
    assert manifest is not None
    classes = manifest["class_map"]["classes"]
    expected_names = {
        int(item["label_id"]): str(item["label_name"]) for item in classes
    }
    actual_names = frame[config.label_name_column].astype(str)
    mapped_names = frame[config.label_column].map(expected_names)
    mismatched = actual_names != mapped_names
    if mismatched.any():
        examples = frame.loc[
            mismatched, [config.label_column, config.label_name_column]
        ].head(5)
        raise DataProtocolError(
            f"{name}.csv label ID/name pairs differ from frozen class map: "
            f"{examples.to_dict(orient='records')}"
        )
    frame[config.label_name_column] = actual_names
    expected_rows = manifest["outputs"][name].get("rows")
    if expected_rows is not None and len(frame) != int(expected_rows):
        raise DataProtocolError(
            f"{name}.csv row count {len(frame)} does not match split manifest "
            f"row count {expected_rows}"
        )
    return frame


def load_selection_splits(config: ExperimentConfig) -> SplitBundle:
    """Load train/validation only.  This function never parses test.csv."""
    validate_split_manifest(config)
    bundle = SplitBundle(
        train=_read_split(config, "train"),
        val=_read_split(config, "val"),
    )
    audit_split_leakage(config, bundle)
    return bundle


def load_locked_test_splits(config: ExperimentConfig) -> SplitBundle:
    """Load all splits during the explicit one-shot test phase."""
    validate_split_manifest(config)
    bundle = SplitBundle(
        train=_read_split(config, "train"),
        val=_read_split(config, "val"),
        test=_read_split(config, "test"),
    )
    audit_split_leakage(config, bundle)
    return bundle


_WHITESPACE = re.compile(r"\s+")


def _normalise_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    return _WHITESPACE.sub(" ", str(value).strip().casefold())


def _hashed_examples(values: Iterable[Any], limit: int = 5) -> list[str]:
    examples: list[str] = []
    for value in sorted(str(x) for x in values)[:limit]:
        examples.append(sha256(value.encode("utf-8")).hexdigest()[:16])
    return examples


def _cross_overlap(
    frames: dict[str, pd.DataFrame],
    column: str,
    *,
    normalise: bool,
) -> list[dict[str, Any]]:
    prepared: dict[str, set[Any]] = {}
    for name, frame in frames.items():
        if column not in frame.columns:
            raise DataProtocolError(
                f"configured leakage column {column!r} missing in {name}"
            )
        values = frame[column].map(_normalise_text) if normalise else frame[column]
        prepared[name] = {
            value
            for value in values.tolist()
            if not pd.isna(value) and str(value) != ""
        }
    names = list(prepared)
    overlaps: list[dict[str, Any]] = []
    for left_index, left in enumerate(names):
        for right in names[left_index + 1 :]:
            shared = prepared[left].intersection(prepared[right])
            overlaps.append(
                {
                    "left": left,
                    "right": right,
                    "column": column,
                    "count": len(shared),
                    "sample_hashes": _hashed_examples(shared),
                }
            )
    return overlaps


def audit_split_leakage(
    config: ExperimentConfig, bundle: SplitBundle
) -> dict[str, Any]:
    frames = {"train": bundle.train, "val": bundle.val}
    if bundle.test is not None:
        frames["test"] = bundle.test

    checks: list[dict[str, Any]] = []
    checks.extend(_cross_overlap(frames, config.id_column, normalise=False))
    checks.extend(
        _cross_overlap(frames, config.embedding_index_column, normalise=False)
    )
    for column in config.group_columns:
        checks.extend(_cross_overlap(frames, column, normalise=False))
    if config.text_column is not None:
        checks.extend(_cross_overlap(frames, config.text_column, normalise=True))
    if config.image_column is not None:
        checks.extend(_cross_overlap(frames, config.image_column, normalise=True))

    id_or_group = {
        config.id_column,
        config.embedding_index_column,
        *config.group_columns,
    }
    fatal = [
        check for check in checks if check["count"] and check["column"] in id_or_group
    ]
    if config.fail_on_exact_cross_split_duplicates:
        exact_columns = {config.text_column, config.image_column}.difference({None})
        fatal.extend(
            check
            for check in checks
            if check["count"] and check["column"] in exact_columns
        )
    if fatal:
        summary = "; ".join(
            f"{x['column']} {x['left']}↔{x['right']}={x['count']}" for x in fatal
        )
        raise DataProtocolError(f"cross-split leakage detected: {summary}")
    temporal: dict[str, Any] | None = None
    if config.require_strict_temporal_test:
        train_max = bundle.train[config.time_column].max()
        val_min = bundle.val[config.time_column].min()
        val_max = bundle.val[config.time_column].max()
        temporal = {
            "train_max": train_max.isoformat(),
            "val_min": val_min.isoformat(),
            "val_max": val_max.isoformat(),
            "train_before_val": bool(train_max < val_min),
        }
        if train_max >= val_min:
            raise DataProtocolError(
                "strict temporal validation violated: latest train timestamp "
                f"{train_max.isoformat()} is not before earliest validation timestamp "
                f"{val_min.isoformat()}"
            )
    if bundle.test is not None and config.require_strict_temporal_test:
        test_min = bundle.test[config.time_column].min()
        assert temporal is not None
        temporal.update(
            {
                "test_min": test_min.isoformat(),
                "val_before_test": bool(val_max < test_min),
                "strictly_ordered": bool(train_max < val_min and val_max < test_min),
            }
        )
        if val_max >= test_min:
            raise DataProtocolError(
                "strict temporal holdout violated: latest validation timestamp "
                f"{val_max.isoformat()} is not before earliest test timestamp "
                f"{test_min.isoformat()}"
            )
    return {
        "status": "pass",
        "parsed_splits": list(frames),
        "checks": checks,
        "temporal": temporal,
    }


def _validate_class_map_manifest(
    config: ExperimentConfig, manifest: Mapping[str, Any]
) -> dict[str, Any]:
    raw = manifest.get("class_map")
    if not isinstance(raw, dict):
        raise DataProtocolError("split manifest must contain a frozen class_map")
    if raw.get("schema_version") != 1:
        raise DataProtocolError("split manifest class_map.schema_version must be 1")
    if raw.get("label_id_column") != config.label_column:
        raise DataProtocolError(
            "split manifest class-map label ID column differs from the config"
        )
    if raw.get("label_name_column") != config.label_name_column:
        raise DataProtocolError(
            "split manifest class-map label-name column differs from the config"
        )
    classes = raw.get("classes")
    if not isinstance(classes, list) or len(classes) != config.expected_num_classes:
        raise DataProtocolError(
            "split manifest class map must contain exactly "
            f"{config.expected_num_classes} ordered classes"
        )
    expected_ids = list(range(config.expected_num_classes))
    observed_ids: list[int] = []
    observed_names: list[str] = []
    for index, item in enumerate(classes):
        if not isinstance(item, dict):
            raise DataProtocolError(f"class_map.classes[{index}] must be an object")
        label_id = item.get("label_id")
        label_name = item.get("label_name")
        if type(label_id) is not int:  # bool is intentionally rejected.
            raise DataProtocolError(
                f"class_map.classes[{index}].label_id must be an integer"
            )
        if (
            not isinstance(label_name, str)
            or not label_name.strip()
            or label_name != label_name.strip()
        ):
            raise DataProtocolError(
                f"class_map.classes[{index}].label_name must be a normalized, "
                "non-empty string"
            )
        observed_ids.append(label_id)
        observed_names.append(label_name)
    if observed_ids != expected_ids:
        raise DataProtocolError(
            f"class map IDs/order must be {expected_ids}, got {observed_ids}"
        )
    if len(set(observed_names)) != len(observed_names):
        raise DataProtocolError("class-map label names must be unique")
    stored_hash = _require_sha256(raw.get("sha256"), "class_map.sha256")
    if class_map_sha256(raw) != stored_hash:
        raise DataProtocolError("split manifest class-map hash is invalid")
    return raw


def _validate_cutoff_preregistration_manifest(
    manifest: Mapping[str, Any], *, source_hash: str
) -> None:
    record = manifest.get("cutoff_preregistration")
    if not isinstance(record, dict):
        raise DataProtocolError(
            "split manifest must bind a pre-label cutoff preregistration"
        )
    _require_sha256(
        record.get("source_file_sha256"),
        "cutoff_preregistration.source_file_sha256",
    )
    declaration_hash = _require_sha256(
        record.get("declaration_sha256"),
        "cutoff_preregistration.declaration_sha256",
    )
    declaration = record.get("declaration")
    if not isinstance(declaration, dict):
        raise DataProtocolError("cutoff_preregistration.declaration must be an object")
    encoded = json.dumps(
        declaration,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if sha256(encoded).hexdigest() != declaration_hash:
        raise DataProtocolError("cutoff preregistration declaration hash is invalid")
    policy = declaration.get("cutoff_policy")
    if not isinstance(policy, dict):
        raise DataProtocolError(
            "cutoff preregistration declaration has no cutoff_policy"
        )
    mode = policy.get("mode")
    try:
        if mode == "explicit":
            validate_split_preregistration(
                declaration,
                source_snapshot_sha256=source_hash,
                val_start=policy.get("val_start"),
                test_start=policy.get("test_start"),
                train_fraction=0.7,
                val_fraction=0.15,
            )
        elif mode == "temporal_fraction":
            validate_split_preregistration(
                declaration,
                source_snapshot_sha256=source_hash,
                val_start=None,
                test_start=None,
                train_fraction=float(policy.get("train_fraction")),
                val_fraction=float(policy.get("val_fraction")),
            )
        else:
            raise DataProtocolError(
                "cutoff preregistration mode must be explicit or temporal_fraction"
            )
    except (SplitBuildError, TypeError, ValueError) as exc:
        raise DataProtocolError(f"invalid cutoff preregistration: {exc}") from exc

    temporal = manifest.get("temporal_split")
    if not isinstance(temporal, dict):
        raise DataProtocolError("split manifest temporal_split receipt is missing")
    if mode == "explicit":
        if temporal.get("derived_cutoffs") is not False:
            raise DataProtocolError(
                "explicit preregistered cutoffs cannot be marked as derived"
            )
        for field in ("val_start", "test_start"):
            declared = pd.to_datetime(policy[field], utc=True, errors="raise")
            realized = pd.to_datetime(temporal.get(field), utc=True, errors="raise")
            if declared != realized:
                raise DataProtocolError(
                    f"manifest temporal_split.{field} differs from preregistration"
                )
    elif temporal.get("derived_cutoffs") is not True:
        raise DataProtocolError(
            "fractional preregistered cutoffs must be marked as derived"
        )


def validate_split_manifest(config: ExperimentConfig) -> dict[str, Any] | None:
    if not config.require_split_manifest:
        return None
    path = config.split_dir / "split_manifest.json"
    if not path.is_file():
        raise DataProtocolError(
            f"Q2 protocol requires split manifest generated with near-duplicate "
            f"grouping and temporal holdout: {path}"
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    required_pairs = {
        "schema_version": 1,
        "strategy": "grouped_strict_temporal_holdout",
        "embedding_index_column": config.embedding_index_column,
        "time_column": config.time_column,
    }
    for key, expected in required_pairs.items():
        if manifest.get(key) != expected:
            raise DataProtocolError(
                f"split manifest {key!r} must be {expected!r}, "
                f"got {manifest.get(key)!r}"
            )
    _validate_class_map_manifest(config, manifest)
    source = manifest.get("source")
    embedding_index = manifest.get("embedding_index")
    if not isinstance(source, dict) or not isinstance(embedding_index, dict):
        raise DataProtocolError(
            "split manifest must contain source and embedding_index provenance"
        )
    source_hash = _require_sha256(source.get("sha256"), "split_manifest.source.sha256")
    if type(source.get("rows")) is not int or source["rows"] < 1:
        raise DataProtocolError("split_manifest.source.rows must be a positive integer")
    if embedding_index.get("column") != config.embedding_index_column:
        raise DataProtocolError(
            "split manifest embedding_index.column differs from the config"
        )
    if embedding_index.get("source") not in {
        "existing_metadata_column",
        "generated_from_source_row_order",
    }:
        raise DataProtocolError(
            "split manifest embedding_index.source is missing or unsupported"
        )
    _require_sha256(
        embedding_index.get("source_order_sha256"),
        "split_manifest.embedding_index.source_order_sha256",
    )
    _require_sha256(
        embedding_index.get("mapping_sha256"),
        "split_manifest.embedding_index.mapping_sha256",
    )
    _validate_cutoff_preregistration_manifest(manifest, source_hash=source_hash)
    manifest_groups = set(manifest.get("group_columns", []))
    missing_groups = sorted(set(config.group_columns).difference(manifest_groups))
    if missing_groups:
        raise DataProtocolError(
            f"split manifest does not attest configured group columns: {missing_groups}"
        )
    near_text = manifest.get("near_text_grouping", {})
    if near_text.get("method") not in {
        "simhash_bktree",
        "simhash_lsh",
        "minhash_lsh",
    }:
        raise DataProtocolError(
            "split manifest must attest near-text grouping via SimHash or MinHash"
        )
    if manifest.get("near_image_grouping", {}).get("method") != "dhash_bktree":
        raise DataProtocolError(
            "split manifest must attest near-image grouping via dHash/BK-tree"
        )
    grouping = manifest.get("grouping")
    if not isinstance(grouping, dict):
        raise DataProtocolError("split manifest grouping receipt is missing")
    if grouping.get("missing_images") != 0 or grouping.get("unreadable_images") != 0:
        raise DataProtocolError(
            "prespecified Phase-A split cannot contain missing or unreadable images"
        )
    if (
        manifest.get("parameters", {}).get(
            "test_label_membership_used_for_cutoff_acceptance"
        )
        is not False
    ):
        raise DataProtocolError(
            "split manifest must attest that test labels did not tune cutoff acceptance"
        )
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise DataProtocolError("split manifest must contain outputs metadata")
    for split_name in ("train", "val", "test"):
        record = outputs.get(split_name)
        if not isinstance(record, dict):
            raise DataProtocolError(
                f"split manifest has no outputs.{split_name} record"
            )
        if split_name == "test":
            if (
                "rows" in record
                or record.get("statistics_withheld_until_locked_evaluation") is not True
            ):
                raise DataProtocolError(
                    "selection-safe split manifest must withhold test row/label "
                    "statistics until the locked evaluation"
                )
        elif not isinstance(record.get("rows"), int) or record["rows"] < 1:
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.rows must be a positive integer"
            )
        expected_hash = record.get("sha256")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.sha256 is invalid"
            )
        stored_path = record.get("path")
        if not isinstance(stored_path, str) or not stored_path:
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.path is missing"
            )
        relative_path = Path(stored_path)
        if relative_path.is_absolute():
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.path must be manifest-relative"
            )
        split_root = config.split_dir.resolve()
        actual_path = (split_root / relative_path).resolve()
        if not actual_path.is_relative_to(split_root):
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.path escapes the split directory"
            )
        configured_path = (split_root / f"{split_name}.csv").resolve()
        if actual_path != configured_path:
            raise DataProtocolError(
                f"split manifest outputs.{split_name}.path must resolve to "
                f"{split_name}.csv"
            )
        if not actual_path.is_file():
            raise DataProtocolError(f"manifested split is missing: {actual_path}")
        if sha256_file(actual_path) != expected_hash:
            raise DataProtocolError(
                f"{split_name}.csv does not match its near-duplicate split manifest"
            )
    if manifest.get("test_statistics_withheld") is not True:
        raise DataProtocolError(
            "split manifest must explicitly withhold test statistics during selection"
        )
    label_distribution = manifest.get("label_distribution", {})
    if (
        not isinstance(label_distribution, dict)
        or "test" in label_distribution
        or not set(label_distribution).issubset({"train", "val"})
    ):
        raise DataProtocolError(
            "selection-safe split manifest must not expose test label distribution"
        )
    return manifest


class EmbeddingStore:
    """Memory-mapped embedding registry aligned by the stable row ID."""

    def __init__(self, config: ExperimentConfig):
        self.config = config
        self._arrays: dict[tuple[str, str], np.ndarray] = {}

    def _get(self, modality: str, name: str) -> np.ndarray:
        key = (modality, name)
        if key not in self._arrays:
            directory = (
                self.config.image_embeddings_dir
                if modality == "image"
                else self.config.text_embeddings_dir
            )
            path = directory / f"{name}.npy"
            if not path.is_file():
                raise DataProtocolError(f"missing {modality} embedding: {path}")
            array = np.load(path, mmap_mode="r")
            if array.ndim != 2 or array.shape[1] < 1:
                raise DataProtocolError(
                    f"{path} must have shape (rows, features), got {array.shape}"
                )
            self._arrays[key] = array
        return self._arrays[key]

    @staticmethod
    def _l2(array: np.ndarray, eps: float = 1e-9) -> np.ndarray:
        values = np.asarray(array, dtype=np.float32)
        norm = np.linalg.norm(values, axis=1, keepdims=True)
        return values / np.clip(norm, eps, None)

    def _part(
        self,
        modality: str,
        name: str,
        ids: np.ndarray,
    ) -> np.ndarray:
        full = self._get(modality, name)
        if ids.max(initial=-1) >= full.shape[0]:
            raise DataProtocolError(
                f"{modality}:{name} has {full.shape[0]} rows but split references "
                f"{self.config.embedding_index_column}={ids.max()}"
            )
        part = np.asarray(full[ids], dtype=np.float32)
        if not np.isfinite(part).all():
            raise DataProtocolError(
                f"{modality}:{name} contains non-finite values for this split"
            )
        if self.config.l2_per_modality:
            part = self._l2(part)
        return part

    def build_modalities(
        self, candidate: CandidateConfig, split: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        if candidate.image_encoder is None or candidate.text_encoder is None:
            raise DataProtocolError(
                f"candidate {candidate.name!r} requires both modalities"
            )
        ids = split[self.config.embedding_index_column].to_numpy(dtype=np.int64)
        return (
            self._part("image", candidate.image_encoder, ids),
            self._part("text", candidate.text_encoder, ids),
        )

    def build(self, candidate: CandidateConfig, split: pd.DataFrame) -> np.ndarray:
        ids = split[self.config.embedding_index_column].to_numpy(dtype=np.int64)
        parts: list[np.ndarray] = []
        for modality, name in (
            ("image", candidate.image_encoder),
            ("text", candidate.text_encoder),
        ):
            if name is None:
                continue
            parts.append(self._part(modality, name, ids))
        if not parts:
            raise DataProtocolError(f"candidate {candidate.name!r} has no features")
        if len(parts) == 1:
            return parts[0]
        return np.concatenate(parts, axis=1).astype(np.float32, copy=False)
