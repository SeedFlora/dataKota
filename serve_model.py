"""FastAPI server untuk multimodal classification CRM Jakarta.

Pipeline: image + text → early fusion → five receipt-bound CatBoost heads →
equal-weight probability mean → predicted dinas + score.

Usage:
    uvicorn serve_model:app --host 0.0.0.0 --port 8000 --workers 1
"""

from __future__ import annotations

import base64
import hmac
import importlib.metadata
import io
import json
import os
import sys
import urllib.request
from contextlib import asynccontextmanager
from dataclasses import dataclass
from math import atan2, cos, isfinite, radians, sin, sqrt
from pathlib import Path

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from crm import TARGET_CLASSES
from crm.deployment import (
    EPISTEMIC_MI_METHOD,
    ONNX_SEED_ENSEMBLE_METHOD,
    PGS_SEED_ENSEMBLE_METHOD,
    classifier_parity_report,
    determine_review_reasons,
    equal_weight_probability_mean,
    normalize_probability_output,
    validate_probability_matrix,
)
from crm.export_contract import (
    CLASSIFIER_PARITY_TOLERANCES,
    ExportContractError,
    sha256_file,
    validate_export_manifest,
)
from crm.image_preprocessing import ImagePreprocessor
from crm.pgs import pgs_predict, validate_pgs_model

