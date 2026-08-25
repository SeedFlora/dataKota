#!/usr/bin/env python3
"""Run validation-only selection and the separate one-shot locked test phase."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm.experiments.config import load_config
from crm.experiments.runner import run_locked_test, run_selection

TEST_CONFIRMATION = "I_UNDERSTAND_TEST_IS_ONE_SHOT"


def select_command(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    run_dir = run_selection(
        config,
        run_dir=Path(args.run_dir).resolve() if args.run_dir else None,
        resume=args.resume,
    )
    receipt_path = run_dir / "selection" / "selection_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "phase": "selection_complete",
                "selected_candidate": receipt["selected_candidate"],
                "test_csv_parsed": receipt["test_csv_parsed"],
                "next": (
                    "python tools/run_q2_experiment.py evaluate-test "
                    f'--run-dir "{run_dir}" --confirm {TEST_CONFIRMATION}'
                ),
            },
            indent=2,
        )
    )
    return 0


def test_command(args: argparse.Namespace) -> int:
    if args.confirm != TEST_CONFIRMATION:
        raise SystemExit(
            "Refusing to open test.csv. Pass "
            f"--confirm {TEST_CONFIRMATION} only after the selection receipt is frozen."
        )
    run_dir = run_locked_test(Path(args.run_dir))
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "phase": "locked_test_complete",
                "receipt": str(run_dir / "test" / "TEST_EVALUATION_COMPLETE.json"),
            },
            indent=2,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    subcommands = command.add_subparsers(dest="command", required=True)

    select = subcommands.add_parser(
        "select",
        help="fit all seeds/candidates and select using train+validation only",
    )
    select.add_argument("--config", required=True)
    select.add_argument("--run-dir")
    select.add_argument(
        "--resume",
        action="store_true",
        help="resume an interrupted selection with the exact frozen config/inputs",
    )
    select.set_defaults(function=select_command)

    evaluate = subcommands.add_parser(
        "evaluate-test",
        help="open the frozen test split exactly once for preregistered candidates",
    )
    evaluate.add_argument("--run-dir", required=True)
    evaluate.add_argument("--confirm", required=True)
    evaluate.set_defaults(function=test_command)
    return command


if __name__ == "__main__":
    arguments = parser().parse_args()
    sys.exit(arguments.function(arguments))
