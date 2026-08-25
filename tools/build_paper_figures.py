#!/usr/bin/env python3
"""Build the paper's non-AI aggregate error-concentration figure."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm.rounded_metrics import read_reported_metrics, reconstruct_metrics  # noqa: E402

SHORT_LABELS = {
    "Roads and public works": "Roads/public works",
    "Public order police": "Public-order police",
    "Transportation": "Transportation",
    "Urban village administration": "Urban village",
    "Parks and forestry": "Parks/forestry",
    "Water resources": "Water resources",
    "Building, spatial planning, and land": "Building/spatial/land",
    "Regional-owned enterprises": "Regional enterprises",
    "Other agency (catch-all)": "Other (catch-all)",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "author_reported_class_metrics.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "figures" / "reconstructed_class_errors.pdf",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rows = reconstruct_metrics(read_reported_metrics(args.input))
    labels = [SHORT_LABELS[row.label] for row in rows]
    false_negatives = np.array([row.fn for row in rows])
    false_positives = np.array([row.fp for row in rows])
    y = np.arange(len(rows))
    height = 0.36

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.labelsize": 9,
            "legend.fontsize": 8.5,
        }
    )
    figure, axis = plt.subplots(figsize=(6.7, 4.25), constrained_layout=True)
    axis.barh(
        y - height / 2,
        false_negatives,
        height,
        label="False negatives",
        color="#D55E00",
    )
    axis.barh(
        y + height / 2,
        false_positives,
        height,
        label="False positives",
        color="#0072B2",
    )
    for index, value in enumerate(false_negatives):
        axis.text(value + 7, index - height / 2, str(value), va="center", fontsize=7.6)
    for index, value in enumerate(false_positives):
        axis.text(value + 7, index + height / 2, str(value), va="center", fontsize=7.6)
    axis.set_yticks(y, labels)
    axis.invert_yaxis()
    axis.set_xlabel("Reconstructed count")
    axis.set_xlim(0, max(false_negatives.max(), false_positives.max()) * 1.14)
    axis.grid(axis="x", color="#D9D9D9", linewidth=0.6)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(loc="lower right", frameon=False)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, bbox_inches="tight")
    plt.close(figure)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
