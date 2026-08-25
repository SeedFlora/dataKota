#!/usr/bin/env python3
"""Build immutable group-temporal train/validation/test splits for Q2 experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm.splitting import (
    SplitBuildError,
    assert_group_disjoint,
    assert_strict_temporal_order,
    assign_group_temporal_split,
    build_class_map,
    build_leakage_groups,
    conflicting_group_count,
    label_distribution,
    validate_split_preregistration,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> int:
    source = Path(args.metadata).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    source_hash = sha256_file(source)
    preregistration_path = Path(args.split_preregistration).resolve()
    if not preregistration_path.is_file():
        raise FileNotFoundError(preregistration_path)
    preregistration_bytes = preregistration_path.read_bytes()
    try:
        preregistration_raw = json.loads(preregistration_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SplitBuildError(
            f"Invalid split preregistration JSON: {preregistration_path}"
        ) from exc
    preregistration = validate_split_preregistration(
        preregistration_raw,
        source_snapshot_sha256=source_hash,
        val_start=args.val_start,
        test_start=args.test_start,
        train_fraction=args.train_fraction,
        val_fraction=args.val_fraction,
    )
    if args.allow_missing_images:
        raise SplitBuildError(
            "--allow-missing-images is incompatible with a prespecified Phase-A split; "
            "repair/exclude those rows under a separately frozen data-cleaning "
            "protocol before building the split"
        )
    frame = pd.read_csv(source)
    class_map = build_class_map(
        frame,
        label_id_column=args.label_column,
        label_name_column=args.label_name_column,
    )
    frame[args.label_column] = pd.to_numeric(
        frame[args.label_column], errors="raise"
    ).astype("int64")
    frame = frame.copy()
    embedding_index_source: str
    if args.embedding_index_column in frame:
        values = pd.to_numeric(frame[args.embedding_index_column], errors="raise")
        if values.isna().any() or not (values == values.astype("int64")).all():
            raise SplitBuildError(
                f"{args.embedding_index_column} must contain non-null integers"
            )
        values = values.astype("int64")
        if (values < 0).any() or values.duplicated().any():
            raise SplitBuildError(
                f"{args.embedding_index_column} must be unique and non-negative"
            )
        if sorted(values.tolist()) != list(range(len(frame))):
            raise SplitBuildError(
                f"{args.embedding_index_column} must be a permutation of "
                f"0..{len(frame) - 1}; sparse/out-of-range indices cannot be "
                "aligned to a full-source embedding cache"
            )
        frame[args.embedding_index_column] = values
        embedding_index_source = "existing_metadata_column"
    elif args.generate_embedding_index_from_source_order:
        frame[args.embedding_index_column] = range(len(frame))
        embedding_index_source = "generated_from_source_row_order"
    else:
        raise SplitBuildError(
            f"Metadata has no {args.embedding_index_column!r}. If every embedding "
            "cache was extracted from this exact CSV in unchanged row order, rerun "
            "with --generate-embedding-index-from-source-order; otherwise add an "
            "explicit verified index column first."
        )

    embedding_index_mapping_hash = hashlib.sha256(
        json.dumps(
            frame[args.embedding_index_column].astype(int).tolist(),
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    groups, grouping_receipt = build_leakage_groups(
        frame,
        id_column=args.id_column,
        text_column=args.text_column,
        image_column=args.image_column,
        image_base=Path(args.image_base).resolve(),
        explicit_group_columns=tuple(args.group_column),
        text_hamming_radius=args.text_hamming_radius,
        text_jaccard_threshold=args.text_jaccard_threshold,
        image_hamming_radius=args.image_hamming_radius,
        allow_missing_images=args.allow_missing_images,
    )
    if grouping_receipt.missing_images or grouping_receipt.unreadable_images:
        raise SplitBuildError(
            "Confirmatory split requires readable images for every included row"
        )
    frame["leakage_group_id"] = groups
    assignment, temporal_receipt = assign_group_temporal_split(
        frame,
        time_column=args.time_column,
        val_start=args.val_start,
        test_start=args.test_start,
        target_train_fraction=args.train_fraction,
        target_val_fraction=args.val_fraction,
    )
    frame["split"] = assignment
    assert_group_disjoint(frame)
    temporal_ranges = assert_strict_temporal_order(frame, time_column=args.time_column)

    # Development partitions must support training/selection.  Deliberately do
    # not inspect test-class presence or recommend cutoff changes based on test
    # labels: the preregistered temporal policy remains fixed.
    expected_labels = set(range(len(class_map["classes"])))
    for split in ("train", "val"):
        observed_labels = set(
            frame.loc[frame["split"] == split, args.label_column].unique().tolist()
        )
        missing_labels = sorted(expected_labels.difference(observed_labels))
        if missing_labels:
            raise SplitBuildError(
                f"development partition {split!r} is missing labels {missing_labels}; "
                "do not alter the frozen cutoff based on test labels"
            )

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    protected_targets = [
        out_dir / name
        for name in (
            "train.csv",
            "val.csv",
            "test.csv",
            "quarantine.csv",
            "split_manifest.json",
        )
    ]
    existing_targets = [path for path in protected_targets if path.exists()]
    if existing_targets and not args.overwrite:
        raise SplitBuildError(
            "Refusing to mutate an existing split. Choose a new --out-dir or pass "
            "--overwrite explicitly: "
            + ", ".join(str(path) for path in existing_targets)
        )
    output_files: dict[str, dict[str, object]] = {}
    for split in ("train", "val", "test", "quarantine"):
        if split == "quarantine" and not (frame["split"] == split).any():
            continue
        target = out_dir / f"{split}.csv"
        part = frame.loc[frame["split"] == split].drop(columns=["split"])
        temporary = target.with_suffix(target.suffix + ".tmp")
        part.to_csv(temporary, index=False)
        temporary.replace(target)
        output_record: dict[str, object] = {
            "path": target.name,
            "sha256": sha256_file(target),
        }
        if split == "test":
            output_record["statistics_withheld_until_locked_evaluation"] = True
        else:
            output_record["rows"] = len(part)
        output_files[split] = output_record
    stale_quarantine = out_dir / "quarantine.csv"
    if not (frame["split"] == "quarantine").any() and stale_quarantine.exists():
        stale_quarantine.unlink()

    timestamps = pd.to_datetime(frame[args.time_column], utc=True, errors="raise")
    manifest = {
        "schema_version": 1,
        "strategy": "grouped_strict_temporal_holdout",
        "embedding_index_column": args.embedding_index_column,
        "class_map": class_map,
        "cutoff_preregistration": {
            "source_file_sha256": hashlib.sha256(preregistration_bytes).hexdigest(),
            "declaration_sha256": hashlib.sha256(
                json.dumps(
                    preregistration,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest(),
            "declaration": preregistration,
        },
        "embedding_index": {
            "column": args.embedding_index_column,
            "source": embedding_index_source,
            "source_order_sha256": source_hash,
            "mapping_sha256": embedding_index_mapping_hash,
        },
        "time_column": args.time_column,
        "group_columns": ["leakage_group_id", *args.group_column],
        "near_text_grouping": {
            "method": "simhash_bktree",
            "hamming_radius": args.text_hamming_radius,
            "jaccard_threshold": args.text_jaccard_threshold,
        },
        "near_image_grouping": {
            "method": "dhash_bktree",
            "hamming_radius": args.image_hamming_radius,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "test_statistics_withheld": True,
        "source": {
            "path": str(source),
            "sha256": source_hash,
            "rows": len(frame),
        },
        "parameters": {
            "id_column": args.id_column,
            "label_column": args.label_column,
            "label_name_column": args.label_name_column,
            "time_column": args.time_column,
            "text_column": args.text_column,
            "image_column": args.image_column,
            "explicit_group_columns": args.group_column,
            "text_hamming_radius": args.text_hamming_radius,
            "text_jaccard_threshold": args.text_jaccard_threshold,
            "image_hamming_radius": args.image_hamming_radius,
            "allow_missing_images": args.allow_missing_images,
            "test_label_membership_used_for_cutoff_acceptance": False,
        },
        "grouping": asdict(grouping_receipt),
        "temporal_split": asdict(temporal_receipt),
        "strict_temporal_ranges": temporal_ranges,
        "time_range": {
            "min": timestamps.min().isoformat(),
            "max": timestamps.max().isoformat(),
        },
        "groups": {
            "count": int(frame["leakage_group_id"].nunique()),
            "largest_size": int(frame.groupby("leakage_group_id").size().max()),
            "development_multi_label_groups": conflicting_group_count(
                frame[frame["split"].isin(["train", "val"])], args.label_column
            ),
        },
        "label_distribution": label_distribution(
            frame[frame["split"].isin(["train", "val"])], args.label_column
        ),
        "outputs": output_files,
        "limitations": [
            "SimHash/dHash clustering is a deterministic screening procedure, not proof that all semantic duplicates were found.",
            "Temporal cutoffs and incident grouping must be justified from collection metadata before the test partition is opened.",
            "External-city validation is not created by this script.",
        ],
    }
    manifest_path = out_dir / "split_manifest.json"
    manifest_temporary = manifest_path.with_suffix(".json.tmp")
    manifest_temporary.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    manifest_temporary.replace(manifest_path)
    print(
        json.dumps({"outputs": output_files, "manifest": str(manifest_path)}, indent=2)
    )
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--metadata", required=True)
    command.add_argument(
        "--split-preregistration",
        required=True,
        help=(
            "JSON declaration binding source hash, custodian, rationale, attempt log, "
            "and cutoff policy before labels are inspected"
        ),
    )
    command.add_argument("--image-base", required=True)
    command.add_argument("--out-dir", default="artifacts/splits_q2")
    command.add_argument("--id-column", default="row_id")
    command.add_argument("--label-column", default="label_id")
    command.add_argument("--label-name-column", default="label")
    command.add_argument("--embedding-index-column", default="embedding_index")
    command.add_argument(
        "--generate-embedding-index-from-source-order",
        action="store_true",
        help=(
            "create the embedding index from CSV row order; use only when all .npy "
            "caches were extracted from this exact, unchanged source order"
        ),
    )
    command.add_argument("--time-column", default="created_at")
    command.add_argument("--text-column", default="laporan")
    command.add_argument("--image-column", default="gambar")
    command.add_argument("--group-column", action="append", default=[])
    command.add_argument("--val-start")
    command.add_argument("--test-start")
    command.add_argument("--train-fraction", type=float, default=0.70)
    command.add_argument("--val-fraction", type=float, default=0.15)
    command.add_argument("--text-hamming-radius", type=int, default=3)
    command.add_argument("--text-jaccard-threshold", type=float, default=0.82)
    command.add_argument("--image-hamming-radius", type=int, default=5)
    command.add_argument(
        "--allow-missing-images",
        action="store_true",
        help="rejected for prespecified Phase-A splits; retained only for explicit diagnostics",
    )
    command.add_argument(
        "--overwrite",
        action="store_true",
        help="explicitly replace split outputs in --out-dir",
    )
    return command


if __name__ == "__main__":
    sys.exit(build(parser().parse_args()))
