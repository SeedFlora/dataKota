"""Leakage-resistant grouping and temporal splitting utilities.

The implementation deliberately uses deterministic standard algorithms rather
than an opaque random train/test split. Text SimHash and image dHash are used as
candidate screens; connected components ensure that any linked reports remain
in exactly one temporal partition.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image, ImageOps


class SplitBuildError(RuntimeError):
    """Raised when a defensible split cannot be constructed."""


def class_map_sha256(class_map: dict[str, object]) -> str:
    """Hash the canonical, ordered label-ID/name contract.

    The digest intentionally excludes the digest field itself.  Both split
    construction and downstream experiment/deployment checks use this exact
    representation so a changed class order cannot be mistaken for the same
    classifier task.
    """
    payload = {
        "schema_version": class_map.get("schema_version"),
        "label_id_column": class_map.get("label_id_column"),
        "label_name_column": class_map.get("label_name_column"),
        "classes": class_map.get("classes"),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_class_map(
    frame: pd.DataFrame,
    *,
    label_id_column: str,
    label_name_column: str,
) -> dict[str, object]:
    """Build a one-to-one, contiguous and ordered label mapping."""
    missing = [
        column
        for column in (label_id_column, label_name_column)
        if column not in frame.columns
    ]
    if missing:
        raise SplitBuildError(f"Missing class-map columns: {missing}")

    numeric_ids = pd.to_numeric(frame[label_id_column], errors="coerce")
    if (
        numeric_ids.isna().any()
        or not np.equal(numeric_ids.to_numpy(), np.floor(numeric_ids.to_numpy())).all()
    ):
        raise SplitBuildError(f"{label_id_column} must contain non-null integers")
    label_ids = numeric_ids.astype("int64")
    if (label_ids < 0).any():
        raise SplitBuildError(f"{label_id_column} cannot contain negative IDs")

    raw_names = frame[label_name_column]
    if raw_names.isna().any():
        raise SplitBuildError(f"{label_name_column} cannot contain null names")
    if not raw_names.map(lambda value: isinstance(value, str)).all():
        raise SplitBuildError(
            f"{label_name_column} must contain explicit string class names"
        )
    names = raw_names.astype(str)
    if names.str.strip().eq("").any():
        raise SplitBuildError(f"{label_name_column} cannot contain empty names")
    if (names != names.str.strip()).any():
        raise SplitBuildError(
            f"{label_name_column} contains leading/trailing whitespace; normalize it "
            "before freezing the class map"
        )

    pairs = pd.DataFrame({"label_id": label_ids, "label_name": names})
    names_per_id = pairs.groupby("label_id")["label_name"].nunique()
    ids_per_name = pairs.groupby("label_name")["label_id"].nunique()
    if (names_per_id > 1).any():
        bad = names_per_id[names_per_id > 1].index.astype(int).tolist()
        raise SplitBuildError(f"label IDs map to multiple names: {bad}")
    if (ids_per_name > 1).any():
        bad = ids_per_name[ids_per_name > 1].index.astype(str).tolist()
        raise SplitBuildError(f"label names map to multiple IDs: {bad}")

    unique = pairs.drop_duplicates().sort_values("label_id", kind="stable")
    observed = unique["label_id"].astype(int).tolist()
    expected = list(range(len(unique)))
    if observed != expected:
        raise SplitBuildError(
            f"{label_id_column} must be contiguous and ordered as {expected}; "
            f"observed {observed}"
        )
    class_map: dict[str, object] = {
        "schema_version": 1,
        "label_id_column": label_id_column,
        "label_name_column": label_name_column,
        "classes": [
            {"label_id": int(row.label_id), "label_name": str(row.label_name)}
            for row in unique.itertuples(index=False)
        ],
    }
    class_map["sha256"] = class_map_sha256(class_map)
    return class_map


def validate_split_preregistration(
    declaration: object,
    *,
    source_snapshot_sha256: str,
    val_start: str | None,
    test_start: str | None,
    train_fraction: float,
    val_fraction: float,
) -> dict[str, object]:
    """Validate a cutoff policy frozen before split labels are inspected."""
    if not isinstance(declaration, Mapping):
        raise SplitBuildError("Split preregistration must be a JSON object")
    preregistration = dict(declaration)
    if preregistration.get("schema_version") != 1:
        raise SplitBuildError("Split preregistration schema_version must be 1")
    if preregistration.get("source_snapshot_sha256") != source_snapshot_sha256:
        raise SplitBuildError(
            "Split preregistration does not match the source snapshot hash"
        )
    if preregistration.get("test_labels_inspected") is not False:
        raise SplitBuildError(
            "Split preregistration must attest test_labels_inspected=false"
        )
    for field in ("data_custodian", "rationale"):
        value = preregistration.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SplitBuildError(
                f"Split preregistration {field!r} must be a non-empty string"
            )
    created_at = preregistration.get("created_at_utc")
    if not isinstance(created_at, str):
        raise SplitBuildError(
            "Split preregistration created_at_utc must be an ISO-8601 timestamp"
        )
    try:
        parsed_created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SplitBuildError(
            "Split preregistration created_at_utc must be an ISO-8601 timestamp"
        ) from exc
    if parsed_created_at.tzinfo is None:
        raise SplitBuildError(
            "Split preregistration created_at_utc must include a timezone"
        )
    attempts = preregistration.get("attempt_log")
    if not isinstance(attempts, list) or not attempts:
        raise SplitBuildError(
            "Split preregistration attempt_log must contain at least one entry"
        )
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, Mapping):
            raise SplitBuildError(f"attempt_log[{index}] must be an object")
        if type(attempt.get("attempt")) is not int or attempt["attempt"] < 1:
            raise SplitBuildError(
                f"attempt_log[{index}].attempt must be a positive integer"
            )
        decision = attempt.get("decision")
        if not isinstance(decision, str) or not decision.strip():
            raise SplitBuildError(
                f"attempt_log[{index}].decision must be a non-empty string"
            )

    policy = preregistration.get("cutoff_policy")
    if not isinstance(policy, Mapping):
        raise SplitBuildError("Split preregistration cutoff_policy must be an object")
    explicit = val_start is not None or test_start is not None
    if explicit:
        if val_start is None or test_start is None:
            raise SplitBuildError(
                "Provide both --val-start and --test-start, or neither"
            )
        if policy.get("mode") != "explicit":
            raise SplitBuildError(
                "Split preregistration cutoff_policy.mode must be 'explicit'"
            )
        for field, actual in (("val_start", val_start), ("test_start", test_start)):
            declared = policy.get(field)
            try:
                declared_timestamp = pd.to_datetime(declared, utc=True, errors="raise")
                actual_timestamp = pd.to_datetime(actual, utc=True, errors="raise")
            except (TypeError, ValueError) as exc:
                raise SplitBuildError(
                    f"Split preregistration cutoff_policy.{field} is invalid"
                ) from exc
            if declared_timestamp != actual_timestamp:
                raise SplitBuildError(
                    f"CLI {field} differs from the preregistered cutoff"
                )
    else:
        if policy.get("mode") != "temporal_fraction":
            raise SplitBuildError(
                "Split preregistration cutoff_policy.mode must be 'temporal_fraction'"
            )
        try:
            declared_train = float(policy.get("train_fraction"))
            declared_val = float(policy.get("val_fraction"))
        except (TypeError, ValueError) as exc:
            raise SplitBuildError(
                "Preregistered train/validation fractions must be numeric"
            ) from exc
        if not np.isclose(declared_train, train_fraction) or not np.isclose(
            declared_val, val_fraction
        ):
            raise SplitBuildError(
                "CLI train/validation fractions differ from the preregistered policy"
            )
    return preregistration


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))
        self.rank = [0] * size

    def find(self, item: int) -> int:
        parent = self.parent[item]
        if parent != item:
            self.parent[item] = self.find(parent)
        return self.parent[item]

    def union(self, left: int, right: int) -> bool:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return False
        if self.rank[left_root] < self.rank[right_root]:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if self.rank[left_root] == self.rank[right_root]:
            self.rank[left_root] += 1
        return True


def normalize_text(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", " ", text).strip()


def char_shingles(text: str, width: int = 4) -> set[str]:
    compact = f" {normalize_text(text)} "
    if not compact.strip():
        return set()
    if len(compact) <= width:
        return {compact}
    return {compact[index : index + width] for index in range(len(compact) - width + 1)}


def simhash64(features: Iterable[str]) -> int:
    vector = [0] * 64
    used = 0
    for feature in sorted(set(features)):
        used += 1
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        for bit in range(64):
            vector[bit] += 1 if value & (1 << bit) else -1
    if not used:
        return 0
    output = 0
    for bit, weight in enumerate(vector):
        if weight >= 0:
            output |= 1 << bit
    return output


def hamming64(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class BKTree:
    """Small deterministic BK-tree for 64-bit Hamming-distance lookups."""

    def __init__(self):
        self.root: tuple[int, list[int], dict[int, object]] | None = None

    def add(self, value: int, index: int) -> None:
        if self.root is None:
            self.root = (value, [index], {})
            return
        node = self.root
        while True:
            node_value, indices, children = node
            distance = hamming64(value, node_value)
            if distance == 0:
                indices.append(index)
                return
            child = children.get(distance)
            if child is None:
                children[distance] = (value, [index], {})
                return
            node = child  # type: ignore[assignment]

    def query(self, value: int, radius: int) -> list[int]:
        if self.root is None:
            return []
        matches: list[int] = []
        stack = [self.root]
        while stack:
            node_value, indices, children = stack.pop()
            distance = hamming64(value, node_value)
            if distance <= radius:
                matches.extend(indices)
            lower, upper = distance - radius, distance + radius
            for edge, child in children.items():
                if lower <= edge <= upper:
                    stack.append(child)  # type: ignore[arg-type]
        return matches


def dhash64(path: Path) -> int:
    try:
        with Image.open(path) as image:
            image = (
                ImageOps.exif_transpose(image)
                .convert("L")
                .resize((9, 8), Image.Resampling.LANCZOS)
            )
            pixels = np.asarray(image, dtype=np.int16)
    except (OSError, ValueError) as exc:
        raise SplitBuildError(f"Cannot hash image {path}: {exc}") from exc
    comparisons = pixels[:, 1:] > pixels[:, :-1]
    output = 0
    for bit, flag in enumerate(comparisons.ravel()):
        if bool(flag):
            output |= 1 << bit
    return output


@dataclass(frozen=True)
class GroupingReceipt:
    exact_text_edges: int
    near_text_edges: int
    near_image_edges: int
    explicit_group_edges: int
    missing_images: int
    unreadable_images: int


def build_leakage_groups(
    frame: pd.DataFrame,
    *,
    id_column: str,
    text_column: str,
    image_column: str,
    image_base: Path,
    explicit_group_columns: Sequence[str] = (),
    text_hamming_radius: int = 3,
    text_jaccard_threshold: float = 0.82,
    image_hamming_radius: int = 5,
    allow_missing_images: bool = False,
) -> tuple[pd.Series, GroupingReceipt]:
    required = {id_column, text_column, image_column, *explicit_group_columns}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise SplitBuildError(f"Metadata is missing grouping columns: {missing}")
    if frame[id_column].isna().any() or frame[id_column].duplicated().any():
        raise SplitBuildError(f"{id_column} must be non-null and unique")

    union_find = UnionFind(len(frame))
    exact_edges = near_text_edges = near_image_edges = explicit_edges = 0

    exact_text: dict[str, int] = {}
    normalized_texts = [normalize_text(value) for value in frame[text_column].tolist()]
    for index, text in enumerate(normalized_texts):
        if not text:
            continue
        previous = exact_text.get(text)
        if previous is None:
            exact_text[text] = index
        elif union_find.union(previous, index):
            exact_edges += 1

    text_tree = BKTree()
    text_hashes: list[int] = []
    for index, text in enumerate(normalized_texts):
        shingles = char_shingles(text)
        value = simhash64(shingles)
        text_hashes.append(value)
        if text:
            for candidate in text_tree.query(value, text_hamming_radius):
                if union_find.find(candidate) == union_find.find(index):
                    continue
                if jaccard(
                    shingles, char_shingles(normalized_texts[candidate])
                ) >= text_jaccard_threshold and union_find.union(candidate, index):
                    near_text_edges += 1
            text_tree.add(value, index)

    missing_images = unreadable_images = 0
    image_tree = BKTree()
    for index, raw_path in enumerate(frame[image_column].tolist()):
        value = (
            "" if raw_path is None or bool(pd.isna(raw_path)) else str(raw_path).strip()
        )
        path = Path(value)
        if not path.is_absolute():
            path = image_base / path
        if not value or not path.is_file():
            missing_images += 1
            if allow_missing_images:
                continue
            raise SplitBuildError(
                f"Missing image for row {frame.iloc[index][id_column]}: {path}"
            )
        try:
            image_hash = dhash64(path)
        except SplitBuildError:
            unreadable_images += 1
            if allow_missing_images:
                continue
            raise
        for candidate in image_tree.query(image_hash, image_hamming_radius):
            if union_find.union(candidate, index):
                near_image_edges += 1
        image_tree.add(image_hash, index)

    for column in explicit_group_columns:
        first_by_value: dict[str, int] = {}
        for index, raw_value in enumerate(frame[column].tolist()):
            value = normalize_text(raw_value)
            if not value:
                continue
            previous = first_by_value.get(value)
            if previous is None:
                first_by_value[value] = index
            elif union_find.union(previous, index):
                explicit_edges += 1

    member_ids: dict[int, list[str]] = defaultdict(list)
    for index, raw_id in enumerate(frame[id_column].tolist()):
        member_ids[union_find.find(index)].append(str(raw_id))
    group_names = {
        root: "g_"
        + hashlib.sha256("\x1f".join(sorted(ids)).encode("utf-8")).hexdigest()[:16]
        for root, ids in member_ids.items()
    }
    groups = pd.Series(
        [group_names[union_find.find(index)] for index in range(len(frame))],
        index=frame.index,
        name="leakage_group_id",
    )
    return groups, GroupingReceipt(
        exact_text_edges=exact_edges,
        near_text_edges=near_text_edges,
        near_image_edges=near_image_edges,
        explicit_group_edges=explicit_edges,
        missing_images=missing_images,
        unreadable_images=unreadable_images,
    )


@dataclass(frozen=True)
class TemporalSplitReceipt:
    derived_cutoffs: bool
    val_start: str
    test_start: str
    quarantined_groups: int
    quarantined_rows: int


def assign_group_temporal_split(
    frame: pd.DataFrame,
    *,
    time_column: str,
    group_column: str = "leakage_group_id",
    val_start: str | None = None,
    test_start: str | None = None,
    target_train_fraction: float = 0.70,
    target_val_fraction: float = 0.15,
) -> tuple[pd.Series, TemporalSplitReceipt]:
    if time_column not in frame or group_column not in frame:
        raise SplitBuildError(
            f"Required temporal columns missing: {time_column}, {group_column}"
        )
    timestamps = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        bad = int(timestamps.isna().sum())
        raise SplitBuildError(f"{time_column} has {bad} unparsable/null timestamps")
    if not 0 < target_train_fraction < 1 or not 0 < target_val_fraction < 1:
        raise SplitBuildError("Split fractions must be in (0, 1)")
    if target_train_fraction + target_val_fraction >= 1:
        raise SplitBuildError("Train + validation fractions must be below 1")

    group_table = (
        pd.DataFrame({"group": frame[group_column], "timestamp": timestamps})
        .groupby("group", as_index=False)
        .agg(
            min_timestamp=("timestamp", "min"),
            max_timestamp=("timestamp", "max"),
            rows=("timestamp", "size"),
        )
        .sort_values(["max_timestamp", "group"])
        .reset_index(drop=True)
    )
    derived = val_start is None and test_start is None
    if (val_start is None) != (test_start is None):
        raise SplitBuildError("Provide both --val-start and --test-start, or neither")
    if derived:
        ordered_timestamps = timestamps.sort_values(kind="stable").reset_index(
            drop=True
        )
        if len(ordered_timestamps) < 3:
            raise SplitBuildError("At least three dated rows are required")
        val_index = min(
            max(int(np.floor(target_train_fraction * len(ordered_timestamps))), 1),
            len(ordered_timestamps) - 2,
        )
        test_index = min(
            max(
                int(
                    np.floor(
                        (target_train_fraction + target_val_fraction)
                        * len(ordered_timestamps)
                    )
                ),
                val_index + 1,
            ),
            len(ordered_timestamps) - 1,
        )
        val_cutoff = ordered_timestamps.iloc[val_index]
        test_cutoff = ordered_timestamps.iloc[test_index]
    else:
        val_cutoff = pd.to_datetime(val_start, utc=True, errors="raise")
        test_cutoff = pd.to_datetime(test_start, utc=True, errors="raise")
    if not val_cutoff < test_cutoff:
        raise SplitBuildError("Validation start must be before test start")

    # A group that straddles a boundary cannot be placed on either side without
    # violating strict chronology or group isolation. Quarantine it explicitly
    # instead of silently leaking an older incident into a later partition.
    train_mask = group_table["max_timestamp"] < val_cutoff
    val_mask = (group_table["min_timestamp"] >= val_cutoff) & (
        group_table["max_timestamp"] < test_cutoff
    )
    test_mask = group_table["min_timestamp"] >= test_cutoff
    group_table["split"] = np.select(
        [train_mask, val_mask, test_mask],
        ["train", "val", "test"],
        default="quarantine",
    )
    observed = set(group_table["split"])
    missing_partitions = {"train", "val", "test"}.difference(observed)
    if missing_partitions:
        raise SplitBuildError(
            f"Temporal cutoffs produced empty partitions: {sorted(missing_partitions)}"
        )
    mapping = dict(zip(group_table["group"], group_table["split"]))
    assignment = frame[group_column].map(mapping).rename("split")
    quarantined = group_table[group_table["split"] == "quarantine"]
    return assignment, TemporalSplitReceipt(
        derived_cutoffs=derived,
        val_start=val_cutoff.isoformat(),
        test_start=test_cutoff.isoformat(),
        quarantined_groups=len(quarantined),
        quarantined_rows=int(quarantined["rows"].sum()),
    )


def assert_group_disjoint(frame: pd.DataFrame) -> None:
    counts = frame.groupby("leakage_group_id")["split"].nunique()
    leaking = counts[counts > 1]
    if len(leaking):
        raise SplitBuildError(f"{len(leaking)} leakage groups cross partitions")


def assert_strict_temporal_order(
    frame: pd.DataFrame,
    *,
    time_column: str,
) -> dict[str, dict[str, str]]:
    timestamps = pd.to_datetime(frame[time_column], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise SplitBuildError(f"{time_column} contains invalid timestamps")
    ranges: dict[str, dict[str, str]] = {}
    for split in ("train", "val", "test"):
        values = timestamps[frame["split"] == split]
        if values.empty:
            raise SplitBuildError(f"{split} partition is empty")
        ranges[split] = {
            "min": values.min().isoformat(),
            "max": values.max().isoformat(),
        }
    train_max = pd.Timestamp(ranges["train"]["max"])
    val_min = pd.Timestamp(ranges["val"]["min"])
    val_max = pd.Timestamp(ranges["val"]["max"])
    test_min = pd.Timestamp(ranges["test"]["min"])
    if not train_max < val_min:
        raise SplitBuildError(
            f"Strict chronology failed: train max {train_max} >= val min {val_min}"
        )
    if not val_max < test_min:
        raise SplitBuildError(
            f"Strict chronology failed: val max {val_max} >= test min {test_min}"
        )
    return ranges


def label_distribution(
    frame: pd.DataFrame, label_column: str
) -> dict[str, dict[str, int]]:
    table = pd.crosstab(frame["split"], frame[label_column])
    return {
        str(split): {str(label): int(count) for label, count in row.items()}
        for split, row in table.iterrows()
    }


def conflicting_group_count(frame: pd.DataFrame, label_column: str) -> int:
    return int((frame.groupby("leakage_group_id")[label_column].nunique() > 1).sum())
