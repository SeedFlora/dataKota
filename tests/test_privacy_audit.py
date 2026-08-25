from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "privacy_audit", ROOT / "tools" / "privacy_audit.py"
)
assert SPEC and SPEC.loader
privacy_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(privacy_audit)


class PrivacyAuditTest(unittest.TestCase):
    def test_reports_counts_without_raw_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "reports.csv"
            with source.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["row_id", "laporan", "gambar"])
                writer.writeheader()
                writer.writerow(
                    {
                        "row_id": "secret-report-id",
                        "laporan": "Hubungi test@example.com atau 0812-3456-7890",
                        "gambar": "",
                    }
                )
            out = root / "aggregate.json"
            private = root / "private.json"
            args = privacy_audit.build_parser().parse_args(
                [
                    "--csv",
                    str(source),
                    "--out",
                    str(out),
                    "--findings-out",
                    str(private),
                    "--salt",
                    "test-only-secret-salt",
                ]
            )
            self.assertEqual(privacy_audit.audit(args), 0)
            aggregate_text = out.read_text(encoding="utf-8")
            report = json.loads(aggregate_text)
            self.assertEqual(report["affected_rows"]["email"], 1)
            self.assertEqual(report["affected_rows"]["phone"], 1)
            self.assertNotIn("test@example.com", aggregate_text)
            self.assertNotIn("0812", aggregate_text)
            self.assertNotIn("secret-report-id", private.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
