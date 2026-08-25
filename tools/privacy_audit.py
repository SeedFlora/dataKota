#!/usr/bin/env python3
"""Aggregate privacy audit for CRM text and image metadata.

The report never includes raw complaint text or detected values. Optional
row-level findings use a salted SHA-256 identifier so the public aggregate can
be shared without exposing report ids. Face and license-plate detection remain
a required separate visual audit; this tool does not claim to detect them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

PATTERNS = {
    "email": re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"),
    "phone": re.compile(r"(?<!\d)(?:\+?62|0)[\s.-]?(?:\d[\s.-]?){8,13}(?!\d)"),
    "long_numeric_id": re.compile(r"(?<!\d)\d{16}(?!\d)"),
    "url": re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE),
    "indonesian_plate": re.compile(
        r"(?<![A-Z0-9])(?:B|D|F|T|E|Z|A|G|H|K|R|AA|AB|AD)\s?\d{1,4}\s?[A-Z]{1,3}(?![A-Z0-9])",
        re.IGNORECASE,
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _private_id(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def _resolve_image(base_dir: Path, value: str) -> Path | None:
    value = value.strip()
    if not value:
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else base_dir / candidate


def _image_metadata_findings(path: Path) -> set[str]:
    findings: set[str] = set()
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return findings
            findings.add("image_exif_present")
            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag == "GPSInfo" and value:
                    findings.add("image_exif_gps")
                elif (
                    tag in {"DateTime", "DateTimeOriginal", "DateTimeDigitized"}
                    and value
                ):
                    findings.add("image_exif_datetime")
                elif (
                    tag in {"Make", "Model", "BodySerialNumber", "LensSerialNumber"}
                    and value
                ):
                    findings.add("image_device_metadata")
    except (OSError, ValueError):
        findings.add("image_unreadable")
    return findings


def audit(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv)
    if not csv_path.is_file():
        raise FileNotFoundError(csv_path)
    base_dir = Path(args.base_dir) if args.base_dir else csv_path.parent
    counts: Counter[str] = Counter()
    affected_rows: Counter[str] = Counter()
    findings_rows: list[dict[str, Any]] = []
    total = 0
    if args.findings_out and (not args.salt or len(args.salt) < 16):
        raise ValueError(
            "Private row-level findings require a secret salt of at least 16 "
            "characters via CRM_PRIVACY_AUDIT_SALT or --salt"
        )

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        required = {args.text_col}
        if args.image_col:
            required.add(args.image_col)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing columns: {sorted(missing)}")
        for index, row in enumerate(reader):
            total += 1
            text = row.get(args.text_col) or ""
            row_findings: set[str] = set()
            for name, pattern in PATTERNS.items():
                matches = pattern.findall(text)
                if matches:
                    counts[name] += len(matches)
                    affected_rows[name] += 1
                    row_findings.add(name)

            if args.image_col:
                image_path = _resolve_image(base_dir, row.get(args.image_col) or "")
                if image_path is not None:
                    if image_path.is_file():
                        for name in _image_metadata_findings(image_path):
                            counts[name] += 1
                            affected_rows[name] += 1
                            row_findings.add(name)
                    else:
                        counts["image_missing"] += 1
                        affected_rows["image_missing"] += 1
                        row_findings.add("image_missing")

            if row_findings and args.findings_out:
                raw_id = (
                    (row.get(args.id_col) or "").strip() if args.id_col else str(index)
                )
                findings_rows.append(
                    {
                        "private_row_id": _private_id(raw_id or str(index), args.salt),
                        "finding_types": sorted(row_findings),
                    }
                )

    report = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        # A basename plus digest is enough to bind the snapshot without leaking
        # a contributor's local username or directory structure.
        "input": csv_path.name,
        "input_sha256": _sha256(csv_path),
        "rows_scanned": total,
        "text_column": args.text_col,
        "image_column": args.image_col,
        "finding_occurrences": dict(sorted(counts.items())),
        "affected_rows": dict(sorted(affected_rows.items())),
        "limitations": [
            "Regex findings are screening signals and require secure human adjudication.",
            "The tool does not inspect image pixels for faces, people, addresses, or license plates.",
            "The Indonesian plate regex covers common regional prefixes only and is not exhaustive.",
            "A legal-basis, retention, access-control, and release-risk review is still required.",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.findings_out:
        findings_path = Path(args.findings_out)
        findings_path.parent.mkdir(parents=True, exist_ok=True)
        findings_path.write_text(
            json.dumps(findings_rows, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(f"Scanned {total} rows; aggregate report -> {out}")
    print("Pixel-level face/license-plate review remains mandatory.")
    return 2 if args.fail_on_findings and any(counts.values()) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--text-col", default="laporan")
    parser.add_argument("--image-col", default="gambar")
    parser.add_argument("--id-col", default="row_id")
    parser.add_argument("--base-dir")
    parser.add_argument("--out", default="artifacts/audits/privacy_aggregate.json")
    parser.add_argument(
        "--findings-out", help="private, hashed row-level findings JSON"
    )
    parser.add_argument(
        "--salt",
        default=os.getenv("CRM_PRIVACY_AUDIT_SALT"),
        help=(
            "secret salt for private hashed row findings; prefer the "
            "CRM_PRIVACY_AUDIT_SALT environment variable and never publish it"
        ),
    )
    parser.add_argument("--fail-on-findings", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    return audit(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
