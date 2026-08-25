"""Configuration models for the locked Q2 experiment protocol.

The protocol intentionally keeps all model-selection knobs in one global
configuration.  Candidate-specific CatBoost budgets are rejected so that the
standard and posterior-sampling variants differ only in the treatment under
study.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a protocol configuration is scientifically unsafe."""


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SUPPORTED_MODELS = {
    "catboost",
    "late_fusion_catboost",
    "logistic_regression",
    "sgd_logistic",
    "tfidf_logistic",
    "dummy_prior",
    "dummy_stratified",
}
_CATBOOST_LOCKED_KEYS = {
    "iterations",
    "learning_rate",
    "depth",
    "l2_leaf_reg",
    "early_stopping_rounds",
    "checkpoint_tree_policy",
    "eval_metric",
    "loss_function",
    "random_seed",
    "random_state",
    "posterior_sampling",
}


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a mapping")
    return value


def _resolve(base: Path, value: str, name: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


@dataclass(frozen=True)
class CandidateConfig:
    name: str
    model: str
    image_encoder: str | None = None
    text_encoder: str | None = None
    posterior_sampling: bool = False
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CandidateConfig:
        candidate = cls(
            name=str(raw.get("name", "")),
            model=str(raw.get("model", "")),
            image_encoder=raw.get("image_encoder"),
            text_encoder=raw.get("text_encoder"),
            posterior_sampling=bool(raw.get("posterior_sampling", False)),
            params=dict(_require_mapping(raw.get("params", {}), "candidate.params")),
        )
        candidate.validate()
        return candidate

    def validate(self) -> None:
        if not _SAFE_NAME.fullmatch(self.name):
            raise ConfigError(
                f"candidate name {self.name!r} must match {_SAFE_NAME.pattern}"
            )
        if self.model not in _SUPPORTED_MODELS:
            raise ConfigError(
                f"candidate {self.name!r} uses unsupported model {self.model!r}"
            )
        if (
            self.image_encoder is None
            and self.text_encoder is None
            and self.model != "tfidf_logistic"
        ):
            raise ConfigError(f"candidate {self.name!r} has no input modality")
        if self.model == "tfidf_logistic" and (
            self.image_encoder is not None or self.text_encoder is not None
        ):
            raise ConfigError(
                f"candidate {self.name!r}: tfidf_logistic uses raw text, not embeddings"
            )
        if self.model == "late_fusion_catboost" and (
            self.image_encoder is None or self.text_encoder is None
        ):
            raise ConfigError(
                f"candidate {self.name!r}: late fusion requires image and text encoders"
            )
        if self.posterior_sampling and self.model != "catboost":
            raise ConfigError(
                f"candidate {self.name!r}: posterior_sampling is CatBoost-only"
            )
        forbidden = sorted(_CATBOOST_LOCKED_KEYS.intersection(self.params))
        if self.model in {"catboost", "late_fusion_catboost"} and forbidden:
            raise ConfigError(
                f"candidate {self.name!r} overrides locked CatBoost budget keys: "
                + ", ".join(forbidden)
            )
        for encoder_name, value in (
            ("image_encoder", self.image_encoder),
            ("text_encoder", self.text_encoder),
        ):
            if value is not None and not _SAFE_NAME.fullmatch(str(value)):
                raise ConfigError(
                    f"candidate {self.name!r} has unsafe {encoder_name}={value!r}"
                )


@dataclass(frozen=True)
class CatBoostBudget:
    iterations: int = 1500
    learning_rate: float = 0.05
    depth: int = 6
    l2_leaf_reg: float = 3.0
    early_stopping_rounds: int = 50
    checkpoint_tree_policy: str = "full_early_stopped_trajectory_for_both_point_and_pgs"
    eval_metric: str = "TotalF1:average=Macro"
    thread_count: int = -1

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> CatBoostBudget:
        budget = cls(
            iterations=int(raw.get("iterations", 1500)),
            learning_rate=float(raw.get("learning_rate", 0.05)),
            depth=int(raw.get("depth", 6)),
            l2_leaf_reg=float(raw.get("l2_leaf_reg", 3.0)),
            early_stopping_rounds=int(raw.get("early_stopping_rounds", 50)),
            checkpoint_tree_policy=str(raw.get("checkpoint_tree_policy", "")),
            eval_metric=str(raw.get("eval_metric", "TotalF1:average=Macro")),
            thread_count=int(raw.get("thread_count", -1)),
        )
        if budget.iterations < 2:
            raise ConfigError("catboost.iterations must be >= 2")
        if not 1 <= budget.depth <= 16:
            raise ConfigError("catboost.depth must be between 1 and 16")
        if budget.learning_rate <= 0:
            raise ConfigError("catboost.learning_rate must be > 0")
        if budget.early_stopping_rounds < 1:
            raise ConfigError("catboost.early_stopping_rounds must be >= 1")
        if budget.checkpoint_tree_policy != (
            "full_early_stopped_trajectory_for_both_point_and_pgs"
        ):
            raise ConfigError(
                "catboost.checkpoint_tree_policy must retain the complete "
                "early-stopped trajectory for both point and PGS candidates"
            )
        if "TotalF1" not in budget.eval_metric or "Macro" not in budget.eval_metric:
            raise ConfigError(
                "catboost.eval_metric must be macro-F1 "
                "(for example TotalF1:average=Macro)"
            )
        return budget


@dataclass(frozen=True)
class TestPlan:
    include_selected: bool = True
    fixed_candidates: tuple[str, ...] = ()
    paired_reference: str | None = None
    paired_comparisons: tuple[tuple[str, str, str], ...] = ()
    matched_checkpoint_inference_ablations: tuple[tuple[str, str], ...] = ()
    bootstrap_iterations: int = 10000
    bootstrap_seed: int = 271828
    bootstrap_stratification: str = "utc_month_x_cluster_majority_label_v1"
    training_seed_sensitivity_iterations: int = 10000
    training_seed_sensitivity_seed: int = 271828
    confidence_level: float = 0.95
    cluster_permutation_iterations: int = 20000
    cluster_permutation_seed: int = 314159

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TestPlan:
        required_bootstrap_fields = {
            "bootstrap_iterations",
            "bootstrap_seed",
            "bootstrap_stratification",
            "training_seed_sensitivity_iterations",
            "training_seed_sensitivity_seed",
        }
        if missing := sorted(required_bootstrap_fields.difference(raw)):
            raise ConfigError(
                "test bootstrap design must be explicitly preregistered; missing: "
                + ", ".join(missing)
            )
        comparisons: list[tuple[str, str, str]] = []
        for index, comparison in enumerate(raw.get("paired_comparisons", [])):
            if isinstance(comparison, Mapping):
                reference = str(comparison.get("reference", ""))
                challenger = str(comparison.get("challenger", ""))
                label = str(comparison.get("label", f"{challenger}_minus_{reference}"))
            elif isinstance(comparison, (list, tuple)) and len(comparison) == 3:
                reference, challenger, label = (str(x) for x in comparison)
            else:
                raise ConfigError(f"test.paired_comparisons[{index}] must be a mapping")
            if not reference or not challenger or not _SAFE_NAME.fullmatch(label):
                raise ConfigError(
                    f"invalid test.paired_comparisons[{index}] reference/challenger/label"
                )
            comparisons.append((reference, challenger, label))
        matched_checkpoint_ablations: list[tuple[str, str]] = []
        for index, ablation in enumerate(
            raw.get("matched_checkpoint_inference_ablations", [])
        ):
            if isinstance(ablation, Mapping):
                candidate = str(ablation.get("candidate", ""))
                label = str(ablation.get("label", ""))
            elif isinstance(ablation, (list, tuple)) and len(ablation) == 2:
                candidate, label = (str(value) for value in ablation)
            else:
                raise ConfigError(
                    "test.matched_checkpoint_inference_ablations"
                    f"[{index}] must be a mapping"
                )
            if (
                not candidate
                or not label
                or not _SAFE_NAME.fullmatch(candidate)
                or not _SAFE_NAME.fullmatch(label)
            ):
                raise ConfigError(
                    "invalid test.matched_checkpoint_inference_ablations"
                    f"[{index}] candidate/label"
                )
            matched_checkpoint_ablations.append((candidate, label))
        plan = cls(
            include_selected=bool(raw.get("include_selected", True)),
            fixed_candidates=tuple(str(x) for x in raw.get("fixed_candidates", [])),
            paired_reference=raw.get("paired_reference"),
            paired_comparisons=tuple(comparisons),
            matched_checkpoint_inference_ablations=tuple(matched_checkpoint_ablations),
            bootstrap_iterations=int(raw["bootstrap_iterations"]),
            bootstrap_seed=int(raw["bootstrap_seed"]),
            bootstrap_stratification=str(raw["bootstrap_stratification"]),
            training_seed_sensitivity_iterations=int(
                raw["training_seed_sensitivity_iterations"]
            ),
            training_seed_sensitivity_seed=int(raw["training_seed_sensitivity_seed"]),
            confidence_level=float(raw.get("confidence_level", 0.95)),
            cluster_permutation_iterations=int(
                raw.get("cluster_permutation_iterations", 20000)
            ),
            cluster_permutation_seed=int(raw.get("cluster_permutation_seed", 314159)),
        )
        if not plan.include_selected and not plan.fixed_candidates:
            raise ConfigError("test plan would evaluate no candidates")
        if plan.bootstrap_iterations < 100:
            raise ConfigError("test.bootstrap_iterations must be >= 100")
        if not 0 <= plan.bootstrap_seed <= 2**32 - 1:
            raise ConfigError("test.bootstrap_seed must be between 0 and 2^32 - 1")
        if plan.training_seed_sensitivity_iterations < 100:
            raise ConfigError(
                "test.training_seed_sensitivity_iterations must be >= 100"
            )
        if not 0 <= plan.training_seed_sensitivity_seed <= 2**32 - 1:
            raise ConfigError(
                "test.training_seed_sensitivity_seed must be between 0 and 2^32 - 1"
            )
        if plan.training_seed_sensitivity_seed != plan.bootstrap_seed:
            raise ConfigError(
                "test.training_seed_sensitivity_seed must equal bootstrap_seed so "
                "both analyses use the same derived cluster-resample stream; an "
                "independent spawned child is reserved for training-seed draws"
            )
        if plan.bootstrap_stratification != "utc_month_x_cluster_majority_label_v1":
            raise ConfigError(
                "test.bootstrap_stratification must be "
                "utc_month_x_cluster_majority_label_v1"
            )
        if not 0.5 < plan.confidence_level < 1.0:
            raise ConfigError("test.confidence_level must be between 0.5 and 1")
        if plan.cluster_permutation_iterations < 1000:
            raise ConfigError("test.cluster_permutation_iterations must be >= 1000")
        return plan


@dataclass(frozen=True)
class ExperimentConfig:
    schema_version: int
    experiment_name: str
    split_dir: Path
    image_embeddings_dir: Path
    text_embeddings_dir: Path
    output_root: Path
    id_column: str
    embedding_index_column: str
    label_column: str
    label_name_column: str
    text_column: str | None
    image_column: str | None
    time_column: str
    group_columns: tuple[str, ...]
    expected_num_classes: int
    require_all_classes: bool
    require_split_manifest: bool
    require_strict_temporal_test: bool
    fail_on_exact_cross_split_duplicates: bool
    l2_per_modality: bool
    hash_embeddings: bool
    require_embedding_receipts: bool
    seeds: tuple[int, ...]
    selection_metric: str
    deployment_eligible_candidates: tuple[str, ...]
    calibration_family: str
    calibration_fitting_objective: str
    calibration_probability_scope: str
    calibration_claim: str
    ece_bins: int
    ece_family: str
    ece_binning: str
    ece_bin_interval_semantics: str
    virtual_ensembles: int
    coverage_points: tuple[float, ...]
    review_operating_criterion: str
    review_target_coverage: float
    review_target_population: str
    review_threshold_source: str
    review_tie_policy: str
    catboost: CatBoostBudget
    candidates: tuple[CandidateConfig, ...]
    test: TestPlan
    source_path: Path | None = None
    source_sha256: str | None = None

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, Any],
        *,
        base_dir: Path,
        source_path: Path | None = None,
        source_sha256: str | None = None,
    ) -> ExperimentConfig:
        paths = _require_mapping(raw.get("paths", {}), "paths")
        data = _require_mapping(raw.get("data", {}), "data")
        protocol = _require_mapping(raw.get("protocol", {}), "protocol")
        uncertainty = _require_mapping(raw.get("uncertainty", {}), "uncertainty")
        metrics = _require_mapping(raw.get("metrics", {}), "metrics")
        calibration = _require_mapping(raw.get("calibration", {}), "calibration")
        selective_review = _require_mapping(
            raw.get("selective_review", {}), "selective_review"
        )
        candidates_raw = raw.get("candidates", [])
        if not isinstance(candidates_raw, list):
            raise ConfigError("candidates must be a list")

        config = cls(
            schema_version=int(raw.get("schema_version", 1)),
            experiment_name=str(raw.get("experiment_name", "")),
            split_dir=_resolve(base_dir, paths.get("split_dir", ""), "paths.split_dir"),
            image_embeddings_dir=_resolve(
                base_dir,
                paths.get("image_embeddings_dir", ""),
                "paths.image_embeddings_dir",
            ),
            text_embeddings_dir=_resolve(
                base_dir,
                paths.get("text_embeddings_dir", ""),
                "paths.text_embeddings_dir",
            ),
            output_root=_resolve(
                base_dir, paths.get("output_root", ""), "paths.output_root"
            ),
            id_column=str(data.get("id_column", "row_id")),
            embedding_index_column=str(
                data.get("embedding_index_column", "embedding_index")
            ),
            label_column=str(data.get("label_column", "label_id")),
            label_name_column=data.get("label_name_column", "label"),
            text_column=data.get("text_column", "laporan"),
            image_column=data.get("image_column", "gambar"),
            time_column=str(data.get("time_column", "created_at")),
            group_columns=tuple(str(x) for x in data.get("group_columns", [])),
            expected_num_classes=int(data.get("expected_num_classes", 0)),
            require_all_classes=bool(data.get("require_all_classes", True)),
            require_split_manifest=bool(data.get("require_split_manifest", True)),
            require_strict_temporal_test=bool(
                data.get("require_strict_temporal_test", True)
            ),
            fail_on_exact_cross_split_duplicates=bool(
                data.get("fail_on_exact_cross_split_duplicates", True)
            ),
            l2_per_modality=bool(data.get("l2_per_modality", True)),
            hash_embeddings=bool(protocol.get("hash_embeddings", True)),
            require_embedding_receipts=bool(
                protocol.get("require_embedding_receipts", True)
            ),
            seeds=tuple(int(x) for x in protocol.get("seeds", [])),
            selection_metric=str(protocol.get("selection_metric", "macro_f1")),
            deployment_eligible_candidates=tuple(
                str(x) for x in protocol.get("deployment_eligible_candidates", [])
            ),
            calibration_family=str(
                calibration.get("family", "identity_no_posthoc_calibration")
            ),
            calibration_fitting_objective=str(
                calibration.get("fitting_objective", "not_applicable_identity")
            ),
            calibration_probability_scope=str(
                calibration.get(
                    "probability_scope", "equal_weight_seed_ensemble_probabilities"
                )
            ),
            calibration_claim=str(
                calibration.get("claim", "uncalibrated_probabilities")
            ),
            ece_bins=int(metrics.get("ece_bins", 15)),
            ece_family=str(metrics.get("ece_family", "top_label")),
            ece_binning=str(metrics.get("ece_binning", "equal_width_0_1")),
            ece_bin_interval_semantics=str(
                metrics.get(
                    "ece_bin_interval_semantics",
                    "left_closed_right_open_final_closed",
                )
            ),
            virtual_ensembles=int(uncertainty.get("virtual_ensembles", 30)),
            coverage_points=tuple(
                float(x)
                for x in uncertainty.get(
                    "coverage_points", [1.0, 0.9, 0.8, 0.7, 0.5, 0.3, 0.1]
                )
            ),
            review_operating_criterion=str(
                selective_review.get(
                    "operating_criterion",
                    "fixed_target_joint_validation_coverage_on_predicted_routable_labels",
                )
            ),
            review_target_coverage=float(selective_review.get("target_coverage", 0.8)),
            review_target_population=str(
                selective_review.get(
                    "target_population", "predicted_routable_labels_only"
                )
            ),
            review_threshold_source=str(
                selective_review.get("threshold_source", "validation_seed_ensemble")
            ),
            review_tie_policy=str(
                selective_review.get("tie_policy", "include_all_at_boundary")
            ),
            catboost=CatBoostBudget.from_dict(
                _require_mapping(raw.get("catboost", {}), "catboost")
            ),
            candidates=tuple(CandidateConfig.from_dict(x) for x in candidates_raw),
            test=TestPlan.from_dict(_require_mapping(raw.get("test", {}), "test")),
            source_path=source_path,
            source_sha256=source_sha256,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ConfigError(f"unsupported schema_version={self.schema_version}")
        if not _SAFE_NAME.fullmatch(self.experiment_name):
            raise ConfigError("experiment_name must be filesystem-safe")
        if self.expected_num_classes < 2:
            raise ConfigError("data.expected_num_classes must be >= 2")
        if (
            not isinstance(self.label_name_column, str)
            or not self.label_name_column.strip()
        ):
            raise ConfigError(
                "data.label_name_column is required to freeze the ordered class map"
            )
        if not self.embedding_index_column:
            raise ConfigError("data.embedding_index_column cannot be empty")
        if not self.time_column:
            raise ConfigError("data.time_column cannot be empty")
        if not self.group_columns:
            raise ConfigError(
                "data.group_columns must include a near-duplicate/incident group ID"
            )
        if "leakage_group_id" not in self.group_columns:
            raise ConfigError(
                "data.group_columns must include leakage_group_id as the inference cluster"
            )
        if not self.require_split_manifest:
            raise ConfigError(
                "data.require_split_manifest must be true for the locked Q2 protocol"
            )
        if not self.require_embedding_receipts:
            raise ConfigError(
                "protocol.require_embedding_receipts must be true; embedding file "
                "hashes alone do not establish encoder/extraction provenance"
            )
        if len(self.seeds) < 5:
            raise ConfigError("protocol.seeds must contain at least five seeds")
        if len(set(self.seeds)) != len(self.seeds):
            raise ConfigError("protocol.seeds must be unique")
        if self.selection_metric not in {
            "accuracy",
            "macro_f1",
            "balanced_accuracy",
            "macro_ovr_roc_auc",
        }:
            raise ConfigError(f"unsupported selection_metric={self.selection_metric!r}")
        if not self.deployment_eligible_candidates:
            raise ConfigError(
                "protocol.deployment_eligible_candidates must preregister at least "
                "one primary-selection candidate"
            )
        if len(set(self.deployment_eligible_candidates)) != len(
            self.deployment_eligible_candidates
        ):
            raise ConfigError("protocol.deployment_eligible_candidates must be unique")
        if self.ece_bins < 2:
            raise ConfigError("metrics.ece_bins must be >= 2")
        expected_calibration = {
            "family": "identity_no_posthoc_calibration",
            "fitting_objective": "not_applicable_identity",
            "probability_scope": "equal_weight_seed_ensemble_probabilities",
            "claim": "uncalibrated_probabilities",
        }
        observed_calibration = {
            "family": self.calibration_family,
            "fitting_objective": self.calibration_fitting_objective,
            "probability_scope": self.calibration_probability_scope,
            "claim": self.calibration_claim,
        }
        if observed_calibration != expected_calibration:
            raise ConfigError(
                "calibration must explicitly use the preregistered identity/no-claim "
                f"contract: expected {expected_calibration}, got {observed_calibration}"
            )
        expected_ece = {
            "family": "top_label",
            "binning": "equal_width_0_1",
            "interval_semantics": "left_closed_right_open_final_closed",
        }
        observed_ece = {
            "family": self.ece_family,
            "binning": self.ece_binning,
            "interval_semantics": self.ece_bin_interval_semantics,
        }
        if observed_ece != expected_ece:
            raise ConfigError(
                f"metrics ECE semantics must equal {expected_ece}, got {observed_ece}"
            )
        if self.virtual_ensembles < 2:
            raise ConfigError("uncertainty.virtual_ensembles must be >= 2")
        minimum_pgs_patience = 2 * self.virtual_ensembles + 1
        if self.catboost.early_stopping_rounds < minimum_pgs_patience:
            raise ConfigError(
                "catboost.early_stopping_rounds must be at least "
                f"2 * virtual_ensembles + 1 ({minimum_pgs_patience}) so the "
                "matched posterior model retains enough trees for PGS"
            )
        if self.catboost.iterations < minimum_pgs_patience:
            raise ConfigError(
                f"catboost.iterations must be >= {minimum_pgs_patience} for "
                f"{self.virtual_ensembles} virtual ensembles"
            )
        if not self.coverage_points:
            raise ConfigError("uncertainty.coverage_points cannot be empty")
        if any(not 0 < x <= 1 for x in self.coverage_points):
            raise ConfigError("coverage points must be in (0, 1]")
        expected_review_protocol = {
            "operating_criterion": (
                "fixed_target_joint_validation_coverage_on_predicted_routable_labels"
            ),
            "target_population": "predicted_routable_labels_only",
            "threshold_source": "validation_seed_ensemble",
            "tie_policy": "include_all_at_boundary",
        }
        observed_review_protocol = {
            "operating_criterion": self.review_operating_criterion,
            "target_population": self.review_target_population,
            "threshold_source": self.review_threshold_source,
            "tie_policy": self.review_tie_policy,
        }
        if observed_review_protocol != expected_review_protocol:
            raise ConfigError(
                "selective_review protocol differs from the supported frozen rule: "
                f"expected {expected_review_protocol}, got {observed_review_protocol}"
            )
        if not 0.0 < self.review_target_coverage <= 1.0:
            raise ConfigError("selective_review.target_coverage must be in (0, 1]")
        if not self.candidates:
            raise ConfigError("at least one candidate is required")
        names = [candidate.name for candidate in self.candidates]
        if len(set(names)) != len(names):
            raise ConfigError("candidate names must be unique")
        unknown_selection = sorted(
            set(self.deployment_eligible_candidates).difference(names)
        )
        if unknown_selection:
            raise ConfigError(
                "protocol.deployment_eligible_candidates contains unknown names: "
                + ", ".join(unknown_selection)
            )
        catboost_treatment_params = {
            json.dumps(candidate.params, sort_keys=True, separators=(",", ":"))
            for candidate in self.candidates
            if candidate.model == "catboost"
        }
        if len(catboost_treatment_params) > 1:
            raise ConfigError(
                "all CatBoost candidates must use identical candidate.params; "
                "encoder and posterior_sampling are the only allowed treatment differences"
            )
        unknown_test = sorted(set(self.test.fixed_candidates).difference(names))
        if unknown_test:
            raise ConfigError(
                "test.fixed_candidates contains unknown names: "
                + ", ".join(unknown_test)
            )
        if (
            self.test.paired_reference is not None
            and self.test.paired_reference not in names
        ):
            raise ConfigError(
                f"test.paired_reference={self.test.paired_reference!r} is unknown"
            )
        for reference, challenger, _ in self.test.paired_comparisons:
            unknown = sorted({reference, challenger}.difference(names))
            if unknown:
                raise ConfigError(
                    "test.paired_comparisons contains unknown candidates: "
                    + ", ".join(unknown)
                )
        matched_checkpoint_candidates = [
            candidate
            for candidate, _ in self.test.matched_checkpoint_inference_ablations
        ]
        matched_checkpoint_labels = [
            label for _, label in self.test.matched_checkpoint_inference_ablations
        ]
        if len(set(matched_checkpoint_candidates)) != len(
            matched_checkpoint_candidates
        ) or len(set(matched_checkpoint_labels)) != len(matched_checkpoint_labels):
            raise ConfigError(
                "test.matched_checkpoint_inference_ablations must use unique "
                "candidate names and labels"
            )
        for candidate_name in matched_checkpoint_candidates:
            if candidate_name not in names:
                raise ConfigError(
                    "test.matched_checkpoint_inference_ablations contains unknown "
                    f"candidate: {candidate_name}"
                )
            candidate = self.candidate(candidate_name)
            if candidate.model != "catboost" or not candidate.posterior_sampling:
                raise ConfigError(
                    "matched-checkpoint inference ablations require a CatBoost "
                    f"posterior-sampling candidate: {candidate_name}"
                )
            if candidate_name not in self.test.fixed_candidates:
                raise ConfigError(
                    "matched-checkpoint inference ablation candidate must be in "
                    f"test.fixed_candidates: {candidate_name}"
                )

    def candidate(self, name: str) -> CandidateConfig:
        for candidate in self.candidates:
            if candidate.name == name:
                return candidate
        raise ConfigError(f"unknown candidate {name!r}")

    def resolved_dict(self) -> dict[str, Any]:
        """Return an immutable, JSON-safe snapshot with absolute input paths."""
        result = asdict(self)
        result["split_dir"] = str(self.split_dir)
        result["image_embeddings_dir"] = str(self.image_embeddings_dir)
        result["text_embeddings_dir"] = str(self.text_embeddings_dir)
        result["output_root"] = str(self.output_root)
        result["source_path"] = str(self.source_path) if self.source_path else None
        return result

    def protocol_digest(self) -> str:
        payload = self.resolved_dict()
        payload.pop("source_sha256", None)
        payload.pop("source_path", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return sha256(encoded).hexdigest()


def load_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path).expanduser().resolve()
    raw_bytes = config_path.read_bytes()
    raw = yaml.safe_load(raw_bytes)
    if not isinstance(raw, Mapping):
        raise ConfigError("configuration root must be a mapping")
    return ExperimentConfig.from_dict(
        raw,
        base_dir=config_path.parent,
        source_path=config_path,
        source_sha256=sha256(raw_bytes).hexdigest(),
    )


def load_resolved_config(path: str | Path) -> ExperimentConfig:
    """Load the JSON snapshot written when a selection run was created."""
    snapshot_path = Path(path).resolve()
    raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    source_path = Path(raw["source_path"]) if raw.get("source_path") else None
    source_sha = raw.get("source_sha256")
    reconstructed = {
        "schema_version": raw["schema_version"],
        "experiment_name": raw["experiment_name"],
        "paths": {
            "split_dir": raw["split_dir"],
            "image_embeddings_dir": raw["image_embeddings_dir"],
            "text_embeddings_dir": raw["text_embeddings_dir"],
            "output_root": raw["output_root"],
        },
        "data": {
            "id_column": raw["id_column"],
            "embedding_index_column": raw["embedding_index_column"],
            "label_column": raw["label_column"],
            "label_name_column": raw["label_name_column"],
            "text_column": raw["text_column"],
            "image_column": raw["image_column"],
            "time_column": raw["time_column"],
            "group_columns": raw["group_columns"],
            "expected_num_classes": raw["expected_num_classes"],
            "require_all_classes": raw["require_all_classes"],
            "require_split_manifest": raw["require_split_manifest"],
            "require_strict_temporal_test": raw["require_strict_temporal_test"],
            "fail_on_exact_cross_split_duplicates": raw[
                "fail_on_exact_cross_split_duplicates"
            ],
            "l2_per_modality": raw["l2_per_modality"],
        },
        "protocol": {
            "hash_embeddings": raw["hash_embeddings"],
            "require_embedding_receipts": raw["require_embedding_receipts"],
            "seeds": raw["seeds"],
            "selection_metric": raw["selection_metric"],
            "deployment_eligible_candidates": raw["deployment_eligible_candidates"],
        },
        "calibration": {
            "family": raw["calibration_family"],
            "fitting_objective": raw["calibration_fitting_objective"],
            "probability_scope": raw["calibration_probability_scope"],
            "claim": raw["calibration_claim"],
        },
        "metrics": {
            "ece_bins": raw["ece_bins"],
            "ece_family": raw["ece_family"],
            "ece_binning": raw["ece_binning"],
            "ece_bin_interval_semantics": raw["ece_bin_interval_semantics"],
        },
        "uncertainty": {
            "virtual_ensembles": raw["virtual_ensembles"],
            "coverage_points": raw["coverage_points"],
        },
        "selective_review": {
            "operating_criterion": raw["review_operating_criterion"],
            "target_coverage": raw["review_target_coverage"],
            "target_population": raw["review_target_population"],
            "threshold_source": raw["review_threshold_source"],
            "tie_policy": raw["review_tie_policy"],
        },
        "catboost": raw["catboost"],
        "candidates": raw["candidates"],
        "test": raw["test"],
    }
    return ExperimentConfig.from_dict(
        reconstructed,
        base_dir=snapshot_path.parent,
        source_path=source_path,
        source_sha256=source_sha,
    )
