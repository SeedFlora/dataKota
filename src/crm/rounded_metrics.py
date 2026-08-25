"""Exact integer reconstruction from rounded multiclass metric reports.

The historical paper table prints precision, recall, and F1 to four decimal
places. This module enumerates every integer ``(TP, FN, FP)`` margin compatible
with those displayed intervals. It reconstructs diagonal and marginal counts;
it cannot recover off-diagonal confusion cells or sample identities.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Iterable, Mapping


def parse_four_decimal(value: str) -> int:
    """Return a four-decimal probability as an integer in ``[0, 10000]``."""
    text = value.strip()
    whole, separator, fractional = text.partition(".")
    if separator != "." or whole not in {"0", "1"} or len(fractional) != 4:
        raise ValueError(f"metric must be printed with four decimals: {value!r}")
    if not fractional.isdigit():
        raise ValueError(f"metric is not numeric: {value!r}")
    scaled = int(whole) * 10_000 + int(fractional)
    if not 0 <= scaled <= 10_000:
        raise ValueError(f"metric is outside [0, 1]: {value!r}")
    return scaled


def rounds_to_four_decimal(numerator: int, denominator: int, displayed: int) -> bool:
    """Test a non-negative rational against an exact half-up display interval.

    The comparison is integer-only. For displayed integer ``q`` it implements
    ``(q-0.5)/10000 <= numerator/denominator < (q+0.5)/10000``.
    No reconstructed value in the supplied historical table lies on a boundary.
    """
    if numerator < 0 or denominator <= 0:
        raise ValueError("a metric ratio requires numerator >= 0 and denominator > 0")
    if not 0 <= displayed <= 10_000:
        raise ValueError("displayed metric must be in [0, 10000]")
    twice_scaled_numerator = 20_000 * numerator
    return (
        (2 * displayed - 1) * denominator
        <= twice_scaled_numerator
        < (2 * displayed + 1) * denominator
    )


@dataclass(frozen=True)
class ReportedMetric:
    label: str
    precision: int
    recall: int
    f1: int
    support: int

    @classmethod
    def from_mapping(cls, row: Mapping[str, str]) -> "ReportedMetric":
        label = row["label"].strip()
        if not label:
            raise ValueError("class label cannot be empty")
        support = int(row["support"])
        if support <= 0:
            raise ValueError(f"support must be positive for {label}")
        return cls(
            label=label,
            precision=parse_four_decimal(row["precision"]),
            recall=parse_four_decimal(row["recall"]),
            f1=parse_four_decimal(row["f1"]),
            support=support,
        )


@dataclass(frozen=True)
class ReconstructedMetric:
    label: str
    precision: str
    recall: str
    f1: str
    support: int
    tp: int
    fn: int
    fp: int


def read_reported_metrics(path: Path) -> list[ReportedMetric]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = [ReportedMetric.from_mapping(row) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError(f"metric table is empty: {path}")
    if len({row.label for row in rows}) != len(rows):
        raise ValueError("class labels must be unique")
    return rows


def enumerate_candidates(
    row: ReportedMetric,
    *,
    total_samples: int,
) -> list[tuple[int, int, int]]:
    """Enumerate all ``(TP, FN, FP)`` margins matching one printed row."""
    if total_samples < row.support:
        raise ValueError("total sample count cannot be smaller than class support")
    candidates: list[tuple[int, int, int]] = []
    for tp in range(row.support + 1):
        if not rounds_to_four_decimal(tp, row.support, row.recall):
            continue
        fn = row.support - tp
        for fp in range(total_samples - row.support + 1):
            if tp + fp == 0:
                continue
            if not rounds_to_four_decimal(tp, tp + fp, row.precision):
                continue
            f1_denominator = 2 * tp + fp + fn
            if rounds_to_four_decimal(2 * tp, f1_denominator, row.f1):
                candidates.append((tp, fn, fp))
    return candidates


def reconstruct_metrics(rows: Iterable[ReportedMetric]) -> list[ReconstructedMetric]:
    reported = list(rows)
    if not reported:
        raise ValueError("at least one class row is required")
    total_samples = sum(row.support for row in reported)
    reconstructed: list[ReconstructedMetric] = []
    for row in reported:
        candidates = enumerate_candidates(row, total_samples=total_samples)
        if len(candidates) != 1:
            raise ValueError(
                f"{row.label} has {len(candidates)} compatible integer margins; "
                "the reconstruction is not unique"
            )
        tp, fn, fp = candidates[0]
        reconstructed.append(
            ReconstructedMetric(
                label=row.label,
                precision=f"{row.precision / 10_000:.4f}",
                recall=f"{row.recall / 10_000:.4f}",
                f1=f"{row.f1 / 10_000:.4f}",
                support=row.support,
                tp=tp,
                fn=fn,
                fp=fp,
            )
        )
    false_negatives = sum(row.fn for row in reconstructed)
    false_positives = sum(row.fp for row in reconstructed)
    if false_negatives != false_positives:
        raise ValueError(
            "reconstructed margins violate the single-label multiclass identity "
            f"sum(FN) == sum(FP): {false_negatives} != {false_positives}"
        )
    return reconstructed


def compatible_correct_counts(total_samples: int, displayed_accuracy: str) -> list[int]:
    target = parse_four_decimal(displayed_accuracy)
    return [
        correct
        for correct in range(total_samples + 1)
        if rounds_to_four_decimal(correct, total_samples, target)
    ]


def reconstruction_summary(rows: Iterable[ReconstructedMetric]) -> dict[str, object]:
    reconstructed = list(rows)
    if not reconstructed:
        raise ValueError("at least one reconstructed row is required")
    total = sum(row.support for row in reconstructed)
    tp_total = sum(row.tp for row in reconstructed)
    fn_total = sum(row.fn for row in reconstructed)
    fp_total = sum(row.fp for row in reconstructed)
    precisions = [Fraction(row.tp, row.tp + row.fp) for row in reconstructed]
    recalls = [Fraction(row.tp, row.support) for row in reconstructed]
    f1_values = [
        Fraction(2 * row.tp, 2 * row.tp + row.fp + row.fn)
        for row in reconstructed
    ]
    class_count = len(reconstructed)
    urban_and_catch_all_fn = sum(
        row.fn
        for row in reconstructed
        if row.label in {"Urban village administration", "Other agency (catch-all)"}
    )
    return {
        "samples": total,
        "correct": tp_total,
        "errors": fn_total,
        "false_negatives": fn_total,
        "false_positives": fp_total,
        "accuracy": float(Fraction(tp_total, total)),
        "macro_precision": float(sum(precisions, Fraction()) / class_count),
        "macro_recall": float(sum(recalls, Fraction()) / class_count),
        "balanced_accuracy": float(sum(recalls, Fraction()) / class_count),
        "macro_f1": float(sum(f1_values, Fraction()) / class_count),
        "urban_and_catch_all_false_negatives": urban_and_catch_all_fn,
        "urban_and_catch_all_fn_share": float(
            Fraction(urban_and_catch_all_fn, fn_total)
        ),
    }


def reconstructed_rows_as_dicts(
    rows: Iterable[ReconstructedMetric],
) -> list[dict[str, object]]:
    return [asdict(row) for row in rows]
