#!/usr/bin/env python3
"""Reproducible expert audit for the Jakarta CRM operational labels.

The 9-class targets are silver-standard routing outcomes, not adjudicated gold
labels. This command creates an exact-size stratified worksheet and scores one
or two independently completed copies with confidence intervals, agreement,
input checksums, and an optional JSON receipt.

Examples
--------
Generate the same 450-row audit sample for both annotators::

    python tools/label_audit.py sample --n 450 --min-per-class 30 \
        --release-authority private_audit/test_label_release.json \
        --out private_audit/audit_master.csv

Score two copies after independent annotation::

    python tools/label_audit.py score \
        --files private_audit/annotator_a.csv private_audit/annotator_b.csv \
        --sample-receipt private_audit/audit_master.csv.receipt.json \
        --annotator-role "Jakarta agency reviewer A" \
        --annotator-role "Jakarta agency reviewer B" \
        --confirm-independent I_CONFIRM_INDEPENDENT_ANNOTATION \
        --json-out private_audit/label_audit_report.json

Worksheets contain complaint text and image paths and can therefore be
sensitive. Keep them outside version control and share only aggregate output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from crm import TARGET_CLASSES

DEFAULT_SPLIT = ROOT / "artifacts" / "splits_q2" / "test.csv"
AUDIT_FIELDS = [
    "row_id",
    "label",
    "image_path",
    "laporan",
    "plausible",
    "correct_label",
    "reason_code",
    "notes",
]
REASON_CODES = {
    "ambiguous",
    "multi_agency",
    "insufficient_text",
    "insufficient_image",
    "mapping_error",
    "routing_error",
    "other",
}
BASE_AUDIT_FIELDS = ("row_id", "label", "image_path", "laporan")
INDEPENDENCE_CONFIRMATION = "I_CONFIRM_INDEPENDENT_ANNOTATION"


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"CSV is empty: {path}")
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sample_content_sha256(rows: list[dict[str, str]]) -> str:
    """Bind sample identity and review content without publishing either."""
    canonical = []
    for row in rows:
        canonical.append(
            {
                "row_id": _row_id(row),
                "label": (row.get("label") or "").strip(),
                "image_path": (
                    row.get("image_path") or row.get("gambar") or ""
                ).strip(),
                "laporan": " ".join((row.get("laporan") or "").split()),
            }
        )
    encoded = json.dumps(
        sorted(canonical, key=lambda item: item["row_id"]),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _row_id(row: dict[str, str]) -> str:
    for key in ("row_id", "report_id", "id"):
        value = (row.get(key) or "").strip()
        if value:
            return value
    raise ValueError("Every row requires row_id, report_id, or id")


def _exact_stratified_quotas(
    sizes: dict[str, int], total_n: int, min_per_class: int
) -> dict[str, int]:
    labels = sorted(sizes)
    if not labels:
        raise ValueError("No labels found")
    if total_n < min_per_class * len(labels):
        raise ValueError(
            f"n={total_n} is smaller than min_per_class * classes "
            f"({min_per_class} * {len(labels)})"
        )
    if total_n > sum(sizes.values()):
        raise ValueError("Requested sample is larger than the split")
    if any(sizes[label] < min_per_class for label in labels):
        small = {
            label: sizes[label] for label in labels if sizes[label] < min_per_class
        }
        raise ValueError(f"Classes smaller than min_per_class: {small}")

    quotas = {label: min_per_class for label in labels}
    remaining = total_n - sum(quotas.values())
    capacities = {label: sizes[label] - quotas[label] for label in labels}
    capacity_total = sum(capacities.values())
    if remaining == 0:
        return quotas

    raw = {label: remaining * capacities[label] / capacity_total for label in labels}
    for label in labels:
        add = min(capacities[label], math.floor(raw[label]))
        quotas[label] += add
    left = total_n - sum(quotas.values())
    order = sorted(
        labels,
        key=lambda label: (raw[label] - math.floor(raw[label]), sizes[label], label),
        reverse=True,
    )
    while left:
        progressed = False
        for label in order:
            if quotas[label] < sizes[label]:
                quotas[label] += 1
                left -= 1
                progressed = True
                if left == 0:
                    break
        if not progressed:
            raise RuntimeError("Unable to allocate the requested stratified sample")
    return quotas


def _validate_release_authority(path: Path, split_path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("release-authority receipt must use schema_version 1")
    if value.get("source_split_sha256") != _sha256(split_path):
        raise ValueError("release-authority receipt targets a different split")
    authorized_at = datetime.fromisoformat(
        str(value.get("authorized_at_utc", "")).replace("Z", "+00:00")
    )
    if (
        authorized_at.tzinfo is None
        or authorized_at.utcoffset() != timezone.utc.utcoffset(authorized_at)
    ):
        raise ValueError("authorized_at_utc must be timezone-aware UTC")
    if authorized_at > datetime.now(timezone.utc):
        raise ValueError("authorized_at_utc cannot be in the future")
    mode = value.get("authorization_mode")
    if mode == "independent_data_custodian":
        if (
            not value.get("custodian_role")
            or value.get("test_labels_not_disclosed_to_model_team") is not True
        ):
            raise ValueError(
                "custodian mode requires a role and non-disclosure attestation"
            )
    elif mode == "post_locked_test_completion":
        record = value.get("locked_test_completion_receipt")
        if (
            not isinstance(record, dict)
            or not record.get("path")
            or not record.get("sha256")
        ):
            raise ValueError(
                "post-test mode must bind the locked-test completion receipt"
            )
        completion = Path(str(record["path"]))
        if not completion.is_absolute():
            completion = path.parent / completion
        if not completion.is_file() or _sha256(completion) != record["sha256"]:
            raise ValueError("locked-test completion receipt is missing or changed")
        completion_value = json.loads(completion.read_text(encoding="utf-8"))
        if completion_value.get("phase") != "locked_test_complete":
            raise ValueError("bound receipt does not attest locked-test completion")
    else:
        raise ValueError(
            "authorization_mode must be independent_data_custodian or "
            "post_locked_test_completion"
        )
    return value


def cmd_sample(args: argparse.Namespace) -> None:
    split_path = Path(args.split)
    release_path = Path(args.release_authority)
    release = _validate_release_authority(release_path, split_path)
    rows = _read_rows(split_path)
    by_label: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_ids: set[str] = set()
    for row in rows:
        rid = _row_id(row)
        if rid in seen_ids:
            raise ValueError(f"Duplicate row id in split: {rid}")
        seen_ids.add(rid)
        label = (row.get("label") or "").strip()
        if not label:
            raise ValueError(f"Missing label for row {rid}")
        by_label[label].append(row)

    unknown = sorted(set(by_label) - set(TARGET_CLASSES))
    if unknown:
        raise ValueError(f"Unexpected labels: {unknown}")
    missing = sorted(set(TARGET_CLASSES) - set(by_label))
    if missing:
        raise ValueError(f"Target classes absent from split: {missing}")

    quotas = _exact_stratified_quotas(
        {label: len(items) for label, items in by_label.items()},
        args.n,
        args.min_per_class,
    )
    rng = random.Random(args.seed)
    picked: list[dict[str, str]] = []
    for label in sorted(by_label):
        picked.extend(rng.sample(by_label[label], quotas[label]))
    rng.shuffle(picked)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        for row in picked:
            writer.writerow(
                {
                    "row_id": _row_id(row),
                    "label": row.get("label", ""),
                    "image_path": row.get("gambar") or row.get("image_path") or "",
                    "laporan": (row.get("laporan") or "").replace("\n", " ").strip(),
                    "plausible": "",
                    "correct_label": "",
                    "reason_code": "",
                    "notes": "",
                }
            )

    receipt = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_split": str(split_path.resolve()),
        "source_sha256": _sha256(split_path),
        "worksheet": str(out.resolve()),
        "worksheet_sha256": _sha256(out),
        "seed": args.seed,
        "requested_n": args.n,
        "actual_n": len(picked),
        "min_per_class": args.min_per_class,
        "class_quotas": quotas,
        "class_population_sizes": {
            label: len(items) for label, items in sorted(by_label.items())
        },
        "sample_content_sha256": _sample_content_sha256(picked),
        "release_authority": {
            "file": release_path.name,
            "sha256": _sha256(release_path),
            "authorization_mode": release["authorization_mode"],
            "authorized_at_utc": release["authorized_at_utc"],
        },
    }
    receipt_path = out.with_suffix(out.suffix + ".receipt.json")
    receipt_path.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote exactly {len(picked)} samples across {len(by_label)} classes -> {out}"
    )
    print(f"Receipt -> {receipt_path}")
    print("Keep worksheets private; publish only aggregate audit statistics.")


def _to_bin(value: str | None) -> int | None:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "y", "yes", "ya", "true"}:
        return 1
    if normalized in {"0", "n", "no", "tidak", "false"}:
        return 0
    return None


def _wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return [max(0.0, centre - half), min(1.0, centre + half)]


def _load_annotation(path: Path) -> dict[str, dict[str, str]]:
    annotations: dict[str, dict[str, str]] = {}
    for row in _read_rows(path):
        rid = _row_id(row)
        if rid in annotations:
            raise ValueError(f"Duplicate row id in {path}: {rid}")
        plausible = _to_bin(row.get("plausible"))
        source_label = (row.get("label") or "").strip()
        corrected = (row.get("correct_label") or "").strip()
        reason = (row.get("reason_code") or "").strip()
        if source_label not in TARGET_CLASSES:
            raise ValueError(
                f"Invalid source label for {rid} in {path}: {source_label}"
            )
        if plausible == 0 and corrected:
            _parse_correct_labels(corrected, rid=rid, path=path)
        if plausible == 0 and not reason:
            raise ValueError(f"Implausible row {rid} in {path} requires a reason_code")
        if reason and reason not in REASON_CODES:
            raise ValueError(f"Invalid reason_code for {rid} in {path}: {reason}")
        annotations[rid] = row
    return annotations


def _parse_correct_labels(
    value: str, *, rid: str = "?", path: Path | None = None
) -> frozenset[str]:
    labels = frozenset(item.strip() for item in value.split("|") if item.strip())
    invalid = sorted(labels - set(TARGET_CLASSES))
    if invalid:
        location = f" in {path}" if path else ""
        raise ValueError(f"Invalid correct_label for {rid}{location}: {invalid}")
    return labels


def _resolved_label_set(row: dict[str, str], plausible: int) -> frozenset[str]:
    if plausible == 1:
        return frozenset({(row.get("label") or "").strip()})
    return _parse_correct_labels(row.get("correct_label") or "")


def _annotator_summary(
    path: Path,
    rows: dict[str, dict[str, str]],
    population_sizes: dict[str, int] | None,
) -> dict[str, Any]:
    scored = [(rid, row, _to_bin(row.get("plausible"))) for rid, row in rows.items()]
    scored = [(rid, row, value) for rid, row, value in scored if value is not None]
    if not scored:
        return {
            "file": path.name,
            "sha256": _sha256(path),
            "total_rows": len(rows),
            "scored_rows": 0,
        }

    successes = sum(value for _, _, value in scored)
    by_class: dict[str, list[int]] = defaultdict(list)
    reasons: dict[str, int] = defaultdict(int)
    for _, row, value in scored:
        by_class[row.get("label", "?")].append(value)
        reason = (row.get("reason_code") or "").strip()
        if reason:
            reasons[reason] += 1

    per_class = {
        label: {
            "n": len(values),
            "plausible": sum(values),
            "rate": sum(values) / len(values),
            "wilson_95": _wilson(sum(values), len(values)),
        }
        for label, values in sorted(by_class.items())
    }
    macro_rate = sum(item["rate"] for item in per_class.values()) / len(per_class)
    weighted_rate: float | None = None
    weighted_interval: list[float] | None = None
    if population_sizes:
        missing_strata = sorted(set(population_sizes) - set(per_class))
        if missing_strata:
            raise ValueError(
                f"Audit sample is missing population strata: {missing_strata}"
            )
        population_total = sum(population_sizes.values())
        weighted_rate = sum(
            (population_sizes[label] / population_total) * per_class[label]["rate"]
            for label in population_sizes
        )
        variance = 0.0
        for label, population_n in population_sizes.items():
            sample_n = per_class[label]["n"]
            rate = per_class[label]["rate"]
            if sample_n > 1 and population_n > 1:
                weight = population_n / population_total
                finite_population = max(0.0, 1.0 - sample_n / population_n)
                variance += (
                    weight
                    * weight
                    * finite_population
                    * rate
                    * (1.0 - rate)
                    / (sample_n - 1)
                )
        half = 1.959963984540054 * math.sqrt(variance)
        weighted_interval = [
            max(0.0, weighted_rate - half),
            min(1.0, weighted_rate + half),
        ]
    multi_agency = sum(
        len(_resolved_label_set(row, value)) > 1
        or (row.get("reason_code") or "").strip() == "multi_agency"
        for _, row, value in scored
    )
    return {
        # Keep public aggregate reports free of workstation/user directory paths.
        "file": path.name,
        "sha256": _sha256(path),
        "total_rows": len(rows),
        "scored_rows": len(scored),
        "plausible": successes,
        "sample_unweighted_rate": successes / len(scored),
        # This is the population-level micro estimate under the stratified
        # sampling design; a raw sample mean would be biased when quotas differ.
        "micro_rate": weighted_rate,
        "micro_approx_stratified_95": weighted_interval,
        "macro_rate": macro_rate,
        "per_class": per_class,
        "reason_counts": dict(sorted(reasons.items())),
        "multi_agency_count": int(multi_agency),
        "multi_agency_sample_rate": float(multi_agency / len(scored)),
    }


def _cohen_kappa(first: list[int], second: list[int]) -> tuple[float, float | None]:
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / n
    p_first_yes = sum(first) / n
    p_second_yes = sum(second) / n
    expected = p_first_yes * p_second_yes + (1 - p_first_yes) * (1 - p_second_yes)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    return observed, kappa


def cmd_score(args: argparse.Namespace) -> None:
    files = [Path(item) for item in args.files]
    if not 1 <= len(files) <= 2:
        raise ValueError("Score exactly one or two independent annotation files")
    annotator_roles = list(getattr(args, "annotator_role", []) or [])
    if len(annotator_roles) != len(files) or any(
        not role.strip() for role in annotator_roles
    ):
        raise ValueError("Provide one non-empty --annotator-role for each worksheet")
    if (
        len(files) == 2
        and getattr(args, "confirm_independent", None) != INDEPENDENCE_CONFIRMATION
    ):
        raise ValueError(
            "Two-annotator scoring requires --confirm-independent "
            f"{INDEPENDENCE_CONFIRMATION}"
        )
    receipt_value = getattr(args, "sample_receipt", None)
    if not receipt_value:
        raise ValueError(
            "--sample-receipt is required to verify the master sample and compute "
            "design-weighted prevalence"
        )
    sample_receipt_path = Path(receipt_value)
    sample_receipt = json.loads(sample_receipt_path.read_text(encoding="utf-8"))
    population_sizes = {
        str(label): int(size)
        for label, size in sample_receipt.get("class_population_sizes", {}).items()
    }
    if not population_sizes or set(population_sizes) != set(TARGET_CLASSES):
        raise ValueError("Sample receipt lacks all target class population sizes")
    release_authority = sample_receipt.get("release_authority")
    if (
        not isinstance(release_authority, dict)
        or release_authority.get("authorization_mode")
        not in {"independent_data_custodian", "post_locked_test_completion"}
        or not release_authority.get("sha256")
        or not release_authority.get("authorized_at_utc")
    ):
        raise ValueError("Sample receipt lacks a valid test-label release authority")

    annotations = [_load_annotation(path) for path in files]
    expected_content_hash = sample_receipt.get("sample_content_sha256")
    if not expected_content_hash:
        raise ValueError("Sample receipt has no sample_content_sha256")
    for path, rows in zip(files, annotations):
        actual_content_hash = _sample_content_sha256(list(rows.values()))
        if actual_content_hash != expected_content_hash:
            raise ValueError(
                f"{path} does not match the receipt-bound master sample/content"
            )
    summaries = [
        _annotator_summary(path, rows, population_sizes)
        for path, rows in zip(files, annotations)
    ]
    for summary, role in zip(summaries, annotator_roles):
        summary["annotator_role"] = role.strip()
    incomplete = [
        summary["file"]
        for summary in summaries
        if summary["scored_rows"] != summary["total_rows"]
    ]
    if incomplete:
        raise ValueError(
            "Every worksheet row must have a valid plausible value before final "
            f"scoring; incomplete: {incomplete}"
        )
    report: dict[str, Any] = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "annotators": summaries,
        "target_classes": list(TARGET_CLASSES),
        "sample_receipt": sample_receipt_path.name,
        "sample_receipt_sha256": _sha256(sample_receipt_path),
        "sample_content_sha256": expected_content_hash,
        "sampling_design": "stratified_without_replacement",
        "independent_annotation_attested": len(files) == 2,
        "test_label_release_authority": dict(release_authority),
    }

    for summary in summaries:
        print(
            f"\n{Path(summary['file']).name}: {summary['scored_rows']}/{summary['total_rows']} scored"
        )
        if summary["scored_rows"]:
            low, high = summary["micro_approx_stratified_95"]
            print(
                f"  plausibility {summary['micro_rate']:.3f} "
                f"(approx. stratified 95% CI {low:.3f}-{high:.3f})"
            )
            print(f"  macro plausibility {summary['macro_rate']:.3f}")
            for label, item in summary["per_class"].items():
                print(f"    {label:<48} {item['rate']:.3f} (n={item['n']})")

    if len(annotations) >= 2:
        first, second = annotations[:2]
        if set(first) != set(second):
            raise ValueError(
                "The first two annotation files must contain exactly the same row ids"
            )
        all_common = sorted(set(first) & set(second))
        paired: list[tuple[str, int, int]] = []
        for rid in all_common:
            if (first[rid].get("label") or "").strip() != (
                second[rid].get("label") or ""
            ).strip():
                raise ValueError(
                    f"Source label differs between annotators for row {rid}"
                )
            a = _to_bin(first[rid].get("plausible"))
            b = _to_bin(second[rid].get("plausible"))
            if a is not None and b is not None:
                paired.append((rid, a, b))
        if not paired:
            raise ValueError("The first two files have no commonly scored row ids")
        observed, kappa = _cohen_kappa(
            [item[1] for item in paired], [item[2] for item in paired]
        )
        disagreements = [rid for rid, a, b in paired if a != b]
        resolved_pairs = [
            (
                _resolved_label_set(first[rid], a),
                _resolved_label_set(second[rid], b),
            )
            for rid, a, b in paired
        ]
        label_pairs = [pair for pair in resolved_pairs if pair[0] and pair[1]]
        exact_label_agreement = (
            sum(left == right for left, right in label_pairs) / len(label_pairs)
            if label_pairs
            else None
        )
        mean_label_jaccard = (
            sum(len(left & right) / len(left | right) for left, right in label_pairs)
            / len(label_pairs)
            if label_pairs
            else None
        )
        report["inter_annotator"] = {
            "common_row_ids": len(all_common),
            "paired_scored": len(paired),
            "observed_agreement": observed,
            "cohen_kappa": kappa,
            "disagreement_count": len(disagreements),
            "resolved_label_pairs": len(label_pairs),
            "resolved_label_exact_agreement": exact_label_agreement,
            "resolved_label_mean_jaccard": mean_label_jaccard,
            # Row identifiers stay in the private worksheets used for adjudication.
            "only_in_first_count": 0,
            "only_in_second_count": 0,
        }
        kappa_text = "undefined" if kappa is None else f"{kappa:.3f}"
        print(
            f"\nInter-annotator: n={len(paired)}, agreement={observed:.3f}, "
            f"Cohen's kappa={kappa_text}, disagreements={len(disagreements)}"
        )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Machine-readable report -> {out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sample = sub.add_parser("sample", help="generate a private annotation worksheet")
    sample.add_argument("--split", default=str(DEFAULT_SPLIT))
    sample.add_argument("--n", type=int, default=450)
    sample.add_argument("--min-per-class", type=int, default=30)
    sample.add_argument("--seed", type=int, default=20260825)
    sample.add_argument(
        "--release-authority",
        required=True,
        help="receipt authorizing test-label access by a custodian or after locked test",
    )
    sample.add_argument("--out", default="private_audit/audit_master.csv")
    sample.set_defaults(func=cmd_sample)

    score = sub.add_parser("score", help="score one or two completed worksheets")
    score.add_argument("--files", nargs="+", required=True)
    score.add_argument("--sample-receipt", required=True)
    score.add_argument(
        "--annotator-role",
        action="append",
        required=True,
        help="non-identifying domain role; repeat once per worksheet",
    )
    score.add_argument(
        "--confirm-independent",
        help=f"for two files, pass exactly {INDEPENDENCE_CONFIRMATION}",
    )
    score.add_argument("--json-out")
    score.set_defaults(func=cmd_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
