#!/usr/bin/env python3
"""Reconstruct integer class margins from the paper's rounded metric table."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm.rounded_metrics import (  # noqa: E402
    compatible_correct_counts,
    read_reported_metrics,
    reconstruct_metrics,
    reconstructed_rows_as_dicts,
    reconstruction_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exhaustively enumerate integer TP/FN/FP margins compatible with "
            "four-decimal precision, recall, F1, and support."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "author_reported_class_metrics.csv",
    )
    parser.add_argument("--csv-out", type=Path)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reconstructed = reconstruct_metrics(read_reported_metrics(args.input))
    summary = reconstruction_summary(reconstructed)
    summary["correct_counts_rounding_to_0.8073"] = compatible_correct_counts(
        int(summary["samples"]), "0.8073"
    )
    summary["correct_counts_rounding_to_0.8074"] = compatible_correct_counts(
        int(summary["samples"]), "0.8074"
    )

    if args.csv_out:
        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        rows = reconstructed_rows_as_dicts(reconstructed)
        with args.csv_out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
