from __future__ import annotations

from pathlib import Path

import pytest

from crm.rounded_metrics import (
    compatible_correct_counts,
    read_reported_metrics,
    reconstruct_metrics,
    reconstruction_summary,
)

ROOT = Path(__file__).resolve().parent.parent


def test_historical_four_decimal_report_has_unique_integer_reconstruction() -> None:
    rows = reconstruct_metrics(
        read_reported_metrics(ROOT / "data" / "author_reported_class_metrics.csv")
    )
    observed = {row.label: (row.tp, row.fn, row.fp) for row in rows}
    assert observed == {
        "Roads and public works": (1785, 244, 280),
        "Public order police": (1097, 164, 204),
        "Transportation": (1524, 228, 281),
        "Urban village administration": (1247, 550, 292),
        "Parks and forestry": (821, 79, 99),
        "Water resources": (290, 101, 230),
        "Building, spatial planning, and land": (194, 27, 37),
        "Regional-owned enterprises": (200, 52, 98),
        "Other agency (catch-all)": (322, 341, 265),
    }


def test_reconstructed_aggregates_explain_accuracy_discrepancy() -> None:
    rows = reconstruct_metrics(
        read_reported_metrics(ROOT / "data" / "author_reported_class_metrics.csv")
    )
    summary = reconstruction_summary(rows)
    assert summary["samples"] == 9266
    assert summary["correct"] == 7480
    assert summary["false_negatives"] == summary["false_positives"] == 1786
    assert summary["accuracy"] == pytest.approx(7480 / 9266)
    assert f"{summary['accuracy']:.4f}" == "0.8073"
    assert compatible_correct_counts(9266, "0.8073") == [7480]
    assert compatible_correct_counts(9266, "0.8074") == [7481]
    assert f"{summary['macro_precision']:.4f}" == "0.7635"
    assert f"{summary['macro_recall']:.4f}" == "0.7916"
    assert f"{summary['balanced_accuracy']:.4f}" == "0.7916"
    assert f"{summary['macro_f1']:.4f}" == "0.7747"
    assert summary["urban_and_catch_all_false_negatives"] == 891
    assert 100 * summary["urban_and_catch_all_fn_share"] == pytest.approx(
        49.8880179171
    )
