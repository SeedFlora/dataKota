from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
from PIL import Image

from crm.splitting import (
    SplitBuildError,
    assert_group_disjoint,
    assert_strict_temporal_order,
    assign_group_temporal_split,
    build_class_map,
    build_leakage_groups,
    class_map_sha256,
    validate_split_preregistration,
)


class SplittingTest(unittest.TestCase):
    def test_cutoff_preregistration_binds_policy_before_label_use(self) -> None:
        declaration = {
            "schema_version": 1,
            "source_snapshot_sha256": "a" * 64,
            "created_at_utc": "2025-12-01T00:00:00+00:00",
            "data_custodian": "custodian-1",
            "test_labels_inspected": False,
            "rationale": "Chronological deployment simulation.",
            "attempt_log": [{"attempt": 1, "decision": "Freeze 70/15/15."}],
            "cutoff_policy": {
                "mode": "temporal_fraction",
                "train_fraction": 0.7,
                "val_fraction": 0.15,
            },
        }
        validated = validate_split_preregistration(
            declaration,
            source_snapshot_sha256="a" * 64,
            val_start=None,
            test_start=None,
            train_fraction=0.7,
            val_fraction=0.15,
        )
        self.assertEqual(validated["data_custodian"], "custodian-1")
        with self.assertRaisesRegex(SplitBuildError, "differ from the preregistered"):
            validate_split_preregistration(
                declaration,
                source_snapshot_sha256="a" * 64,
                val_start=None,
                test_start=None,
                train_fraction=0.6,
                val_fraction=0.2,
            )

    def test_class_map_is_ordered_one_to_one_and_self_hashed(self) -> None:
        frame = pd.DataFrame(
            {
                "label_id": [1, 0, 1, 0],
                "label": ["flood", "road", "flood", "road"],
            }
        )
        class_map = build_class_map(
            frame, label_id_column="label_id", label_name_column="label"
        )
        self.assertEqual(
            class_map["classes"],
            [
                {"label_id": 0, "label_name": "road"},
                {"label_id": 1, "label_name": "flood"},
            ],
        )
        self.assertEqual(class_map["sha256"], class_map_sha256(class_map))

    def test_duplicates_stay_in_one_temporal_partition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image_paths = []
            patterns = [0, 0, 1, 2, 3, 4]
            for index, pattern in enumerate(patterns):
                path = root / f"{index}.png"
                image = Image.new("L", (16, 16), 0)
                for x in range(16):
                    for y in range(16):
                        image.putpixel(
                            (x, y),
                            ((x * (pattern + 1) + y * (pattern * 3 + 1)) % 17) * 15,
                        )
                image.convert("RGB").save(path)
                image_paths.append(path.name)
            frame = pd.DataFrame(
                {
                    "row_id": list(range(6)),
                    "label_id": [0, 0, 1, 1, 0, 1],
                    "laporan": [
                        "jalan rusak",
                        "Jalan   rusak",
                        "pohon tumbang",
                        "sampah",
                        "banjir",
                        "lampu mati",
                    ],
                    "gambar": image_paths,
                    "created_at": pd.date_range(
                        "2026-01-01", periods=6, freq="30D", tz="UTC"
                    ),
                }
            )
            groups, _ = build_leakage_groups(
                frame,
                id_column="row_id",
                text_column="laporan",
                image_column="gambar",
                image_base=root,
            )
            frame["leakage_group_id"] = groups
            self.assertEqual(groups.iloc[0], groups.iloc[1])
            split, _ = assign_group_temporal_split(
                frame,
                time_column="created_at",
                val_start="2026-03-01",
                test_start="2026-05-01",
            )
            frame["split"] = split
            assert_group_disjoint(frame)
            self.assertEqual(frame.loc[0, "split"], frame.loc[1, "split"])

    def test_boundary_spanning_group_is_quarantined(self) -> None:
        frame = pd.DataFrame(
            {
                "leakage_group_id": ["train", "cross", "val", "cross", "test"],
                "created_at": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-15",
                        "2026-02-10",
                        "2026-03-05",
                        "2026-03-10",
                    ],
                    utc=True,
                ),
            }
        )
        assignment, receipt = assign_group_temporal_split(
            frame,
            time_column="created_at",
            val_start="2026-02-01",
            test_start="2026-03-01",
        )
        frame["split"] = assignment
        self.assertTrue(
            (
                frame.loc[frame["leakage_group_id"] == "cross", "split"] == "quarantine"
            ).all()
        )
        self.assertEqual(receipt.quarantined_groups, 1)
        self.assertEqual(receipt.quarantined_rows, 2)
        ranges = assert_strict_temporal_order(frame, time_column="created_at")
        self.assertLess(
            pd.Timestamp(ranges["train"]["max"]), pd.Timestamp(ranges["val"]["min"])
        )
        self.assertLess(
            pd.Timestamp(ranges["val"]["max"]), pd.Timestamp(ranges["test"]["min"])
        )


if __name__ == "__main__":
    unittest.main()
