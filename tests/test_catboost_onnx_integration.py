from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.deployment import classifier_parity_report, normalize_probability_output
from crm.pgs import pgs_predict
from crm.splitting import class_map_sha256

try:
    import onnxruntime as ort
    from catboost import CatBoostClassifier
except ImportError:  # pragma: no cover - optional in lightweight developer envs
    ort = None
    CatBoostClassifier = None


@unittest.skipIf(
    ort is None or CatBoostClassifier is None,
    "catboost and onnxruntime are required for export integration",
)
class CatBoostOnnxIntegrationTest(unittest.TestCase):
    def test_real_virtual_ensembles_and_onnx_export_follow_contract(self):
        rng = np.random.default_rng(42)
        features = rng.normal(size=(120, 8)).astype(np.float32)
        labels = np.argmax(
            np.column_stack(
                (
                    features[:, 0] + features[:, 1],
                    features[:, 2] - features[:, 3],
                    -features[:, 0] + features[:, 4],
                )
            ),
            axis=1,
        )
        model = CatBoostClassifier(
            iterations=60,
            depth=4,
            loss_function="MultiClass",
            posterior_sampling=True,
            random_seed=42,
            verbose=False,
            allow_writing_files=False,
        )
        model.fit(features, labels)

        posterior = pgs_predict(model, features[:7], n_virtual_ensembles=5)
        self.assertEqual(posterior.probabilities.shape, (7, 3))
        np.testing.assert_allclose(
            posterior.probabilities.sum(axis=1),
            1.0,
            atol=1e-6,
        )
        self.assertTrue(np.all(posterior.epistemic_mutual_information >= 0.0))

        with tempfile.TemporaryDirectory() as tmp:
            onnx_path = Path(tmp) / "classifier.onnx"
            native_path = Path(tmp) / "classifier.cbm"
            features_path = Path(tmp) / "features.npy"
            ids_path = Path(tmp) / "test_ids.json"
            split_manifest_path = Path(tmp) / "split_manifest.json"
            class_map_path = Path(tmp) / "class_map.json"
            test_csv_path = Path(tmp) / "test.csv"
            feature_receipt_path = Path(tmp) / "features.receipt.json"
            image_embeddings_path = Path(tmp) / "image.npy"
            text_embeddings_path = Path(tmp) / "text.npy"
            image_receipt_path = Path(tmp) / "image.receipt.json"
            text_receipt_path = Path(tmp) / "text.receipt.json"
            report_path = Path(tmp) / "parity.json"
            model.save_model(str(onnx_path), format="onnx")
            model.save_model(str(native_path))
            np.save(features_path, features[:20], allow_pickle=False)
            np.save(image_embeddings_path, features[:, :3], allow_pickle=False)
            np.save(text_embeddings_path, features[:, 3:], allow_pickle=False)
            ids_path.write_text(
                json.dumps([f"test-{index}" for index in range(20)]),
                encoding="utf-8",
            )
            test_csv_path.write_text(
                "row_id,embedding_index\n"
                + "".join(f"test-{index},{index}\n" for index in range(20)),
                encoding="utf-8",
            )
            class_map = {
                "schema_version": 1,
                "label_id_column": "label_id",
                "label_name_column": "label",
                "classes": [
                    {"label_id": index, "label_name": f"class-{index}"}
                    for index in range(3)
                ],
            }
            class_map["sha256"] = class_map_sha256(class_map)
            class_map_path.write_text(json.dumps(class_map), encoding="utf-8")
            split_manifest = {
                "strategy": "grouped_strict_temporal_holdout",
                "parameters": {"id_column": "row_id"},
                "embedding_index": {"column": "embedding_index"},
                "class_map": class_map,
                "outputs": {
                    "test": {
                        "path": test_csv_path.name,
                        "sha256": hashlib.sha256(
                            test_csv_path.read_bytes()
                        ).hexdigest(),
                    }
                },
            }
            split_manifest_path.write_text(json.dumps(split_manifest), encoding="utf-8")
            ordered_ids_digest = hashlib.sha256(
                json.dumps(
                    [f"test-{index}" for index in range(20)],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            image_hash = hashlib.sha256(image_embeddings_path.read_bytes()).hexdigest()
            text_hash = hashlib.sha256(text_embeddings_path.read_bytes()).hexdigest()
            image_preprocessing_hash = "d" * 64
            text_preprocessing_hash = "e" * 64
            image_receipt_path.write_text(
                json.dumps(
                    {
                        "encoder_name": "synthetic_image",
                        "embedding_sha256": image_hash,
                        "preprocessing_sha256": image_preprocessing_hash,
                        "dimension": 3,
                        "dtype": "float32",
                    }
                ),
                encoding="utf-8",
            )
            text_receipt_path.write_text(
                json.dumps(
                    {
                        "encoder_name": "synthetic_text",
                        "embedding_sha256": text_hash,
                        "preprocessing_sha256": text_preprocessing_hash,
                        "dimension": 5,
                        "dtype": "float32",
                    }
                ),
                encoding="utf-8",
            )
            feature_receipt_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "selected_candidate": "synthetic_multimodal",
                        "feature_sample_sha256": hashlib.sha256(
                            features_path.read_bytes()
                        ).hexdigest(),
                        "rows": 20,
                        "dimension": 8,
                        "ordered_test_ids_sha256": ordered_ids_digest,
                        "split_manifest_sha256": hashlib.sha256(
                            split_manifest_path.read_bytes()
                        ).hexdigest(),
                        "class_map_semantic_sha256": class_map["sha256"],
                        "extraction_code_commit": "a" * 40,
                        "embedding_index_column": "embedding_index",
                        "fusion": {
                            "operation": "concatenate",
                            "modality_order": ["image", "text"],
                            "axis": 1,
                            "l2_per_modality": False,
                            "l2_epsilon": 1e-9,
                            "output_dtype": "float32",
                        },
                        "source_embeddings": {
                            "image": {
                                "key": "image:synthetic_image",
                                "encoder_name": "synthetic_image",
                                "path": image_embeddings_path.name,
                                "sha256": image_hash,
                                "extraction_receipt_path": image_receipt_path.name,
                                "extraction_receipt_sha256": hashlib.sha256(
                                    image_receipt_path.read_bytes()
                                ).hexdigest(),
                                "preprocessing_sha256": image_preprocessing_hash,
                                "dimension": 3,
                                "dtype": "float32",
                            },
                            "text": {
                                "key": "text:synthetic_text",
                                "encoder_name": "synthetic_text",
                                "path": text_embeddings_path.name,
                                "sha256": text_hash,
                                "extraction_receipt_path": text_receipt_path.name,
                                "extraction_receipt_sha256": hashlib.sha256(
                                    text_receipt_path.read_bytes()
                                ).hexdigest(),
                                "preprocessing_sha256": text_preprocessing_hash,
                                "dimension": 5,
                                "dtype": "float32",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            session = ort.InferenceSession(
                str(onnx_path),
                providers=["CPUExecutionProvider"],
            )
            deployed = normalize_probability_output(
                session.run(None, {session.get_inputs()[0].name: features[:20]})[-1],
                range(3),
            )
            report = classifier_parity_report(
                model.predict_proba(features[:20]),
                deployed,
                probability_tolerance=1e-5,
            )
            self.assertTrue(report.passed, report.to_dict())

            command = [
                sys.executable,
                str(ROOT / "tools" / "check_classifier_parity.py"),
                "--native",
                str(native_path),
                "--onnx",
                str(onnx_path),
                "--features",
                str(features_path),
                "--class-count",
                "3",
                "--test-ids",
                str(ids_path),
                "--split-manifest",
                str(split_manifest_path),
                "--class-map",
                str(class_map_path),
                "--feature-receipt",
                str(feature_receipt_path),
                "--output",
                str(report_path),
            ]
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            receipt = json.loads(report_path.read_text(encoding="utf-8"))
            expected_hash = hashlib.sha256(features_path.read_bytes()).hexdigest()
            self.assertEqual(receipt["feature_sample_sha256"], expected_hash)
            self.assertTrue(receipt["passed"])

            if report.max_absolute_probability_error > 0.0:
                failed = subprocess.run(
                    [*command[:-2], "--probability-tolerance", "0"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(failed.returncode, 1)
                self.assertEqual(failed.stdout, "")
                self.assertIn(
                    "classifier parity tolerances must equal the frozen export policy",
                    failed.stderr,
                )


if __name__ == "__main__":
    unittest.main()
