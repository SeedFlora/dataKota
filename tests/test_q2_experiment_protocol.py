from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from crm.experiments.artifacts import artifact_record, object_sha256
from crm.experiments.config import CandidateConfig, load_config
from crm.experiments.data import (
    DataProtocolError,
    EmbeddingStore,
    validate_split_manifest,
)
from crm.experiments.models import (
    PredictionBundle,
    catboost_parameters,
    fit_candidate,
    load_fitted_model,
    predict_candidate,
    predict_native_point_from_posterior_checkpoint,
    save_fitted_model,
)
from crm.experiments.runner import (
    ProtocolStateError,
    _aggregate_validation,
    _deployment_eligible_leaderboard,
    _seed_ensemble_prediction,
    _selected_review_policy,
    _validation_review_operating_points,
    run_locked_test,
    run_selection,
)
from crm.preprocessing_contract import preprocessing_sha256
from crm.splitting import class_map_sha256
from tests.preprocessing_examples import image_preprocessing
from tools import q2_readiness


def _tiny_protocol(tmp_path: Path):
    split_dir = tmp_path / "splits"
    image_dir = tmp_path / "image"
    text_dir = tmp_path / "text"
    split_dir.mkdir()
    image_dir.mkdir()
    text_dir.mkdir()

    rows = []
    partitions = {
        "train": pd.date_range("2026-01-01", periods=6, freq="D", tz="UTC"),
        "val": pd.date_range("2026-02-01", periods=6, freq="D", tz="UTC"),
        "test": pd.date_range("2026-03-01", periods=6, freq="D", tz="UTC"),
    }
    row_id = 1000
    embedding_index = 0
    for split, timestamps in partitions.items():
        split_rows = []
        for index, timestamp in enumerate(timestamps):
            split_rows.append(
                {
                    "row_id": row_id,
                    "embedding_index": embedding_index,
                    "label_id": index % 2,
                    "label": f"class_{index % 2}",
                    "laporan": f"unique report {split} {index}",
                    "gambar": f"unique_{split}_{index}.jpg",
                    "created_at": timestamp.isoformat(),
                    "leakage_group_id": f"group_{split}_{index}",
                }
            )
            rows.append(split_rows[-1])
            row_id += 7
            embedding_index += 1
        pd.DataFrame(split_rows).to_csv(split_dir / f"{split}.csv", index=False)

    rng = np.random.default_rng(123)
    np.save(
        image_dir / "tiny_image.npy", rng.normal(size=(len(rows), 4)).astype("float32")
    )
    np.save(
        text_dir / "tiny_text.npy", rng.normal(size=(len(rows), 3)).astype("float32")
    )
    source_path = tmp_path / "source_snapshot.csv"
    pd.DataFrame(rows).to_csv(source_path, index=False)
    source_hash = sha256(source_path.read_bytes()).hexdigest()
    embedding_index_mapping_hash = sha256(
        json.dumps(list(range(len(rows))), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    image_path = image_dir / "tiny_image.npy"
    image_contract = image_preprocessing()
    (image_dir / "tiny_image.receipt.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "modality": "image",
                "encoder_name": "tiny_image",
                "embedding_file": image_path.name,
                "embedding_sha256": sha256(image_path.read_bytes()).hexdigest(),
                "source_snapshot_sha256": source_hash,
                "source_row_order_sha256": source_hash,
                "embedding_index_column": "embedding_index",
                "embedding_index_mapping_sha256": embedding_index_mapping_hash,
                "encoder": {
                    "repository": "example/tiny-image-encoder",
                    "revision": "1" * 40,
                },
                "preprocessing": image_contract,
                "preprocessing_sha256": preprocessing_sha256(image_contract),
                "pooling": "cls_token",
                "prefix": None,
                "max_length": None,
                "rows": len(rows),
                "dimension": 4,
                "dtype": "float32",
                "extraction_code_commit": "2" * 40,
            }
        ),
        encoding="utf-8",
    )
    outputs = {}
    for split in partitions:
        split_path = split_dir / f"{split}.csv"
        outputs[split] = {
            "path": split_path.name,
            "sha256": sha256(split_path.read_bytes()).hexdigest(),
        }
        if split == "test":
            outputs[split]["statistics_withheld_until_locked_evaluation"] = True
        else:
            outputs[split]["rows"] = 6
    class_map = {
        "schema_version": 1,
        "label_id_column": "label_id",
        "label_name_column": "label",
        "classes": [
            {"label_id": 0, "label_name": "class_0"},
            {"label_id": 1, "label_name": "class_1"},
        ],
    }
    class_map["sha256"] = class_map_sha256(class_map)
    preregistration = {
        "schema_version": 1,
        "source_snapshot_sha256": source_hash,
        "created_at_utc": "2025-12-01T00:00:00+00:00",
        "data_custodian": "synthetic-test-custodian",
        "test_labels_inspected": False,
        "rationale": "Synthetic temporal holdout fixed before the test fixture runs.",
        "attempt_log": [
            {"attempt": 1, "decision": "Use the predetermined temporal fractions."}
        ],
        "cutoff_policy": {
            "mode": "temporal_fraction",
            "train_fraction": 0.7,
            "val_fraction": 0.15,
        },
    }
    preregistration_hash = sha256(
        json.dumps(
            preregistration,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    (split_dir / "split_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategy": "grouped_strict_temporal_holdout",
                "embedding_index_column": "embedding_index",
                "embedding_index": {
                    "column": "embedding_index",
                    "source": "existing_metadata_column",
                    "source_order_sha256": source_hash,
                    "mapping_sha256": embedding_index_mapping_hash,
                },
                "class_map": class_map,
                "cutoff_preregistration": {
                    "source_file_sha256": "3" * 64,
                    "declaration_sha256": preregistration_hash,
                    "declaration": preregistration,
                },
                "time_column": "created_at",
                "group_columns": ["leakage_group_id"],
                "near_text_grouping": {"method": "simhash_bktree"},
                "near_image_grouping": {"method": "dhash_bktree"},
                "grouping": {"missing_images": 0, "unreadable_images": 0},
                "temporal_split": {
                    "derived_cutoffs": True,
                    "val_start": "2026-02-01T00:00:00+00:00",
                    "test_start": "2026-03-01T00:00:00+00:00",
                },
                "parameters": {
                    "test_label_membership_used_for_cutoff_acceptance": False
                },
                "source": {
                    "path": str(source_path),
                    "sha256": source_hash,
                    "rows": len(rows),
                },
                "test_statistics_withheld": True,
                "label_distribution": {
                    "train": {"0": 3, "1": 3},
                    "val": {"0": 3, "1": 3},
                },
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )

    raw_config = {
        "schema_version": 1,
        "experiment_name": "tiny_q2",
        "paths": {
            "split_dir": str(split_dir),
            "image_embeddings_dir": str(image_dir),
            "text_embeddings_dir": str(text_dir),
            "output_root": str(tmp_path / "runs"),
        },
        "data": {
            "id_column": "row_id",
            "embedding_index_column": "embedding_index",
            "label_column": "label_id",
            "label_name_column": "label",
            "text_column": "laporan",
            "image_column": "gambar",
            "time_column": "created_at",
            "group_columns": ["leakage_group_id"],
            "expected_num_classes": 2,
            "require_all_classes": True,
            "require_split_manifest": True,
            "require_strict_temporal_test": True,
            "fail_on_exact_cross_split_duplicates": True,
            "l2_per_modality": True,
        },
        "protocol": {
            "seeds": [1, 2, 3, 4, 5],
            "selection_metric": "macro_f1",
            "deployment_eligible_candidates": ["dummy", "tfidf"],
            "hash_embeddings": True,
            "require_embedding_receipts": True,
        },
        "catboost": {
            "iterations": 20,
            "learning_rate": 0.1,
            "depth": 3,
            "l2_leaf_reg": 3,
            "early_stopping_rounds": 10,
            "checkpoint_tree_policy": (
                "full_early_stopped_trajectory_for_both_point_and_pgs"
            ),
            "eval_metric": "TotalF1:average=Macro",
            "thread_count": 1,
        },
        "metrics": {"ece_bins": 5},
        "uncertainty": {
            "virtual_ensembles": 3,
            "coverage_points": [1.0, 0.5],
        },
        "candidates": [
            {
                "name": "dummy",
                "model": "dummy_prior",
                "image_encoder": "tiny_image",
            },
            {
                "name": "tfidf",
                "model": "tfidf_logistic",
                "params": {"min_df": 1, "max_features": 100},
            },
        ],
        "test": {
            "include_selected": True,
            "fixed_candidates": ["dummy", "tfidf"],
            "paired_reference": "dummy",
            "paired_comparisons": [
                {
                    "label": "tfidf_minus_dummy",
                    "reference": "dummy",
                    "challenger": "tfidf",
                }
            ],
            "bootstrap_iterations": 100,
            # Deliberately small for this synthetic non-release test only.
            "bootstrap_seed": 271828,
            "bootstrap_stratification": ("utc_month_x_cluster_majority_label_v1"),
            "training_seed_sensitivity_iterations": 100,
            "training_seed_sensitivity_seed": 271828,
            "confidence_level": 0.95,
            "cluster_permutation_iterations": 1000,
            "cluster_permutation_seed": 12345,
        },
    }
    config_path = tmp_path / "protocol.yaml"
    config_path.write_text(yaml.safe_dump(raw_config), encoding="utf-8")
    return load_config(config_path), split_dir


def test_validation_selection_never_parses_test_csv(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    original = pd.read_csv

    def guarded_read_csv(path, *args, **kwargs):
        if Path(path).name == "test.csv":
            raise AssertionError("selection attempted to parse locked test.csv")
        return original(path, *args, **kwargs)

    run_dir = tmp_path / "selection_run"
    with patch("crm.experiments.data.pd.read_csv", side_effect=guarded_read_csv):
        run_selection(config, run_dir=run_dir)
    receipt = json.loads((run_dir / "selection" / "selection_receipt.json").read_text())
    assert receipt["test_csv_parsed"] is False
    assert receipt["class_map_sha256"]
    assert "label_distribution" not in json.dumps(receipt)
    assert all(
        not Path(record["path"]).is_absolute()
        for record in receipt["artifacts"].values()
    )
    manifest = json.loads((config.split_dir / "split_manifest.json").read_text())
    assert manifest["test_statistics_withheld"] is True
    assert "test" not in manifest["label_distribution"]
    assert "rows" not in manifest["outputs"]["test"]


def test_selection_primary_score_uses_mean_probabilities_not_mean_seed_f1(
    tmp_path: Path,
) -> None:
    config, split_dir = _tiny_protocol(tmp_path)
    validation = pd.read_csv(split_dir / "val.csv")
    y_true = validation[config.label_column].to_numpy(dtype=np.int64)
    run_dir = tmp_path / "ensemble_selection"
    receipts = []
    for candidate in config.candidates:
        for seed_index, seed in enumerate(config.seeds):
            if candidate.name == "dummy":
                # Three individually perfect but weak heads and two confidently
                # wrong heads: mean seed F1 is high, yet their probability mean
                # is wrong for every row.
                correct_head = seed_index < 3
                probabilities = np.empty((len(y_true), 2), dtype=np.float64)
                for row_index, label in enumerate(y_true):
                    true_probability = 0.51 if correct_head else 0.01
                    probabilities[row_index, label] = true_probability
                    probabilities[row_index, 1 - label] = 1.0 - true_probability
                seed_macro_f1 = 1.0 if correct_head else 0.0
            else:
                # Always predicting class zero yields macro-F1 1/3 here; this
                # stable ensemble must beat the misleading mean-seed winner.
                probabilities = np.tile([0.7, 0.3], (len(y_true), 1))
                seed_macro_f1 = 1.0 / 3.0
            prediction_path = (
                run_dir
                / "selection"
                / candidate.name
                / f"seed_{seed}"
                / "predictions.csv.gz"
            )
            prediction_path.parent.mkdir(parents=True, exist_ok=True)
            frame = pd.DataFrame(
                {
                    config.id_column: validation[config.id_column],
                    "y_true": y_true,
                    "y_pred": probabilities.argmax(axis=1),
                    "prob_0": probabilities[:, 0],
                    "prob_1": probabilities[:, 1],
                    "uncertainty_predictive_entropy": -np.sum(
                        probabilities * np.log(np.clip(probabilities, 1e-12, 1.0)),
                        axis=1,
                    ),
                    "uncertainty_one_minus_confidence": (
                        1.0 - probabilities.max(axis=1)
                    ),
                }
            )
            frame.to_csv(prediction_path, index=False, compression="gzip")
            receipts.append(
                {
                    "candidate": candidate.name,
                    "seed": seed,
                    "model": candidate.model,
                    "image_encoder": candidate.image_encoder,
                    "text_encoder": candidate.text_encoder,
                    "posterior_sampling": candidate.posterior_sampling,
                    "fit_seconds": 0.0,
                    "metrics": {"macro_f1": seed_macro_f1},
                    "artifacts": {
                        "predictions": artifact_record(
                            prediction_path, base_dir=run_dir
                        ),
                        "checkpoint": {"size_bytes": 100 + seed_index},
                    },
                }
            )

    by_seed, leaderboard, _ = _aggregate_validation(
        config, run_dir, validation, receipts
    )
    seed_means = by_seed.groupby("candidate")["macro_f1"].mean()
    assert seed_means["dummy"] > seed_means["tfidf"]
    assert leaderboard.iloc[0]["candidate"] == "tfidf"
    assert (
        leaderboard.iloc[0]["ensemble_macro_f1"]
        > leaderboard.iloc[1]["ensemble_macro_f1"]
    )


def test_ineligible_baseline_cannot_become_the_deployed_primary_winner(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    deployable = CandidateConfig(
        name="cb_dinov3_me5_point",
        model="catboost",
        image_encoder="dinov3_large",
        text_encoder="mE5_large",
    )
    late_fusion = CandidateConfig(
        name="latefusion_dinov3_me5",
        model="late_fusion_catboost",
        image_encoder="dinov3_large",
        text_encoder="mE5_large",
    )
    config = replace(
        config,
        candidates=(deployable, late_fusion),
        deployment_eligible_candidates=(deployable.name,),
    )
    global_leaderboard = pd.DataFrame(
        [
            {
                "candidate": late_fusion.name,
                "ensemble_macro_f1": 0.92,
                "ensemble_nll": 0.20,
                "total_checkpoint_size_bytes": 10,
            },
            {
                "candidate": deployable.name,
                "ensemble_macro_f1": 0.88,
                "ensemble_nll": 0.25,
                "total_checkpoint_size_bytes": 20,
            },
        ]
    )

    eligible = _deployment_eligible_leaderboard(config, global_leaderboard)

    assert global_leaderboard.iloc[0]["candidate"] == late_fusion.name
    assert eligible.iloc[0]["candidate"] == deployable.name
    assert eligible.iloc[0]["global_validation_rank"] == 2


def test_pgs_review_thresholds_target_joint_not_independent_coverage(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = replace(config.candidates[0], posterior_sampling=True)
    config = replace(config, candidates=(candidate,))
    predictions = pd.DataFrame(
        {
            "candidate": [candidate.name] * 10,
            "y_true": [0, 1] * 5,
            "y_pred": [0, 1] * 5,
            "uncertainty_one_minus_confidence": np.arange(10, dtype=float),
            "uncertainty_epistemic_mutual_information": np.arange(
                9, -1, -1, dtype=float
            ),
        }
    )
    points = _validation_review_operating_points(
        config,
        predictions,
        ["class_0", "class_1"],
    )
    joint = points[points["uncertainty"] == "joint_deployed_review_policy"].iloc[0]
    assert joint["realized_coverage"] == 0.8
    assert joint["marginal_quantile_coverage"] == 0.9
    policy = _selected_review_policy(
        config,
        candidate.name,
        points,
        ["class_0", "class_1"],
    )
    assert policy["validation_joint_realized_coverage"] == 0.8
    assert policy["marginal_quantile_coverage"] == 0.9


def test_catchall_predictions_are_excluded_from_review_target_population(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = config.candidates[0]
    config = replace(
        config,
        candidates=(candidate,),
        deployment_eligible_candidates=(candidate.name,),
    )
    predictions = pd.DataFrame(
        {
            "candidate": [candidate.name] * 10,
            "y_true": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            # Class 1 is the catch-all and must never be auto-accepted.
            "y_pred": [0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
            "uncertainty_one_minus_confidence": np.arange(10, dtype=float),
        }
    )

    points = _validation_review_operating_points(
        config,
        predictions,
        ["class_0", "Instansi lain"],
    )
    joint = points[points["uncertainty"] == "joint_deployed_review_policy"].iloc[0]

    assert joint["target_population"] == "predicted_routable_labels_only"
    assert joint["target_population_count"] == 8
    assert joint["unconditionally_reviewed_count"] == 2
    assert joint["realized_coverage"] == pytest.approx(0.875)
    assert joint["overall_realized_coverage"] == pytest.approx(0.7)
    assert joint["overall_retained"] == 7

    resolved = config.resolved_dict()
    readiness_rows = q2_readiness._recompute_validation_review_rows(
        resolved,
        {candidate.name: resolved["candidates"][0]},
        {
            candidate.name: {
                "y_true": predictions["y_true"].to_numpy(dtype=np.int64),
                "y_pred": predictions["y_pred"].to_numpy(dtype=np.int64),
                "one_minus_confidence": predictions[
                    "uncertainty_one_minus_confidence"
                ].to_numpy(dtype=np.float64),
            }
        },
        ["class_0", "Instansi lain"],
    )
    readiness_joint = next(
        row
        for row in readiness_rows
        if row["uncertainty"] == "joint_deployed_review_policy"
    )
    for field in (
        "target_population_count",
        "unconditionally_reviewed_count",
        "retained",
        "realized_coverage",
        "overall_retained",
        "overall_realized_coverage",
        "selective_risk",
        "selective_macro_f1",
    ):
        assert readiness_joint[field] == pytest.approx(joint[field])


def test_joint_seed_pgs_mi_includes_between_training_seed_dispersion() -> None:
    first_probabilities = np.asarray([[0.9, 0.1]], dtype=np.float64)
    second_probabilities = np.asarray([[0.1, 0.9]], dtype=np.float64)

    def component(probabilities: np.ndarray) -> PredictionBundle:
        entropy = -np.sum(
            probabilities * np.log(probabilities),
            axis=1,
        )
        return PredictionBundle(
            probabilities=probabilities,
            predictions=probabilities.argmax(axis=1),
            uncertainty={"expected_data_entropy": entropy},
            probability_semantics="posterior_mean_virtual_ensemble_probability",
        )

    ensemble = _seed_ensemble_prediction(
        [component(first_probabilities), component(second_probabilities)],
        posterior_sampling=True,
    )

    # Each seed can have zero within-seed PGS MI, yet the joint (seed, virtual
    # member) mixture is uncertain because the training-seed means disagree.
    expected_data_entropy = -0.9 * np.log(0.9) - 0.1 * np.log(0.1)
    expected_joint_mi = np.log(2.0) - expected_data_entropy
    assert ensemble.uncertainty["epistemic_mutual_information"][0] == pytest.approx(
        expected_joint_mi
    )
    assert ensemble.uncertainty["epistemic_mutual_information"][0] > 0.0
    assert ensemble.probability_semantics == (
        "equal_weight_mean_over_training_seed_x_pgs_virtual_member_components"
    )


def test_missing_embedding_extraction_receipt_is_a_hard_gate(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    (config.image_embeddings_dir / "tiny_image.receipt.json").unlink()
    with pytest.raises(DataProtocolError, match="missing extraction receipt"):
        run_selection(config, run_dir=tmp_path / "missing_receipt_run")


def test_incomplete_image_preprocessing_receipt_is_a_hard_gate(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    receipt_path = config.image_embeddings_dir / "tiny_image.receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    del receipt["preprocessing"]["decode"]["exif_orientation"]
    receipt["preprocessing_sha256"] = preprocessing_sha256(receipt["preprocessing"])
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(DataProtocolError, match="exif_orientation"):
        run_selection(config, run_dir=tmp_path / "incomplete_preprocessing_run")


def test_embedding_receipt_source_order_mismatch_is_rejected(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    receipt_path = config.image_embeddings_dir / "tiny_image.receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_row_order_sha256"] = "f" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(DataProtocolError, match="source row order differs"):
        run_selection(config, run_dir=tmp_path / "bad_order_run")


def test_split_rows_must_match_frozen_class_map(tmp_path: Path) -> None:
    config, split_dir = _tiny_protocol(tmp_path)
    train_path = split_dir / "train.csv"
    train = pd.read_csv(train_path)
    train.loc[0, "label"] = "class_wrong"
    train.to_csv(train_path, index=False)
    manifest_path = split_dir / "split_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["outputs"]["train"]["sha256"] = sha256(train_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(DataProtocolError, match="frozen class map"):
        run_selection(config, run_dir=tmp_path / "bad_class_map_run")


def test_tiny_selection_and_locked_test_are_one_shot(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    run_dir = run_selection(config, run_dir=tmp_path / "complete_run")
    run_locked_test(run_dir)
    assert (run_dir / "test" / "TEST_EVALUATION_COMPLETE.json").is_file()
    assert (run_dir / "test" / "dummy" / "seed_1" / "reliability_bins.csv").is_file()
    assert (
        run_dir / "test" / "dummy" / "seed_1" / "confusion_matrix_counts.csv"
    ).is_file()
    aggregate = pd.read_csv(run_dir / "test" / "phase_a_metrics_aggregate.csv")
    assert "predictive_entropy_aurc_mean" in aggregate.columns
    cluster_tests = pd.read_csv(run_dir / "test" / "cluster_paired_accuracy_tests.csv")
    assert len(cluster_tests) == 1
    assert set(cluster_tests["analysis_unit"]) == {"leakage_group_id"}
    assert "holm_adjusted_cluster_p" in cluster_tests
    ensemble_predictions = pd.read_csv(
        run_dir / "test" / "seed_ensemble_predictions.csv.gz"
    )
    assert len(ensemble_predictions) == 12
    assert set(ensemble_predictions["seed_count"]) == {5}
    assert "leakage_group_id" in ensemble_predictions
    locked_audit = json.loads(
        (run_dir / "metadata" / "locked_test_split_audit.json").read_text()
    )
    assert locked_audit["locked_test_statistics"]["rows"] == 6
    assert locked_audit["locked_test_statistics"]["label_distribution"] == {
        "0": 3,
        "1": 3,
    }
    input_manifest = json.loads(
        (run_dir / "metadata" / "input_manifest.json").read_text()
    )
    selection_receipt = json.loads(
        (run_dir / "selection" / "selection_receipt.json").read_text()
    )
    selection_leaderboard = pd.read_csv(
        run_dir / "selection" / "validation_seed_ensemble_metrics.csv"
    )
    assert selection_receipt["primary_system"] == (
        "equal_weight_preregistered_seed_ensemble"
    )
    assert "ensemble_macro_f1" in selection_leaderboard
    assert "ensemble_nll" in selection_leaderboard
    assert "total_checkpoint_size_bytes" in selection_leaderboard
    assert (
        selection_leaderboard.iloc[0]["candidate"]
        == selection_receipt["selected_candidate"]
    )
    assert {
        "validation_seed_ensemble_predictions",
        "validation_seed_ensemble_metrics",
    }.issubset(selection_receipt["artifacts"])
    test_receipt = json.loads(
        (run_dir / "test" / "TEST_EVALUATION_COMPLETE.json").read_text()
    )
    assert (
        input_manifest["class_map_sha256"]
        == selection_receipt["class_map_sha256"]
        == test_receipt["class_map_sha256"]
    )
    assert test_receipt["protocol_digest"] == config.protocol_digest()
    inference_plan = selection_receipt["prespecified_phase_a_inference_plan"]
    assert inference_plan["paired_bootstrap_iterations"] == 100
    assert inference_plan["paired_bootstrap_seed"] == 271828
    assert inference_plan["paired_bootstrap_rng_stream_derivation"] == {
        "scheme": "numpy_seedsequence_spawn_v1",
        "bit_generator": "PCG64",
        "root_entropy": 271828,
        "cluster_spawn_key": [0],
        "training_seed_spawn_key": None,
    }
    assert inference_plan["paired_bootstrap_stratification"] == (
        "utc_month_x_cluster_majority_label_v1"
    )
    assert inference_plan["paired_bootstrap_training_seed_resampling"] is False
    assert inference_plan["training_seed_sensitivity_iterations"] == 100
    assert inference_plan["training_seed_sensitivity_seed"] == 271828
    assert inference_plan["training_seed_sensitivity_rng_stream_derivation"] == {
        "scheme": "numpy_seedsequence_spawn_v1",
        "bit_generator": "PCG64",
        "root_entropy": 271828,
        "cluster_spawn_key": [0],
        "training_seed_spawn_key": [1],
    }
    bootstrap_execution = test_receipt["prespecified_phase_a_inference_execution"][
        "paired_bootstrap"
    ]
    assert bootstrap_execution["bootstrap_replicates"] == 100
    assert bootstrap_execution["bootstrap_seed"] == 271828
    assert bootstrap_execution["estimand"] == (
        "deployed_fixed_preregistered_seed_ensemble_metric_delta"
    )
    assert bootstrap_execution["training_seed_resampling"] is False
    assert (
        bootstrap_execution["bootstrap_rng_stream_derivation"]
        == (inference_plan["paired_bootstrap_rng_stream_derivation"])
    )
    assert bootstrap_execution["probability_aggregation"] == (
        "arithmetic_mean_before_argmax_and_metric"
    )
    assert bootstrap_execution["strata_cluster_counts"] == {
        "utc_month=2026-03|majority_label=0": 3,
        "utc_month=2026-03|majority_label=1": 3,
    }
    assert len(bootstrap_execution["cluster_strata_sha256"]) == 64
    sensitivity_execution = test_receipt["prespecified_phase_a_inference_execution"][
        "training_seed_sensitivity"
    ]
    assert sensitivity_execution["bootstrap_replicates"] == 100
    assert sensitivity_execution["bootstrap_seed"] == 271828
    assert sensitivity_execution["training_seed_resampling"] is True
    assert (
        sensitivity_execution["bootstrap_rng_stream_derivation"]
        == (inference_plan["training_seed_sensitivity_rng_stream_derivation"])
    )
    assert sensitivity_execution["analysis_role"] == (
        "secondary_training_seed_sensitivity"
    )
    assert (
        sensitivity_execution["cluster_strata_sha256"]
        == (bootstrap_execution["cluster_strata_sha256"])
    )
    sensitivity = pd.read_csv(
        run_dir / "test" / "training_seed_sensitivity_bootstrap.csv"
    )
    primary = pd.read_csv(run_dir / "test" / "paired_bootstrap_comparisons.csv")
    assert len(sensitivity) == len(primary)
    assert set(primary["analysis_role"]) == {"primary_phase_a_prespecified_interval"}
    assert set(sensitivity["analysis_role"]) == {"secondary_training_seed_sensitivity"}
    strata = pd.read_csv(run_dir / "test" / "bootstrap_cluster_strata.csv")
    assert len(strata) == 6
    assert set(strata["stratum"]) == {
        "utc_month=2026-03|majority_label=0",
        "utc_month=2026-03|majority_label=1",
    }
    assert {
        "bootstrap_cluster_strata",
        "environment_manifest",
        "locked_test_split_audit",
        "training_seed_sensitivity",
    }.issubset(test_receipt["artifacts"])
    assert all(
        not Path(record["path"]).is_absolute()
        for record in test_receipt["artifacts"].values()
    )
    unit_index_path = run_dir / test_receipt["artifacts"]["unit_artifact_index"]["path"]
    unit_index = json.loads(unit_index_path.read_text(encoding="utf-8"))
    assert len(unit_index["units"]) == 10
    assert all(
        not Path(unit["unit_receipt"]["path"]).is_absolute()
        for unit in unit_index["units"]
    )
    with pytest.raises(RuntimeError, match="already been opened"):
        run_locked_test(run_dir)


def test_locked_test_writes_same_checkpoint_pgs_inference_ablation(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    pgs_candidate = CandidateConfig.from_dict(
        {
            "name": "pgs_same_checkpoint",
            "model": "catboost",
            "image_encoder": "tiny_image",
            "posterior_sampling": True,
        }
    )
    ablation_label = "pgs_inference_minus_native_point_same_checkpoint"
    config = replace(
        config,
        candidates=(*config.candidates, pgs_candidate),
        test=replace(
            config.test,
            fixed_candidates=(*config.test.fixed_candidates, pgs_candidate.name),
            matched_checkpoint_inference_ablations=(
                (pgs_candidate.name, ablation_label),
            ),
        ),
    )
    config.validate()
    run_dir = run_selection(config, run_dir=tmp_path / "matched_checkpoint_run")
    run_locked_test(run_dir)

    selection_receipt = json.loads(
        (run_dir / "selection" / "selection_receipt.json").read_text()
    )
    test_receipt = json.loads(
        (run_dir / "test" / "TEST_EVALUATION_COMPLETE.json").read_text()
    )
    assert (
        test_receipt["matched_checkpoint_inference_ablation_plan"]
        == selection_receipt["matched_checkpoint_inference_ablation_plan"]
    )
    execution = test_receipt["matched_checkpoint_inference_ablation_execution"]
    assert execution["same_loaded_checkpoint_object_used_within_each_seed_pair"]
    assert len(execution["checkpoint_bindings"]) == len(config.seeds)
    assert all(
        binding["same_checkpoint_object_used_for_both_inference_modes"]
        for binding in execution["checkpoint_bindings"]
    )
    predictions = pd.read_csv(
        run_dir / "test" / "matched_checkpoint_inference_predictions.csv.gz"
    )
    assert set(predictions["inference_mode"]) == {
        "native_point_same_posterior_checkpoint",
        "virtual_ensemble_same_posterior_checkpoint",
    }
    for seed in config.seeds:
        seed_rows = predictions[predictions["seed"] == seed]
        assert seed_rows["checkpoint_sha256"].nunique() == 1
        assert seed_rows["checkpoint_tree_count"].nunique() == 1
        assert len(seed_rows) == 2 * 6
    comparisons = pd.read_csv(
        run_dir / "test" / "matched_checkpoint_inference_ablations.csv"
    )
    assert set(comparisons["comparison"]) == {ablation_label}
    assert set(comparisons["metric"]) == {"accuracy", "macro_f1"}
    assert comparisons["same_checkpoint_within_seed"].all()
    assert {
        "matched_checkpoint_inference_predictions",
        "matched_checkpoint_inference_ablations",
    }.issubset(test_receipt["artifacts"])
    resolved_config = json.loads((run_dir / "resolved_config.json").read_text())
    input_manifest = json.loads(
        (run_dir / "metadata" / "input_manifest.json").read_text()
    )

    def validate_selection(
        selection_payload: dict[str, object] = selection_receipt,
    ) -> None:
        q2_readiness._validate_validation_selection_semantics(
            resolved_config,
            input_manifest,
            selection_payload,
            input_manifest_path=run_dir / "metadata" / "input_manifest.json",
            selection_receipt_path=(run_dir / "selection" / "selection_receipt.json"),
        )

    validate_selection()

    validation_predictions_path = (
        run_dir / "selection" / "validation_seed_ensemble_predictions.csv.gz"
    )
    original_validation_predictions = pd.read_csv(validation_predictions_path)
    tampered_probabilities = original_validation_predictions.copy()
    selected_name = str(selection_receipt["selected_candidate"])
    selected_index = tampered_probabilities.index[
        tampered_probabilities["candidate"] == selected_name
    ][0]
    tampered_probabilities.loc[selected_index, "prob_0"] = 0.05
    tampered_probabilities.loc[selected_index, "prob_1"] = 0.95
    tampered_probabilities.loc[selected_index, "y_pred"] = 1
    tampered_probabilities.loc[selected_index, "confidence"] = 0.95
    tampered_probabilities.loc[selected_index, "correct"] = bool(
        int(tampered_probabilities.loc[selected_index, "y_true"]) == 1
    )
    tampered_probabilities.loc[selected_index, "uncertainty_predictive_entropy"] = (
        float(-(0.05 * np.log(0.05) + 0.95 * np.log(0.95)))
    )
    tampered_probabilities.loc[selected_index, "uncertainty_one_minus_confidence"] = (
        0.05
    )
    tampered_probabilities.to_csv(
        validation_predictions_path,
        index=False,
        compression="gzip",
    )
    with pytest.raises(ValueError, match="does not reconstruct"):
        validate_selection()

    reordered = original_validation_predictions.copy()
    selected_indices = reordered.index[reordered["candidate"] == selected_name][:2]
    reordered.loc[selected_indices] = reordered.loc[
        list(reversed(selected_indices.tolist()))
    ].to_numpy()
    reordered.to_csv(validation_predictions_path, index=False, compression="gzip")
    with pytest.raises(ValueError, match="does not reconstruct"):
        validate_selection()

    relabelled = original_validation_predictions.copy()
    relabelled.loc[selected_index, "y_true"] = 1 - int(
        relabelled.loc[selected_index, "y_true"]
    )
    relabelled.to_csv(validation_predictions_path, index=False, compression="gzip")
    with pytest.raises(ValueError, match="does not reconstruct"):
        validate_selection()
    original_validation_predictions.to_csv(
        validation_predictions_path,
        index=False,
        compression="gzip",
    )
    validate_selection()

    leaderboard_path = run_dir / "selection" / "validation_seed_ensemble_metrics.csv"
    original_leaderboard = pd.read_csv(leaderboard_path)
    reordered_leaderboard = original_leaderboard.iloc[::-1].reset_index(drop=True)
    reordered_leaderboard.to_csv(leaderboard_path, index=False)
    with pytest.raises(ValueError, match="leaderboard does not recompute"):
        validate_selection()
    original_leaderboard.to_csv(leaderboard_path, index=False)

    primary_leaderboard_path = run_dir / "selection" / "validation_leaderboard.csv"
    original_primary_leaderboard = pd.read_csv(primary_leaderboard_path)
    tampered_primary_leaderboard = original_primary_leaderboard.copy()
    tampered_primary_leaderboard.loc[0, "ensemble_nll"] = (
        float(tampered_primary_leaderboard.loc[0, "ensemble_nll"]) + 0.01
    )
    tampered_primary_leaderboard.to_csv(primary_leaderboard_path, index=False)
    with pytest.raises(ValueError, match="leaderboard does not recompute"):
        validate_selection()
    original_primary_leaderboard.to_csv(primary_leaderboard_path, index=False)

    eligible_leaderboard_path = (
        run_dir / "selection" / "validation_deployment_eligible_leaderboard.csv"
    )
    original_eligible_leaderboard = pd.read_csv(eligible_leaderboard_path)
    tampered_eligible_leaderboard = original_eligible_leaderboard.copy()
    tampered_eligible_leaderboard.loc[0, "ensemble_macro_f1"] = (
        float(tampered_eligible_leaderboard.loc[0, "ensemble_macro_f1"]) - 0.01
    )
    tampered_eligible_leaderboard.to_csv(eligible_leaderboard_path, index=False)
    with pytest.raises(
        ValueError, match="deployment-eligible validation metrics do not recompute"
    ):
        validate_selection()
    original_eligible_leaderboard.to_csv(eligible_leaderboard_path, index=False)

    forged_winner_receipt = json.loads(json.dumps(selection_receipt))
    forged_winner_receipt["selected_candidate"] = next(
        name
        for name in forged_winner_receipt["deployment_eligible_candidates"]
        if name != selected_name
    )
    forged_winner_receipt["review_policy"]["candidate"] = forged_winner_receipt[
        "selected_candidate"
    ]
    with pytest.raises(ValueError, match="winner does not recompute"):
        validate_selection(forged_winner_receipt)

    forged_checkpoint_size_receipt = json.loads(json.dumps(selection_receipt))
    forged_candidate = next(iter(forged_checkpoint_size_receipt["model_records"]))
    forged_seed = str(config.seeds[0])
    forged_checkpoint_size_receipt["model_records"][forged_candidate][forged_seed][
        "size_bytes"
    ] += 1
    with pytest.raises(ValueError, match="differs from unit evidence"):
        validate_selection(forged_checkpoint_size_receipt)

    fractional_seed_count = original_validation_predictions.copy()
    fractional_seed_count["seed_count"] = fractional_seed_count["seed_count"].astype(
        float
    )
    fractional_seed_count.loc[selected_index, "seed_count"] = len(config.seeds) + 0.5
    fractional_seed_count.to_csv(
        validation_predictions_path,
        index=False,
        compression="gzip",
    )
    with pytest.raises(ValueError, match="must be an exact integer"):
        validate_selection()
    original_validation_predictions.to_csv(
        validation_predictions_path,
        index=False,
        compression="gzip",
    )

    review_points_path = (
        run_dir / "selection" / "validation_review_operating_points.csv"
    )
    original_review_points = pd.read_csv(review_points_path)
    tampered_review_points = original_review_points.copy()
    confidence_index = tampered_review_points.index[
        (tampered_review_points["candidate"] == selected_name)
        & (tampered_review_points["uncertainty"] == "one_minus_confidence")
    ][0]
    changed_threshold = (
        float(tampered_review_points.loc[confidence_index, "uncertainty_threshold"])
        + 0.001
    )
    tampered_review_points.loc[confidence_index, "uncertainty_threshold"] = (
        changed_threshold
    )
    tampered_review_points.to_csv(review_points_path, index=False)
    coherent_tampered_receipt = json.loads(json.dumps(selection_receipt))
    coherent_tampered_receipt["review_policy"]["maximum_one_minus_confidence"] = (
        changed_threshold
    )
    coherent_tampered_receipt["review_policy"]["minimum_confidence"] = (
        1.0 - changed_threshold
    )
    with pytest.raises(ValueError, match="uncertainty_threshold does not recompute"):
        validate_selection(coherent_tampered_receipt)
    original_review_points.to_csv(review_points_path, index=False)
    validate_selection()

    q2_readiness._validate_matched_checkpoint_inference_ablation(
        resolved_config,
        input_manifest,
        selection_receipt,
        test_receipt,
        input_manifest_path=run_dir / "metadata" / "input_manifest.json",
        test_receipt_path=run_dir / "test" / "TEST_EVALUATION_COMPLETE.json",
    )

    predictions_path = (
        run_dir / "test" / "matched_checkpoint_inference_predictions.csv.gz"
    )
    original_predictions = pd.read_csv(predictions_path)
    original_predictions.iloc[:-1].to_csv(
        predictions_path,
        index=False,
        compression="gzip",
    )
    with pytest.raises(ValueError, match="missing, duplicate, or extra"):
        q2_readiness._validate_matched_checkpoint_inference_ablation(
            resolved_config,
            input_manifest,
            selection_receipt,
            test_receipt,
            input_manifest_path=run_dir / "metadata" / "input_manifest.json",
            test_receipt_path=run_dir / "test" / "TEST_EVALUATION_COMPLETE.json",
        )
    invalid_probabilities = original_predictions.copy()
    invalid_probabilities.loc[0, "prob_0"] = -0.1
    invalid_probabilities.loc[0, "prob_1"] = 1.1
    invalid_probabilities.to_csv(predictions_path, index=False, compression="gzip")
    with pytest.raises(ValueError, match="invalid matched-checkpoint predictions"):
        q2_readiness._validate_matched_checkpoint_inference_ablation(
            resolved_config,
            input_manifest,
            selection_receipt,
            test_receipt,
            input_manifest_path=run_dir / "metadata" / "input_manifest.json",
            test_receipt_path=run_dir / "test" / "TEST_EVALUATION_COMPLETE.json",
        )
    original_predictions.to_csv(predictions_path, index=False, compression="gzip")

    comparisons_path = run_dir / "test" / "matched_checkpoint_inference_ablations.csv"
    original_comparisons = pd.read_csv(comparisons_path)
    tampered_comparisons = original_comparisons.copy()
    tampered_comparisons.loc[0, "ci_lower"] = (
        float(tampered_comparisons.loc[0, "ci_lower"]) + 0.1
    )
    tampered_comparisons.to_csv(comparisons_path, index=False)
    with pytest.raises(ValueError, match="interval/tail values"):
        q2_readiness._validate_matched_checkpoint_inference_ablation(
            resolved_config,
            input_manifest,
            selection_receipt,
            test_receipt,
            input_manifest_path=run_dir / "metadata" / "input_manifest.json",
            test_receipt_path=run_dir / "test" / "TEST_EVALUATION_COMPLETE.json",
        )
    original_comparisons.to_csv(comparisons_path, index=False)


def test_test_hash_tampering_is_rejected_before_open(tmp_path: Path) -> None:
    config, split_dir = _tiny_protocol(tmp_path)
    run_dir = run_selection(config, run_dir=tmp_path / "tamper_run")
    with (split_dir / "test.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(DataProtocolError, match="changed"):
        run_locked_test(run_dir)
    assert not (run_dir / "test" / "TEST_SET_OPENED.json").exists()


def test_stale_split_manifest_is_rejected(tmp_path: Path) -> None:
    config, split_dir = _tiny_protocol(tmp_path)
    train = pd.read_csv(split_dir / "train.csv")
    train.loc[0, "laporan"] = "mutated after manifest"
    train.to_csv(split_dir / "train.csv", index=False)
    with pytest.raises(DataProtocolError, match="does not match"):
        validate_split_manifest(config)


def test_resume_rejects_protocol_changes(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    run_dir = tmp_path / "frozen_run"
    # Simulate an interrupted run by preparing the immutable snapshot, then
    # removing the final receipt after successful selection.
    run_selection(config, run_dir=run_dir)
    (run_dir / "selection" / "selection_receipt.json").unlink()
    changed = replace(config, ece_bins=config.ece_bins + 1)
    with pytest.raises(ProtocolStateError, match="differs from the frozen"):
        run_selection(changed, run_dir=run_dir, resume=True)


def test_resume_rejects_foreign_unit_receipt_identity(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    run_dir = tmp_path / "unit_identity_run"
    run_selection(config, run_dir=run_dir)
    (run_dir / "selection" / "selection_receipt.json").unlink()
    unit_path = run_dir / "selection" / "dummy" / "seed_1" / "unit_receipt.json"
    unit = json.loads(unit_path.read_text(encoding="utf-8"))
    unit.pop("receipt_digest")
    unit["candidate"] = "foreign_candidate"
    unit["receipt_digest"] = object_sha256(unit)
    unit_path.write_text(json.dumps(unit), encoding="utf-8")
    with pytest.raises(ProtocolStateError, match="incompatible identity"):
        run_selection(config, run_dir=run_dir, resume=True)


def test_embedding_index_is_not_assumed_to_equal_row_id(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = config.candidate("dummy")
    split = pd.DataFrame(
        {
            "row_id": [999999],
            "embedding_index": [2],
        }
    )
    expected = np.load(config.image_embeddings_dir / "tiny_image.npy")[2]
    actual = EmbeddingStore(config).build(candidate, split)[0]
    expected = expected / np.linalg.norm(expected)
    np.testing.assert_allclose(actual, expected, atol=1e-6)


def test_catboost_point_and_pgs_have_matched_budget(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    base = replace(
        config.candidate("dummy"),
        name="point",
        model="catboost",
        posterior_sampling=False,
    )
    pgs = replace(base, name="pgs", posterior_sampling=True)
    point_params = catboost_parameters(config, base, seed=42)
    pgs_params = catboost_parameters(config, pgs, seed=42)
    assert point_params.pop("posterior_sampling") is False
    assert pgs_params.pop("posterior_sampling") is True
    assert point_params == pgs_params


def test_stratified_random_sanity_candidate_is_seeded_and_probabilistic(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = CandidateConfig(
        name="stratified_random",
        model="dummy_stratified",
        text_encoder="tiny_text",
    )
    X_train = np.arange(36, dtype=np.float32).reshape(12, 3)
    y_train = np.tile([0, 1], 6)
    X_val = np.arange(18, dtype=np.float32).reshape(6, 3)
    y_val = np.tile([0, 1], 3)
    first = fit_candidate(config, candidate, 13, X_train, y_train, X_val, y_val)
    second = fit_candidate(config, candidate, 13, X_train, y_train, X_val, y_val)
    first_prediction = predict_candidate(
        first, X_val, virtual_ensembles=config.virtual_ensembles
    )
    second_prediction = predict_candidate(
        second, X_val, virtual_ensembles=config.virtual_ensembles
    )
    assert first.metadata["parameters"] == {
        "strategy": "stratified",
        "random_state": 13,
    }
    np.testing.assert_array_equal(
        first_prediction.probabilities, second_prediction.probabilities
    )
    np.testing.assert_allclose(first_prediction.probabilities.sum(axis=1), 1.0)


def test_pgs_candidate_retains_preregistered_virtual_ensemble_budget(
    tmp_path: Path,
) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = CandidateConfig.from_dict(
        {
            "name": "pgs",
            "model": "catboost",
            "image_encoder": "tiny_image",
            "posterior_sampling": True,
        }
    )
    rng = np.random.default_rng(1234)
    y_train = np.tile([0, 1], 30)
    y_val = np.tile([0, 1], 10)
    X_train = rng.normal(size=(len(y_train), 5)).astype("float32")
    X_val = rng.normal(size=(len(y_val), 5)).astype("float32")
    X_train[:, 0] += y_train
    X_val[:, 0] += y_val
    fitted = fit_candidate(config, candidate, 13, X_train, y_train, X_val, y_val)
    point_candidate = replace(
        candidate,
        name="point",
        posterior_sampling=False,
    )
    point_fitted = fit_candidate(
        config,
        point_candidate,
        13,
        X_train,
        y_train,
        X_val,
        y_val,
    )
    assert fitted.metadata["trained_tree_count"] >= 2 * config.virtual_ensembles + 1
    for trained in (point_fitted, fitted):
        assert trained.metadata["checkpoint_tree_policy"] == (
            "full_early_stopped_trajectory_for_both_point_and_pgs"
        )
        assert trained.metadata["point_model_trimmed_to_validation_best"] is False
        assert (
            trained.metadata["inference_tree_count"]
            == trained.metadata["trained_tree_count"]
            == trained.estimator.tree_count_
        )
    prediction = predict_candidate(
        fitted, X_val, virtual_ensembles=config.virtual_ensembles
    )
    native_same_checkpoint = predict_native_point_from_posterior_checkpoint(
        fitted,
        X_val,
    )
    assert prediction.probabilities.shape == (len(y_val), 2)
    np.testing.assert_allclose(prediction.probabilities.sum(axis=1), 1.0, atol=1e-6)
    assert native_same_checkpoint.probabilities.shape == prediction.probabilities.shape
    assert native_same_checkpoint.probability_semantics == (
        "native_point_probability_from_same_posterior_sampling_checkpoint"
    )
    assert fitted.estimator.tree_count_ == fitted.metadata["inference_tree_count"]
    with pytest.raises(ValueError, match="posterior-sampling"):
        predict_native_point_from_posterior_checkpoint(point_fitted, X_val)


def test_late_fusion_weight_is_frozen_across_joblib_roundtrip(tmp_path: Path) -> None:
    config, _ = _tiny_protocol(tmp_path)
    candidate = CandidateConfig.from_dict(
        {
            "name": "late",
            "model": "late_fusion_catboost",
            "image_encoder": "tiny_image",
            "text_encoder": "tiny_text",
            "params": {"image_weight_grid": [0.25, 0.5, 0.75]},
        }
    )
    rng = np.random.default_rng(99)
    y_train = np.tile([0, 1], 20)
    y_val = np.tile([0, 1], 8)
    image_train = rng.normal(size=(len(y_train), 4)).astype("float32")
    text_train = rng.normal(size=(len(y_train), 3)).astype("float32")
    image_val = rng.normal(size=(len(y_val), 4)).astype("float32")
    text_val = rng.normal(size=(len(y_val), 3)).astype("float32")
    # Give each modality a real but imperfect signal.
    image_train[:, 0] += y_train * 1.5
    text_train[:, 0] += y_train * 1.0
    image_val[:, 0] += y_val * 1.5
    text_val[:, 0] += y_val * 1.0

    fitted = fit_candidate(
        config,
        candidate,
        42,
        (image_train, text_train),
        y_train,
        (image_val, text_val),
        y_val,
    )
    selected_weight = fitted.metadata["selected_image_weight"]
    assert selected_weight in {0.25, 0.5, 0.75}
    before = predict_candidate(fitted, (image_val, text_val), virtual_ensembles=3)
    checkpoint = save_fitted_model(fitted, tmp_path / "late_model")
    loaded = load_fitted_model(
        candidate,
        42,
        checkpoint,
        {
            "fit_seconds": fitted.fit_seconds,
            "model_metadata": fitted.metadata,
        },
    )
    assert loaded.estimator.image_weight == selected_weight
    after = predict_candidate(loaded, (image_val, text_val), virtual_ensembles=3)
    np.testing.assert_allclose(before.probabilities, after.probabilities, atol=1e-12)