EXPORT_DIR = Path(os.getenv("EXPORT_DIR", ROOT / "artifacts" / "export"))
EXPECTED_EXPORT_MANIFEST_SHA256 = os.getenv("EXPORT_MANIFEST_SHA256", "").lower()
# These are optional assertions, not sources of model identity. The signed/pinned
# export manifest is the sole runtime source of the deployed name/version.
EXPECTED_MODEL_NAME = os.getenv("MODEL_NAME") or None
EXPECTED_MODEL_VERSION = os.getenv("MODEL_VERSION") or None
REQUESTED_ORT_PROVIDER = os.getenv("ORT_PROVIDER", "CPUExecutionProvider")
MAX_IMAGE_BYTES = int(os.getenv("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
MAX_IMAGE_PIXELS = int(os.getenv("MAX_IMAGE_PIXELS", str(25_000_000)))
MAX_REPORT_TEXT_CHARS = int(os.getenv("MAX_REPORT_TEXT_CHARS", "5000"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be true/false, got {value!r}")


PARITY_PROBABILITY_TOLERANCE = float(
    CLASSIFIER_PARITY_TOLERANCES["probability_tolerance"]
)
_parity_tolerance_assertion = os.getenv("PARITY_PROBABILITY_TOLERANCE")
if _parity_tolerance_assertion is not None:
    try:
        _asserted_parity_tolerance = float(_parity_tolerance_assertion)
    except ValueError as exc:
        raise RuntimeError("PARITY_PROBABILITY_TOLERANCE must be numeric") from exc
    if _asserted_parity_tolerance != PARITY_PROBABILITY_TOLERANCE:
        raise RuntimeError(
            "PARITY_PROBABILITY_TOLERANCE cannot override the frozen export policy"
        )
PARITY_SAMPLE_COUNT = int(os.getenv("PARITY_SAMPLE_COUNT", "32"))
ALLOW_AGENCY_SEED_FALLBACK = _env_bool("ALLOW_AGENCY_SEED_FALLBACK", True)
ENABLE_AGENCY_RELOAD = _env_bool("ENABLE_AGENCY_RELOAD", False)
ALLOW_SELECTION_ONLY_EXPORT = _env_bool("ALLOW_SELECTION_ONLY_EXPORT", False)

if PARITY_PROBABILITY_TOLERANCE < 0 or PARITY_SAMPLE_COUNT < 1:
    raise RuntimeError("parity tolerance/sample count configuration is invalid")
if MAX_IMAGE_BYTES < 1 or MAX_IMAGE_PIXELS < 1 or MAX_REPORT_TEXT_CHARS < 1:
    raise RuntimeError("request size limits must be positive")
if REQUESTED_ORT_PROVIDER not in {"CPUExecutionProvider", "CUDAExecutionProvider"}:
    raise RuntimeError(
        "ORT_PROVIDER must be CPUExecutionProvider or CUDAExecutionProvider"
    )


@dataclass(frozen=True)
class AgencyCandidate:
    agency_id: str
    name: str
    category: str  # label instansi; cocok dengan TARGET_CLASSES (kunci routing)
    latitude: float
    longitude: float
    active: bool = True
    category_slug: str = ""  # cocok dengan enum public.issue_category di Supabase


AGENCY_SEED_PATH = Path(os.getenv("AGENCY_SEED_PATH", ROOT / "agencies_seed.json"))
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
# Routing is a server-side trusted operation. Never accept the anon key here:
# RLS/readability is not proof that a registry is the authoritative routing view.
SUPABASE_SERVICE_ROLE_KEY = (
    os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or ""
)
# Operator-only credential. It is deliberately not consumed by the Flutter app.
RELOAD_TOKEN = os.getenv("AGENCY_RELOAD_TOKEN", "")
if ENABLE_AGENCY_RELOAD and len(RELOAD_TOKEN) < 32:
    raise RuntimeError(
        "ENABLE_AGENCY_RELOAD=true requires an AGENCY_RELOAD_TOKEN of at least 32 characters"
    )


# Canonical bridge between the database enum and the frozen classifier labels.
# It must not be learned from a mutable routing registry/seed at runtime.
SLUG2LABEL = {
    "dinas_bina_marga": "Dinas Bina Marga",
    "satpol_pp": "Satuan Polisi Pamong Praja",
    "dinas_perhubungan": "Dinas Perhubungan",
    "kelurahan": "Kelurahan",
    "dinas_pertamanan_hutan": "Dinas Pertamanan dan Hutan",
    "dinas_sda": "Dinas Sumber Daya Air",
    "dinas_cipta_karya": "Dinas Cipta Karya, Tata Ruang, dan Pertanahan",
    "badan_bumd": "Badan Pembinaan Badan Usaha Milik Daerah",
    "instansi_lain": "Instansi lain",
}
if tuple(SLUG2LABEL.values()) != tuple(TARGET_CLASSES):
    raise RuntimeError("routing slug map differs from the frozen class order")
LABEL2SLUG = {label: slug for slug, label in SLUG2LABEL.items()}
CATCH_ALL_LABEL = "Instansi lain"
ROUTABLE_TARGET_CLASSES = tuple(
    label for label in TARGET_CLASSES if label != CATCH_ALL_LABEL
)


def _validate_service_role_credential(key: str) -> None:
    """Reject anon/client credentials even if placed in a server env var."""
    if key.startswith("sb_secret_") and len(key) >= 32:
        return
    parts = key.split(".")
    if len(parts) != 3:
        raise RuntimeError("Supabase service-role credential has an unsupported format")
    try:
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Supabase service-role JWT payload is invalid") from exc
    if payload.get("role") != "service_role":
        raise RuntimeError("Supabase credential is not a service_role credential")


def _validate_agency_records(agencies: list[AgencyCandidate], source: str) -> None:
    ids = [agency.agency_id for agency in agencies]
    if any(not isinstance(value, str) or not value.strip() for value in ids):
        raise RuntimeError(f"{source} agency registry contains an empty id")
    if len(set(ids)) != len(ids):
        raise RuntimeError(f"{source} agency registry contains duplicate ids")
    if any(not agency.name.strip() for agency in agencies):
        raise RuntimeError(f"{source} agency registry contains an empty name")
    if any(agency.active and agency.category == CATCH_ALL_LABEL for agency in agencies):
        raise RuntimeError(
            f"{source} agency registry marks the human-review catch-all as routable"
        )
    if any(
        agency.category_slug != LABEL2SLUG.get(agency.category) for agency in agencies
    ):
        raise RuntimeError(f"{source} agency registry label/slug mapping is invalid")


def load_agencies_from_seed(path: Path = AGENCY_SEED_PATH) -> list[AgencyCandidate]:
    """Fallback: muat registri instansi dari berkas seed JSON lokal."""
    try:
        raw = json.loads(path.read_text())
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Agency seed tidak ditemukan di {path}. "
            "Set AGENCY_SEED_PATH atau kembalikan berkas agencies_seed.json."
        ) from e
    records = raw["agencies"] if isinstance(raw, dict) else raw
    agencies: list[AgencyCandidate] = []
    for record in records:
        slug = record.get("category_slug", "")
        expected_label = SLUG2LABEL.get(slug)
        if expected_label is None or record.get("category") != expected_label:
            raise RuntimeError(
                "agency seed category mapping differs from the canonical map"
            )
        latitude = float(record["latitude"])
        longitude = float(record["longitude"])
        if (
            not isfinite(latitude)
            or not isfinite(longitude)
            or not -90.0 <= latitude <= 90.0
            or not -180.0 <= longitude <= 180.0
        ):
            raise RuntimeError("agency seed contains invalid coordinates")
        agencies.append(
            AgencyCandidate(
                agency_id=record["id"],
                name=record["name"],
                category=expected_label,
                latitude=latitude,
                longitude=longitude,
                active=bool(record.get("is_active", True)),
                category_slug=slug,
            )
        )
    if not agencies:
        raise RuntimeError(f"Agency seed di {path} kosong.")
    _validate_agency_records(agencies, "seed")
    return agencies


def load_agencies_from_db() -> list[AgencyCandidate]:
    """Sumber utama (Option C): baca tabel public.agencies dari Supabase via
    PostgREST. Kolom enum ``category`` (slug) dipetakan ke label TARGET_CLASSES
    yang dipakai algoritma routing. Memakai stdlib urllib (tanpa dependensi baru).
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("trusted Supabase service-role configuration is unavailable")
    _validate_service_role_credential(SUPABASE_SERVICE_ROLE_KEY)
    url = (
        f"{SUPABASE_URL}/rest/v1/agencies"
        "?select=id,name,category,latitude,longitude,is_active"
    )
    req = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    agencies = []
    for r in rows:
        if r.get("latitude") is None or r.get("longitude") is None:
            continue
        slug = r.get("category") or ""
        if slug not in SLUG2LABEL:
            raise RuntimeError(
                "Supabase agency registry contains an unknown category slug"
            )
        latitude = float(r["latitude"])
        longitude = float(r["longitude"])
        if (
            not isfinite(latitude)
            or not isfinite(longitude)
            or not -90.0 <= latitude <= 90.0
            or not -180.0 <= longitude <= 180.0
        ):
            raise RuntimeError("Supabase agency registry contains invalid coordinates")
        agencies.append(
            AgencyCandidate(
                agency_id=r["id"],
                name=r["name"],
                category=SLUG2LABEL[slug],
                latitude=latitude,
                longitude=longitude,
                active=bool(r.get("is_active", True)),
                category_slug=slug,
            )
        )
    if not agencies:
        raise RuntimeError("Tabel agencies kosong / tidak terbaca")
    _validate_agency_records(agencies, "Supabase")
    return agencies


# Cache in-memory supaya routing tidak query DB tiap permintaan /predict. Error
# messages are never exposed: PostgREST errors can contain operational details.
_AGENCY_STATE: dict = {
    "agencies": [],
    "source": "none",
    "status": "uninitialized",
    "routing_ready": False,
    "coverage_gaps": list(ROUTABLE_TARGET_CLASSES),
    "last_error_code": None,
}


def _agency_coverage_gaps(agencies: list[AgencyCandidate]) -> list[str]:
    covered = {
        agency.category
        for agency in agencies
        if agency.active
        and isfinite(agency.latitude)
        and isfinite(agency.longitude)
        and agency.category in ROUTABLE_TARGET_CLASSES
    }
    return [label for label in ROUTABLE_TARGET_CLASSES if label not in covered]


def refresh_agencies() -> dict:
    """Refresh routing state and mark every unverified fallback fail-closed."""
    try:
        ags = load_agencies_from_db()
        gaps = _agency_coverage_gaps(ags)
        _AGENCY_STATE.update(
            {
                "agencies": ags,
                "source": "supabase_service_role",
                "status": "verified" if not gaps else "incomplete",
                "routing_ready": not gaps,
                "coverage_gaps": gaps,
                "last_error_code": None,
            }
        )
    except Exception as exc:  # noqa: BLE001 - safe, non-routing fallback state
        error_code = type(exc).__name__
        ags: list[AgencyCandidate] = []
        if ALLOW_AGENCY_SEED_FALLBACK:
            try:
                ags = load_agencies_from_seed()
                source = "seed_fallback"
                status = "untrusted_fallback"
            except Exception as seed_exc:  # noqa: BLE001
                source = "none"
                status = "unavailable"
                error_code = f"{error_code}+{type(seed_exc).__name__}"
        else:
            source = "none"
            status = "unavailable"
        _AGENCY_STATE.update(
            {
                "agencies": ags,
                "source": source,
                "status": status,
                # Seed data is useful for development/display only. It is never
                # trusted to authorize automatic dispatch.
                "routing_ready": False,
                "coverage_gaps": _agency_coverage_gaps(ags),
                "last_error_code": error_code,
            }
        )
    return _AGENCY_STATE


def get_agencies() -> list[AgencyCandidate]:
    return _AGENCY_STATE["agencies"]


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    radius = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return radius * c


def find_nearest_agency(
    predicted_class: str, latitude: float | None, longitude: float | None
):
    if predicted_class == CATCH_ALL_LABEL:
        return None
    if latitude is None or longitude is None:
        return None
    if not _AGENCY_STATE["routing_ready"]:
        return None
    agencies = get_agencies()
    candidates = [
        agency
        for agency in agencies
        if agency.active and agency.category == predicted_class
    ]
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda agency: haversine_distance_meters(
            latitude,
            longitude,
            agency.latitude,
            agency.longitude,
        ),
    )
    distance = haversine_distance_meters(
        latitude,
        longitude,
        nearest.latitude,
        nearest.longitude,
    )
    return nearest, distance


def routing_review_reasons(
    predicted_class: str,
    latitude: float | None,
    longitude: float | None,
) -> list[str]:
    """Return fail-closed routing-registry reasons for human review."""
    if predicted_class == CATCH_ALL_LABEL:
        return ["catch_all_class"]
    if not _AGENCY_STATE["routing_ready"]:
        if _AGENCY_STATE["status"] == "incomplete":
            return ["routing_registry_incomplete"]
        return ["agency_registry_untrusted"]
    if latitude is None or longitude is None:
        return ["routing_location_missing"]
    has_exact_candidate = any(
        agency.active
        and agency.category == predicted_class
        and isfinite(agency.latitude)
        and isfinite(agency.longitude)
        for agency in get_agencies()
    )
    return [] if has_exact_candidate else ["routing_registry_gap"]


def mean_pool(hidden: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[..., None].astype(np.float32)
    return (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)


def l2_normalize(x: np.ndarray) -> np.ndarray:
    return x / np.linalg.norm(x, axis=1, keepdims=True).clip(min=1e-9)


@dataclass(frozen=True)
class PipelinePrediction:
    label: str
    label_id: int
    confidence: float
    probabilities: np.ndarray
    inference_method: str
    uncertainty_method: str | None = None
    epistemic_uncertainty: float | None = None
    predictive_entropy: float | None = None
    expected_data_entropy: float | None = None


class CRMPipeline:
    def __init__(
        self,
        export_dir: Path,
        provider: str,
        *,
        expected_manifest_sha256: str,
        expected_model_name: str | None = None,
        expected_model_version: str | None = None,
    ):
        try:
            self.export_manifest = validate_export_manifest(
                export_dir,
                expected_manifest_sha256=expected_manifest_sha256,
                expected_classes=TARGET_CLASSES,
                expected_model_version=expected_model_version,
            )
        except ExportContractError as exc:
            raise RuntimeError(f"invalid deployable export: {exc}") from exc
        model_contract = self.export_manifest["model"]
        if (
            self.export_manifest["protocol"]["export_policy"] != "locked_test_complete"
            and not ALLOW_SELECTION_ONLY_EXPORT
        ):
            raise RuntimeError(
                "selection-only export is non-release and disabled; set "
                "ALLOW_SELECTION_ONLY_EXPORT=true only for an explicitly labelled "
                "development deployment"
            )
        if (
            expected_model_name is not None
            and model_contract["name"] != expected_model_name
        ):
            raise RuntimeError(
                f"model name mismatch: expected {expected_model_name!r}, "
                f"got {model_contract['name']!r}"
            )
        self.model_name = model_contract["name"]
        self.model_version = model_contract["version"]
        self.seeds = tuple(int(seed) for seed in model_contract["seeds"])
        self.inference_method = model_contract["default_inference_method"]
        self.uses_pgs = bool(model_contract["training_posterior_sampling"])
        self.class_map_sha256 = self.export_manifest["class_map"]["semantic_sha256"]
        self.export_manifest_sha256 = sha256_file(export_dir / "export_manifest.json")
        self.export_manifest_digest = self.export_manifest["manifest_digest"]
        self.protocol = dict(self.export_manifest["protocol"])
        self.calibration_protocol = dict(self.export_manifest["calibration"])
        self.review_policy = dict(self.export_manifest["review_policy"])
        self.confidence_threshold = float(self.review_policy["minimum_confidence"])
        manifested_epistemic_threshold = self.review_policy[
            "maximum_epistemic_mutual_information"
        ]
        self.epistemic_uncertainty_threshold = (
            float(manifested_epistemic_threshold)
            if manifested_epistemic_threshold is not None
            else None
        )
        self.encoder_contracts = dict(self.export_manifest["encoders"])
        self.feature_fusion = dict(self.export_manifest["feature_fusion"])
        self.l2_per_modality = bool(self.feature_fusion["l2_per_modality"])
        artifact_by_path = {
            item["path"]: item for item in self.export_manifest["artifacts"]
        }

        available_providers = ort.get_available_providers()
        if provider not in available_providers:
            raise RuntimeError(
                f"requested ONNX Runtime provider {provider!r} is unavailable; "
                f"available providers: {available_providers}. Refusing silent fallback."
            )
        providers = [provider]
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if provider == "CUDAExecutionProvider":
            # Merely placing CUDA first still permits per-node CPU fallback. A
            # release that explicitly requests CUDA must either execute there
            # or fail during session construction.
            so.add_session_config_entry("session.disable_cpu_ep_fallback", "1")

        runtime = self.export_manifest["runtime"]
        txt_dir = (export_dir / runtime["text_tokenizer_dir"]).resolve()

        self.img_sess = ort.InferenceSession(
            str(export_dir / runtime["image_model"]), so, providers=providers
        )
        self.txt_sess = ort.InferenceSession(
            str(export_dir / runtime["text_model"]), so, providers=providers
        )
        self.classifier_sessions: list[tuple[int, ort.InferenceSession, str]] = []
        self.classifier_member_hashes: list[dict[str, int | str]] = []
        for member in runtime["classifier_members"]:
            seed = int(member["seed"])
            session = ort.InferenceSession(
                str(export_dir / member["onnx"]),
                providers=["CPUExecutionProvider"],
            )
            if len(session.get_inputs()) != 1:
                raise RuntimeError(
                    f"classifier seed {seed} must expose one fused-feature input"
                )
            self.classifier_sessions.append(
                (seed, session, session.get_inputs()[0].name)
            )
            self.classifier_member_hashes.append(
                {
                    "seed": seed,
                    "onnx_sha256": artifact_by_path[member["onnx"]]["sha256"],
                    "native_sha256": artifact_by_path[member["native"]]["sha256"],
                }
            )
        image_inputs = {item.name for item in self.img_sess.get_inputs()}
        text_inputs = {item.name for item in self.txt_sess.get_inputs()}
        if image_inputs != {"pixel_values"}:
            raise RuntimeError(
                f"image encoder inputs must be exactly {{'pixel_values'}}, got {image_inputs}"
            )
        if text_inputs != {"input_ids", "attention_mask"}:
            raise RuntimeError(
                "text encoder inputs must be exactly {'input_ids', 'attention_mask'}, "
                f"got {text_inputs}"
            )
        if self.img_sess.get_providers()[0] != provider:
            raise RuntimeError(
                f"image encoder activated {self.img_sess.get_providers()} instead of "
                f"requested provider {provider}; refusing silent fallback"
            )
        if self.txt_sess.get_providers()[0] != provider:
            raise RuntimeError(
                f"text encoder activated {self.txt_sess.get_providers()} instead of "
                f"requested provider {provider}; refusing silent fallback"
            )
        self.requested_provider = provider

        image_output_shape = self.img_sess.get_outputs()[0].shape
        text_output_shape = self.txt_sess.get_outputs()[0].shape
        if len(image_output_shape) != 2 or len(text_output_shape) != 3:
            raise RuntimeError(
                "image encoder must return (N,D) and text encoder must return "
                f"(N,L,D); got {image_output_shape} and {text_output_shape}"
            )
        image_dimension = image_output_shape[-1] if image_output_shape else None
        text_dimension = text_output_shape[-1] if text_output_shape else None
        if not isinstance(image_dimension, int) or not isinstance(text_dimension, int):
            raise RuntimeError(  # noqa: TRY004 - invalid exported runtime contract
                "encoder output dimensions must be static in the receipt-bound ONNX files"
            )
        fused_dimension = image_dimension + text_dimension
        if fused_dimension != model_contract["classifier_feature_count"]:
            raise RuntimeError(
                f"encoder outputs fuse to {fused_dimension} features, but the manifest "
                f"classifier contract requires {model_contract['classifier_feature_count']}"
            )
        for seed, session, _ in self.classifier_sessions:
            if self._classifier_feature_count(session) != fused_dimension:
                raise RuntimeError(
                    f"classifier seed {seed} input dimension differs from the encoder "
                    "output contract"
                )

        self.img_processor = ImagePreprocessor(
            export_dir / runtime["image_preprocessor"]
        )
        from transformers import AutoTokenizer

        self.tokenizer = AutoTokenizer.from_pretrained(
            str(txt_dir), local_files_only=True
        )
        self.text_prefix = runtime["text_prefix"]
        self.text_pool = runtime["text_pooling"]
        self.text_max_length = int(runtime["text_max_length"])
        self.native_models: list[tuple[int, object]] = []
        self.pgs_models: list[tuple[int, object]] = []
        manifested_virtual_ensembles = self.protocol.get("virtual_ensembles_per_seed")
        self.pgs_virtual_ensembles = (
            int(manifested_virtual_ensembles) if self.uses_pgs else None
        )
        self.classifier_parity: dict[str, object] | None = None
        self.pgs_smoke_test = None
        self.pgs_tree_counts: dict[int, int] = {}

        for member in runtime["classifier_members"]:
            seed = int(member["seed"])
            self.native_models.append(
                (seed, self._load_native_model(export_dir / member["native"], seed))
            )
        self.classifier_parity = self._verify_native_onnx_parity()
        if self.uses_pgs:
            self.pgs_models = list(self.native_models)
            self.pgs_smoke_test = self._verify_virtual_ensemble_smoke()
        elif self.epistemic_uncertainty_threshold is not None:
            raise RuntimeError(
                "the export review policy cannot attach an epistemic threshold to "
                "an ONNX point-probability seed ensemble"
            )

    def _load_native_model(self, model_path: Path, seed: int):
        path = model_path.resolve()
        if not path.is_file():
            raise RuntimeError(
                f"manifested native classifier for seed {seed} is missing: {path}"
            )
        from catboost import CatBoostClassifier

        model = CatBoostClassifier()
        model.load_model(str(path))
        classes = np.asarray(model.classes_)
        expected_classes = np.arange(len(TARGET_CLASSES))
        try:
            integer_classes = classes.astype(int)
        except (TypeError, ValueError):
            integer_classes = np.array([], dtype=int)
        if classes.shape != expected_classes.shape or not np.array_equal(
            integer_classes,
            expected_classes,
        ):
            raise RuntimeError(
                f"{path} class ids {classes.tolist()} do not match the "
                f"deployment contract {expected_classes.tolist()}"
            )
        if self.uses_pgs:
            try:
                assert self.pgs_virtual_ensembles is not None
                self.pgs_tree_counts[seed] = validate_pgs_model(
                    model, self.pgs_virtual_ensembles
                )
            except ValueError as exc:
                raise RuntimeError(
                    f"invalid PGS checkpoint for seed {seed} at {path}: {exc}"
                ) from exc
        return model

    def _verify_virtual_ensemble_smoke(self) -> dict[str, object]:
        """Exercise every receipt-bound VirtEnsembles head during startup."""
        first_session = self.classifier_sessions[0][1]
        features = np.zeros(
            (1, self._classifier_feature_count(first_session)), dtype=np.float32
        )
        assert self.pgs_virtual_ensembles is not None
        members: list[dict[str, int | float | bool]] = []
        probability_rows: list[np.ndarray] = []
        for seed, model in self.native_models:
            result = pgs_predict(
                model,
                features,
                n_virtual_ensembles=self.pgs_virtual_ensembles,
            )
            probabilities = validate_probability_matrix(
                result.probabilities, len(TARGET_CLASSES)
            )
            values = np.concatenate(
                [
                    probabilities.reshape(-1),
                    result.epistemic_mutual_information.reshape(-1),
                    result.predictive_entropy.reshape(-1),
                    result.expected_data_entropy.reshape(-1),
                ]
            )
            if not np.isfinite(values).all():
                raise RuntimeError(
                    f"PGS startup smoke test returned non-finite values for seed {seed}"
                )
            probability_rows.append(probabilities)
            members.append(
                {
                    "seed": seed,
                    "passed": True,
                    "retained_trees": self.pgs_tree_counts[seed],
                    "probability_sum": float(probabilities[0].sum()),
                }
            )
        ensemble = equal_weight_probability_mean(
            probability_rows,
            len(TARGET_CLASSES),
            expected_members=len(self.seeds),
        )
        return {
            "passed": True,
            "samples": 1,
            "virtual_ensembles": self.pgs_virtual_ensembles,
            "seed_heads": len(self.pgs_models),
            "ensemble_probability_sum": float(ensemble[0].sum()),
            "members": members,
        }

    @staticmethod
    def _classifier_feature_count(session: ort.InferenceSession) -> int:
        shape = session.get_inputs()[0].shape
        if len(shape) != 2 or not isinstance(shape[1], int):
            raise RuntimeError(
                f"classifier must expose a static feature dimension, got {shape}"
            )
        return shape[1]

    def _onnx_member_probabilities(self, fused: np.ndarray) -> list[np.ndarray]:
        probabilities: list[np.ndarray] = []
        for _, session, input_name in self.classifier_sessions:
            outputs = session.run(None, {input_name: fused})
            probabilities.append(
                normalize_probability_output(outputs[-1], range(len(TARGET_CLASSES)))
            )
        return probabilities

    def _onnx_probabilities(self, fused: np.ndarray) -> np.ndarray:
        member_probabilities = self._onnx_member_probabilities(fused)
        return equal_weight_probability_mean(
            member_probabilities,
            len(TARGET_CLASSES),
            expected_members=len(self.seeds),
        )

    def _verify_native_onnx_parity(self) -> dict[str, object]:
        """Fail startup unless every native head is the source of its ONNX head."""
        feature_count = self._classifier_feature_count(self.classifier_sessions[0][1])
        rng = np.random.default_rng(20260825)
        features = rng.normal(
            loc=0.0,
            scale=0.05,
            size=(PARITY_SAMPLE_COUNT, feature_count),
        ).astype(np.float32)
        onnx_members = {
            seed: probabilities
            for (seed, _, _), probabilities in zip(
                self.classifier_sessions,
                self._onnx_member_probabilities(features),
                strict=True,
            )
        }
        native_members: list[np.ndarray] = []
        member_reports: list[dict[str, object]] = []
        for seed, model in self.native_models:
            native = validate_probability_matrix(
                model.predict_proba(features), len(TARGET_CLASSES)
            )
            native_members.append(native)
            report = classifier_parity_report(
                native,
                onnx_members[seed],
                probability_tolerance=PARITY_PROBABILITY_TOLERANCE,
            )
            member_report: dict[str, object] = {"seed": seed, **report.to_dict()}
            member_reports.append(member_report)
            if not report.passed:
                raise RuntimeError(
                    "Native CatBoost / ONNX parity failed for seed "
                    f"{seed}: {report.to_dict()}"
                )
        ensemble_report = classifier_parity_report(
            equal_weight_probability_mean(
                native_members,
                len(TARGET_CLASSES),
                expected_members=len(self.seeds),
            ),
            self._onnx_probabilities(features),
            probability_tolerance=PARITY_PROBABILITY_TOLERANCE,
        )
        if not ensemble_report.passed:
            raise RuntimeError(
                "Native/ONNX seed-ensemble parity check failed: "
                f"{ensemble_report.to_dict()}"
            )
        return {
            "passed": True,
            "members": member_reports,
            "ensemble": ensemble_report.to_dict(),
        }

    def embed_image(self, img: Image.Image) -> np.ndarray:
        px = self.img_processor(img)
        emb = self.img_sess.run(None, {"pixel_values": px})[0]
        return l2_normalize(emb) if self.l2_per_modality else emb

    def embed_text(self, text: str) -> np.ndarray:
        enc = self.tokenizer(
            [self.text_prefix + text],
            padding="longest",
            truncation=True,
            max_length=self.text_max_length,
            return_tensors="np",
        )
        ids = np.asarray(enc["input_ids"], dtype=np.int64)
        mask = np.asarray(enc["attention_mask"], dtype=np.int64)
        hidden = self.txt_sess.run(None, {"input_ids": ids, "attention_mask": mask})[0]
        emb = hidden[:, 0] if self.text_pool == "cls" else mean_pool(hidden, mask)
        return l2_normalize(emb) if self.l2_per_modality else emb

    def predict(self, img: Image.Image, text: str) -> PipelinePrediction:
        fused = np.concatenate(
            [self.embed_image(img), self.embed_text(text)],
            axis=1,
        ).astype(np.float32)

        if not self.uses_pgs:
            probs = self._onnx_probabilities(fused)
            idx = int(np.argmax(probs[0]))
            return PipelinePrediction(
                label=TARGET_CLASSES[idx],
                label_id=idx,
                confidence=float(probs[0, idx]),
                probabilities=probs[0],
                inference_method=ONNX_SEED_ENSEMBLE_METHOD,
            )

        assert self.pgs_virtual_ensembles is not None
        posterior_results = [
            pgs_predict(
                model,
                fused,
                n_virtual_ensembles=self.pgs_virtual_ensembles,
            )
            for _, model in self.pgs_models
        ]
        probs = equal_weight_probability_mean(
            [result.probabilities for result in posterior_results],
            len(TARGET_CLASSES),
            expected_members=len(self.seeds),
        )
        predictive_entropy = -np.sum(probs * np.log(np.clip(probs, 1e-12, 1.0)), axis=1)
        expected_data_entropy = np.mean(
            np.stack(
                [result.expected_data_entropy for result in posterior_results],
                axis=0,
            ),
            axis=0,
        )
        epistemic_uncertainty = np.maximum(
            predictive_entropy - expected_data_entropy, 0.0
        )
        idx = int(np.argmax(probs[0]))
        return PipelinePrediction(
            label=TARGET_CLASSES[idx],
            label_id=idx,
            confidence=float(probs[0, idx]),
            probabilities=probs[0],
            inference_method=PGS_SEED_ENSEMBLE_METHOD,
            uncertainty_method=EPISTEMIC_MI_METHOD,
            epistemic_uncertainty=float(epistemic_uncertainty[0]),
            predictive_entropy=float(predictive_entropy[0]),
            expected_data_entropy=float(expected_data_entropy[0]),
        )


pipe: CRMPipeline | None = None


def build_pipeline() -> CRMPipeline:
    """Construct heavyweight sessions during application startup, not import."""
    return CRMPipeline(
        EXPORT_DIR,
        provider=REQUESTED_ORT_PROVIDER,
        expected_manifest_sha256=EXPECTED_EXPORT_MANIFEST_SHA256,
        expected_model_name=EXPECTED_MODEL_NAME,
        expected_model_version=EXPECTED_MODEL_VERSION,
    )


def require_pipeline() -> CRMPipeline:
    if pipe is None:
        raise HTTPException(status_code=503, detail="Model pipeline is not ready")
    return pipe


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Load local artifacts and agency state once per worker at startup."""
    global pipe
    refresh_agencies()
    pipe = build_pipeline()
    try:
        yield
    finally:
        pipe = None


class AssignmentResponse(BaseModel):
    agency_id: str
    agency_name: str
    agency_category: str
    agency_category_slug: str
    distance_meters: float
    routing_method: str


class PredictResponse(BaseModel):
    predicted_dinas: str
    predicted_dinas_id: int
    predicted_category_slug: str
    confidence: float
    all_probabilities: dict[str, float]
    model_name: str
    model_version: str
    confidence_threshold: float
    review_required: bool
    review_reasons: list[str]
    inference_method: str
    uncertainty_available: bool
    uncertainty_method: str | None = None
    epistemic_uncertainty: float | None = None
    predictive_entropy: float | None = None
    expected_data_entropy: float | None = None
    epistemic_uncertainty_threshold: float | None = None
    export_manifest_sha256: str
    class_map_sha256: str
    agency_registry_status: str
    assignment: AssignmentResponse | None = None


class HealthResponse(BaseModel):
    status: str
    model_name: str
    model_version: str
    image_encoder: str
    text_encoder: str
    image_encoder_revision: str
    text_encoder_revision: str
    classes: list[str]
    gpu_available: bool
    requested_onnx_provider: str
    active_image_providers: list[str]
    active_text_providers: list[str]
    active_classifier_providers: list[str]
    classifier_seeds: list[int]
    classifier_head_count: int
    onnxruntime_version: str
    software_versions: dict[str, str]
    agencies_source: str
    agencies_status: str
    agencies_routing_ready: bool
    agencies_coverage_gaps: list[str]
    agencies_count: int
    agency_reload_mode: str
    inference_method: str
    uncertainty_available: bool
    uncertainty_method: str | None = None
    virtual_ensembles: int | None = None
    calibration_family: str
    calibration_claim: str
    review_threshold_source: str
    review_target_coverage: float
    confidence_threshold: float
    epistemic_uncertainty_threshold: float | None = None
    native_onnx_classifier_parity: dict[str, object] | None = None
    pgs_virtual_ensemble_smoke: dict[str, object] | None = None
    export_manifest_sha256: str
    export_manifest_digest: str
    class_map_sha256: str
    classifier_member_hashes: list[dict[str, int | str]]
    image_encoder_tree_sha256: str
    text_encoder_tree_sha256: str
    protocol_digest: str
    export_policy: str
    input_manifest_digest: str
    source_class_map_sha256: str
    selection_receipt_digest: str
    locked_test_receipt_digest: str | None = None


class ReloadResponse(BaseModel):
    source: str
    count: int


app = FastAPI(
    title="CRM Jakarta Multimodal Classifier",
    description=(
        "Early-fusion image/text classifier. Every release serves the equal-weight "
        "probability mean across all preregistered seed heads. A selected point "
        "candidate uses ONNX heads; a selected posterior-sampling candidate uses "
        "the receipt-bound native virtual ensembles for every seed."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=bool(ALLOWED_ORIGINS),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Reload-Token"],
)


@app.get("/health", response_model=HealthResponse)
def health():
    active_pipe = require_pipeline()
    uncertainty_available = active_pipe.uses_pgs
    return HealthResponse(
        status=("ok" if _AGENCY_STATE["routing_ready"] else "degraded_review_only"),
        model_name=active_pipe.model_name,
        model_version=active_pipe.model_version,
        image_encoder=active_pipe.encoder_contracts["image"]["name"],
        text_encoder=active_pipe.encoder_contracts["text"]["name"],
        image_encoder_revision=active_pipe.encoder_contracts["image"]["revision"],
        text_encoder_revision=active_pipe.encoder_contracts["text"]["revision"],
        classes=list(TARGET_CLASSES),
        gpu_available="CUDAExecutionProvider" in active_pipe.img_sess.get_providers(),
        requested_onnx_provider=active_pipe.requested_provider,
        active_image_providers=active_pipe.img_sess.get_providers(),
        active_text_providers=active_pipe.txt_sess.get_providers(),
        active_classifier_providers=sorted(
            {
                provider
                for _, session, _ in active_pipe.classifier_sessions
                for provider in session.get_providers()
            }
        ),
        classifier_seeds=list(active_pipe.seeds),
        classifier_head_count=len(active_pipe.classifier_sessions),
        onnxruntime_version=ort.__version__,
        software_versions={
            package: importlib.metadata.version(package)
            for package in (
                "numpy",
                "onnxruntime",
                "transformers",
                "catboost",
                "Pillow",
            )
        },
        agencies_source=_AGENCY_STATE["source"],
        agencies_status=_AGENCY_STATE["status"],
        agencies_routing_ready=_AGENCY_STATE["routing_ready"],
        agencies_coverage_gaps=_AGENCY_STATE["coverage_gaps"],
        agencies_count=len(get_agencies()),
        agency_reload_mode=("operator_token" if ENABLE_AGENCY_RELOAD else "disabled"),
        inference_method=active_pipe.inference_method,
        uncertainty_available=uncertainty_available,
        uncertainty_method=(EPISTEMIC_MI_METHOD if uncertainty_available else None),
        virtual_ensembles=(
            active_pipe.pgs_virtual_ensembles if uncertainty_available else None
        ),
        calibration_family=active_pipe.calibration_protocol["family"],
        calibration_claim=active_pipe.calibration_protocol["claim"],
        review_threshold_source=active_pipe.review_policy["threshold_source"],
        review_target_coverage=float(active_pipe.review_policy["target_coverage"]),
        confidence_threshold=active_pipe.confidence_threshold,
        epistemic_uncertainty_threshold=(active_pipe.epistemic_uncertainty_threshold),
        native_onnx_classifier_parity=active_pipe.classifier_parity,
        pgs_virtual_ensemble_smoke=active_pipe.pgs_smoke_test,
        export_manifest_sha256=active_pipe.export_manifest_sha256,
        export_manifest_digest=active_pipe.export_manifest_digest,
        class_map_sha256=active_pipe.class_map_sha256,
        classifier_member_hashes=active_pipe.classifier_member_hashes,
        image_encoder_tree_sha256=active_pipe.encoder_contracts["image"][
            "artifact_tree_sha256"
        ],
        text_encoder_tree_sha256=active_pipe.encoder_contracts["text"][
            "artifact_tree_sha256"
        ],
        protocol_digest=active_pipe.protocol["protocol_digest"],
        export_policy=active_pipe.protocol["export_policy"],
        input_manifest_digest=active_pipe.protocol["input_manifest_digest"],
        source_class_map_sha256=active_pipe.protocol["source_class_map_sha256"],
        selection_receipt_digest=active_pipe.protocol["selection_receipt_digest"],
        locked_test_receipt_digest=active_pipe.protocol.get(
            "locked_test_receipt_digest"
        ),
    )


@app.post("/reload-agencies", response_model=ReloadResponse)
def reload_agencies(x_reload_token: str | None = Header(default=None)):
    """Refresh agencies only when endpoint and server-side token are enabled."""
    if not ENABLE_AGENCY_RELOAD:
        raise HTTPException(
            status_code=503, detail="Agency reload endpoint is disabled"
        )
    if x_reload_token is None or not hmac.compare_digest(x_reload_token, RELOAD_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid reload token")
    state = refresh_agencies()
    if not state["routing_ready"]:
        raise HTTPException(
            status_code=503,
            detail=f"Agency registry reload failed closed: {state['status']}",
        )
    return ReloadResponse(source=state["source"], count=len(state["agencies"]))


@app.post("/predict", response_model=PredictResponse)
async def predict(
    image: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
    laporan: str = Form(...),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
):
    raw_image = await image.read(MAX_IMAGE_BYTES + 1)
    if len(raw_image) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413, detail="Image exceeds configured byte limit"
        )
    try:
        img = Image.open(io.BytesIO(raw_image))
        if img.width * img.height > MAX_IMAGE_PIXELS:
            raise HTTPException(
                status_code=413, detail="Image exceeds configured pixel limit"
            )
        if img.format not in {"JPEG", "PNG", "WEBP"}:
            raise HTTPException(status_code=415, detail="Unsupported image format")
        img.load()
    except HTTPException:
        raise
    except Image.DecompressionBombError as e:
        raise HTTPException(
            status_code=413, detail="Image decompression limit exceeded"
        ) from e
    except (OSError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    if not laporan.strip():
        raise HTTPException(status_code=400, detail="Laporan text cannot be empty")
    if len(laporan) > MAX_REPORT_TEXT_CHARS:
        raise HTTPException(
            status_code=413, detail="Laporan text exceeds configured limit"
        )
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=422, detail="Latitude and longitude must be supplied together"
        )
    if (
        latitude is not None
        and longitude is not None
        and (
            not isfinite(latitude)
            or not isfinite(longitude)
            or not -90.0 <= latitude <= 90.0
            or not -180.0 <= longitude <= 180.0
        )
    ):
        raise HTTPException(status_code=422, detail="Invalid latitude/longitude")

    active_pipe = require_pipeline()
    prediction = active_pipe.predict(img, laporan)
    review_reasons = determine_review_reasons(
        predicted_label=prediction.label,
        confidence=prediction.confidence,
        confidence_threshold=active_pipe.confidence_threshold,
        catch_all_label=CATCH_ALL_LABEL,
        epistemic_uncertainty=prediction.epistemic_uncertainty,
        epistemic_uncertainty_threshold=(active_pipe.epistemic_uncertainty_threshold),
    )
    review_reasons.extend(routing_review_reasons(prediction.label, latitude, longitude))
    review_reasons = list(dict.fromkeys(review_reasons))
    nearest = find_nearest_agency(prediction.label, latitude, longitude)
    assignment = None
    # A flagged prediction is evidence for a review queue, not authorization to
    # dispatch. The proposed class remains visible, but no active agency
    # assignment leaves the API until the review requirement is resolved.
    if nearest is not None and not review_reasons:
        agency, distance = nearest
        assignment = AssignmentResponse(
            agency_id=agency.agency_id,
            agency_name=agency.name,
            agency_category=agency.category,
            agency_category_slug=agency.category_slug,
            distance_meters=round(float(distance), 2),
            routing_method="nearest_by_category_and_location",
        )
    return PredictResponse(
        predicted_dinas=prediction.label,
        predicted_dinas_id=prediction.label_id,
        predicted_category_slug=LABEL2SLUG[prediction.label],
        confidence=prediction.confidence,
        all_probabilities={
            TARGET_CLASSES[i]: float(prediction.probabilities[i])
            for i in range(len(TARGET_CLASSES))
        },
        model_name=active_pipe.model_name,
        model_version=active_pipe.model_version,
        confidence_threshold=active_pipe.confidence_threshold,
        review_required=bool(review_reasons),
        review_reasons=review_reasons,
        inference_method=prediction.inference_method,
        uncertainty_available=prediction.uncertainty_method is not None,
        uncertainty_method=prediction.uncertainty_method,
        epistemic_uncertainty=prediction.epistemic_uncertainty,
        predictive_entropy=prediction.predictive_entropy,
        expected_data_entropy=prediction.expected_data_entropy,
        epistemic_uncertainty_threshold=(active_pipe.epistemic_uncertainty_threshold),
        export_manifest_sha256=active_pipe.export_manifest_sha256,
        class_map_sha256=active_pipe.class_map_sha256,
        agency_registry_status=_AGENCY_STATE["status"],
        assignment=assignment,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
