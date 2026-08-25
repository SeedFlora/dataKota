from __future__ import annotations

import asyncio
import base64
import importlib
import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
from fastapi import HTTPException, UploadFile
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class ServerImportTest(unittest.TestCase):
    def test_import_does_not_open_model_artifacts_or_external_agency_store(self):
        module = importlib.import_module("serve_model")
        self.assertIsNone(module.pipe)
        self.assertEqual(module._AGENCY_STATE["source"], "none")
        self.assertEqual(module._AGENCY_STATE["agencies"], [])

    def test_only_server_side_supabase_credentials_are_accepted(self):
        module = importlib.import_module("serve_model")
        payload = base64.urlsafe_b64encode(b'{"role":"anon"}').decode().rstrip("=")
        with self.assertRaisesRegex(RuntimeError, "not a service_role"):
            module._validate_service_role_credential(f"header.{payload}.signature")
        service_payload = (
            base64.urlsafe_b64encode(b'{"role":"service_role"}').decode().rstrip("=")
        )
        module._validate_service_role_credential(f"header.{service_payload}.signature")

    def test_runtime_averages_every_frozen_onnx_seed_head_equally(self):
        module = importlib.import_module("serve_model")

        class FakeSession:
            def __init__(self, probabilities):
                self.probabilities = probabilities

            def run(self, _outputs, _inputs):
                return [None, self.probabilities]

        pipeline = module.CRMPipeline.__new__(module.CRMPipeline)
        pipeline.seeds = (13, 42, 73, 101, 137)
        member_probabilities = []
        for first, second in (
            (0.9, 0.1),
            (0.8, 0.2),
            (0.7, 0.3),
            (0.4, 0.6),
            (0.2, 0.8),
        ):
            probabilities = np.zeros((1, len(module.TARGET_CLASSES)), dtype=np.float32)
            probabilities[0, :2] = (first, second)
            member_probabilities.append(probabilities)
        pipeline.classifier_sessions = [
            (seed, FakeSession(probabilities), "features")
            for seed, probabilities in zip(
                pipeline.seeds, member_probabilities, strict=True
            )
        ]
        actual = pipeline._onnx_probabilities(np.zeros((1, 2), dtype=np.float32))
        expected = np.zeros((1, len(module.TARGET_CLASSES)), dtype=np.float32)
        expected[0, :2] = (0.6, 0.4)
        np.testing.assert_allclose(actual, expected, atol=1e-7)

    def test_review_required_prediction_has_no_active_assignment(self):
        module = importlib.import_module("serve_model")

        class FakePipeline:
            model_name = "test-model"
            model_version = "test-version"
            export_manifest_sha256 = "a" * 64
            class_map_sha256 = "b" * 64
            confidence_threshold = 0.7
            epistemic_uncertainty_threshold = None

            def predict(self, _image, _text):
                probabilities = np.zeros(len(module.TARGET_CLASSES), dtype=np.float32)
                probabilities[0] = 0.4
                probabilities[1:] = 0.6 / (len(probabilities) - 1)
                return module.PipelinePrediction(
                    label=module.TARGET_CLASSES[0],
                    label_id=0,
                    confidence=0.4,
                    probabilities=probabilities,
                    inference_method=module.ONNX_SEED_ENSEMBLE_METHOD,
                )

        agency = module.AgencyCandidate(
            agency_id="agency-1",
            name="Candidate agency",
            category=module.TARGET_CLASSES[0],
            latitude=-6.2,
            longitude=106.8,
        )
        buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="JPEG")
        upload = UploadFile(filename="test.jpg", file=BytesIO(buffer.getvalue()))
        with (
            patch.object(module, "require_pipeline", return_value=FakePipeline()),
            patch.object(module, "find_nearest_agency", return_value=(agency, 10.0)),
        ):
            response = asyncio.run(
                module.predict(
                    image=upload,
                    laporan="jalan rusak",
                    latitude=-6.2,
                    longitude=106.8,
                )
            )
        self.assertTrue(response.review_required)
        self.assertIsNone(response.assignment)

    def test_untrusted_seed_registry_cannot_authorize_assignment(self):
        module = importlib.import_module("serve_model")
        agency = module.AgencyCandidate(
            agency_id="agency-1",
            name="Seed-only agency",
            category=module.TARGET_CLASSES[0],
            latitude=-6.2,
            longitude=106.8,
        )
        with patch.dict(
            module._AGENCY_STATE,
            {
                "agencies": [agency],
                "source": "seed_fallback",
                "status": "untrusted_fallback",
                "routing_ready": False,
                "coverage_gaps": module.TARGET_CLASSES[1:],
            },
            clear=True,
        ):
            self.assertIsNone(
                module.find_nearest_agency(module.TARGET_CLASSES[0], -6.2, 106.8)
            )
            self.assertEqual(
                module.routing_review_reasons(module.TARGET_CLASSES[0], -6.2, 106.8),
                ["agency_registry_untrusted"],
            )

    def test_registry_failure_exposes_only_sanitized_state(self):
        module = importlib.import_module("serve_model")
        agency = module.AgencyCandidate(
            agency_id="seed-1",
            name="Fallback",
            category=module.TARGET_CLASSES[0],
            latitude=-6.2,
            longitude=106.8,
        )
        with (
            patch.object(
                module,
                "load_agencies_from_db",
                side_effect=RuntimeError("sensitive database detail"),
            ),
            patch.object(module, "load_agencies_from_seed", return_value=[agency]),
            patch.object(module, "ALLOW_AGENCY_SEED_FALLBACK", True),
            patch.dict(module._AGENCY_STATE, {}, clear=True),
        ):
            state = module.refresh_agencies()
            self.assertEqual(state["source"], "seed_fallback")
            self.assertEqual(state["status"], "untrusted_fallback")
            self.assertFalse(state["routing_ready"])
            self.assertNotIn(
                "sensitive database detail", json.dumps(state, default=str)
            )

    def test_reload_endpoint_is_disabled_by_default(self):
        module = importlib.import_module("serve_model")
        with (
            patch.object(module, "ENABLE_AGENCY_RELOAD", False),
            self.assertRaises(HTTPException) as raised,
        ):
            module.reload_agencies(x_reload_token=None)
        self.assertEqual(raised.exception.status_code, 503)

    def test_verified_registry_gap_is_reviewed_without_catchall_rerouting(self):
        module = importlib.import_module("serve_model")
        catchall = module.AgencyCandidate(
            agency_id="other",
            name="Catch-all",
            category="Instansi lain",
            latitude=-6.2,
            longitude=106.8,
        )
        with patch.dict(
            module._AGENCY_STATE,
            {
                "agencies": [catchall],
                "source": "supabase_service_role",
                "status": "verified",
                "routing_ready": True,
                "coverage_gaps": [],
            },
            clear=True,
        ):
            self.assertIsNone(
                module.find_nearest_agency(module.TARGET_CLASSES[0], -6.2, 106.8)
            )
            self.assertEqual(
                module.routing_review_reasons(module.TARGET_CLASSES[0], -6.2, 106.8),
                ["routing_registry_gap"],
            )

    def test_missing_location_is_reviewed_even_with_verified_registry(self):
        module = importlib.import_module("serve_model")
        with patch.dict(
            module._AGENCY_STATE,
            {
                "agencies": [],
                "source": "supabase_service_role",
                "status": "verified",
                "routing_ready": True,
                "coverage_gaps": [],
            },
            clear=True,
        ):
            self.assertEqual(
                module.routing_review_reasons(module.TARGET_CLASSES[0], None, None),
                ["routing_location_missing"],
            )

    def test_catchall_is_never_a_routable_coverage_requirement(self):
        module = importlib.import_module("serve_model")
        agencies = [
            module.AgencyCandidate(
                agency_id=f"agency-{index}",
                name=label,
                category=label,
                latitude=-6.2,
                longitude=106.8,
            )
            for index, label in enumerate(module.ROUTABLE_TARGET_CLASSES)
        ]
        self.assertEqual(module._agency_coverage_gaps(agencies), [])

    def test_catchall_is_unconditionally_reviewed_and_never_assigned(self):
        module = importlib.import_module("serve_model")
        catchall = module.AgencyCandidate(
            agency_id="unsafe-catchall",
            name="Unsafe catch-all",
            category=module.CATCH_ALL_LABEL,
            latitude=-6.2,
            longitude=106.8,
        )
        with patch.dict(
            module._AGENCY_STATE,
            {
                "agencies": [catchall],
                "source": "supabase_service_role",
                "status": "verified",
                "routing_ready": True,
                "coverage_gaps": [],
            },
            clear=True,
        ):
            self.assertIsNone(
                module.find_nearest_agency(module.CATCH_ALL_LABEL, -6.2, 106.8)
            )
            self.assertEqual(
                module.routing_review_reasons(module.CATCH_ALL_LABEL, -6.2, 106.8),
                ["catch_all_class"],
            )
        with self.assertRaisesRegex(RuntimeError, "catch-all"):
            module._validate_agency_records([catchall], "test")


if __name__ == "__main__":
    unittest.main()
