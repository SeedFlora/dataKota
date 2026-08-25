from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "label_audit", ROOT / "tools" / "label_audit.py"
)
assert SPEC and SPEC.loader
label_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(label_audit)


class LabelAuditTest(unittest.TestCase):
    def test_exact_quota_total_and_minimum(self) -> None:
        quotas = label_audit._exact_stratified_quotas(
            {"a": 100, "b": 50, "c": 25}, total_n=40, min_per_class=5
        )
        self.assertEqual(sum(quotas.values()), 40)
        self.assertTrue(all(value >= 5 for value in quotas.values()))
        self.assertTrue(
            all(
                quotas[key] <= limit
                for key, limit in {"a": 100, "b": 50, "c": 25}.items()
            )
        )

    def test_score_writes_reproducible_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fields = label_audit.AUDIT_FIELDS
            a_path = tmp_path / "a.csv"
            b_path = tmp_path / "b.csv"
            rows_a = []
            rows_b = []
            for class_index, label in enumerate(label_audit.TARGET_CLASSES):
                rows_a.extend(
                    [
                        {
                            "row_id": f"{class_index}-a",
                            "label": label,
                            "image_path": f"{class_index}-a.jpg",
                            "laporan": f"report {class_index} a",
                            "plausible": "1",
                        },
                        {
                            "row_id": f"{class_index}-b",
                            "label": label,
                            "image_path": f"{class_index}-b.jpg",
                            "laporan": f"report {class_index} b",
                            "plausible": "0",
                            "reason_code": "routing_error",
                            "correct_label": label_audit.TARGET_CLASSES[
                                (class_index + 1) % len(label_audit.TARGET_CLASSES)
                            ],
                        },
                    ]
                )
            rows_b = [dict(row) for row in rows_a]
            rows_b[1]["plausible"] = "1"
            rows_b[1]["reason_code"] = ""
            rows_b[1]["correct_label"] = ""
            for path, rows in ((a_path, rows_a), (b_path, rows_b)):
                with path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fields)
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(row)

            report_path = tmp_path / "report.json"
            receipt_path = tmp_path / "sample.receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {
                        "class_population_sizes": {
                            label: 10 for label in label_audit.TARGET_CLASSES
                        },
                        "sample_content_sha256": label_audit._sample_content_sha256(
                            rows_a
                        ),
                        "release_authority": {
                            "file": "release.json",
                            "sha256": "a" * 64,
                            "authorization_mode": "post_locked_test_completion",
                            "authorized_at_utc": "2026-08-25T00:00:00+00:00",
                        },
                    }
                ),
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {
                    "files": [str(a_path), str(b_path)],
                    "sample_receipt": str(receipt_path),
                    "annotator_role": [
                        "Jakarta agency-domain reviewer A",
                        "Jakarta agency-domain reviewer B",
                    ],
                    "confirm_independent": label_audit.INDEPENDENCE_CONFIRMATION,
                    "json_out": str(report_path),
                },
            )()
            label_audit.cmd_score(args)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["annotators"][0]["micro_rate"], 0.5)
            self.assertEqual(report["annotators"][0]["file"], "a.csv")
            self.assertEqual(report["inter_annotator"]["paired_scored"], 18)
            self.assertEqual(report["inter_annotator"]["disagreement_count"], 1)
            self.assertNotIn("disagreement_row_ids", report["inter_annotator"])
            self.assertTrue(report["independent_annotation_attested"])
            self.assertEqual(
                report["annotators"][0]["annotator_role"],
                "Jakarta agency-domain reviewer A",
            )
            self.assertIn("micro_approx_stratified_95", report["annotators"][0])


if __name__ == "__main__":
    unittest.main()
