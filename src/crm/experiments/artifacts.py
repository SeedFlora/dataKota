"""Atomic experiment artifacts and reproducibility metadata."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .data import sha256_file
from .models import PredictionBundle


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"cannot JSON-encode {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def object_sha256(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def create_once_marker(path: Path, payload: dict[str, Any]) -> None:
    """Create a marker atomically; fail if this test phase was opened before."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise RuntimeError(
            f"locked test has already been opened for this run: {path}"
        ) from exc


def environment_manifest(project_root: Path) -> dict[str, Any]:
    packages: dict[str, str | None] = {}
    for package in (
        "catboost",
        "joblib",
        "numpy",
        "pandas",
        "PyYAML",
        "scikit-learn",
        "scipy",
    ):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    git: dict[str, Any] = {"commit": None, "dirty": None, "status": None}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        git = {"commit": commit, "dirty": bool(status), "status": status.splitlines()}
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "captured_at_utc": utc_now(),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "packages": packages,
        "git": git,
    }


def prediction_frame(
    split: pd.DataFrame,
    *,
    id_column: str,
    label_column: str,
    prediction: PredictionBundle,
    metadata_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    result = pd.DataFrame(
        {
            id_column: split[id_column].to_numpy(),
            "y_true": split[label_column].to_numpy(dtype=np.int64),
            "y_pred": prediction.predictions,
            "confidence": prediction.probabilities.max(axis=1),
            "correct": prediction.predictions
            == split[label_column].to_numpy(dtype=np.int64),
        }
    )
    insert_at = 1
    for column in metadata_columns:
        if column in {id_column, label_column} or column in result.columns:
            continue
        if column not in split.columns:
            raise ValueError(f"prediction metadata column missing from split: {column}")
        result.insert(insert_at, column, split[column].to_numpy())
        insert_at += 1
    for class_id in range(prediction.probabilities.shape[1]):
        result[f"prob_{class_id}"] = prediction.probabilities[:, class_id]
    for name, values in prediction.uncertainty.items():
        result[f"uncertainty_{name}"] = values
    return result


def write_prediction_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    frame.to_csv(temporary, index=False, compression="gzip", float_format="%.10g")
    temporary.replace(path)


def artifact_record(path: Path, *, base_dir: Path | None = None) -> dict[str, Any]:
    resolved = path.resolve()
    stored_path = str(resolved)
    if base_dir is not None:
        stored_path = resolved.relative_to(base_dir.resolve()).as_posix()
    return {
        "path": stored_path,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def resolve_artifact_path(record: dict[str, Any], *, base_dir: Path) -> Path:
    stored = Path(record["path"])
    if stored.is_absolute():
        raise RuntimeError(
            f"artifact receipt path must be relative to the run directory: {stored}"
        )
    base = base_dir.resolve()
    resolved = (base / stored).resolve()
    if not resolved.is_relative_to(base):
        raise RuntimeError(f"artifact path escapes run directory: {stored}")
    return resolved
