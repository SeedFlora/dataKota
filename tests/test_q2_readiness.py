from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "q2_readiness", ROOT / "tools" / "q2_readiness.py"
)
assert SPEC and SPEC.loader
q2_readiness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = q2_readiness
SPEC.loader.exec_module(q2_readiness)


def test_missing_evidence_fails_closed(tmp_path: Path) -> None:
    result = q2_readiness.main(
        [
            "--split-manifest",
            str(tmp_path / "missing-split.json"),
            "--label-audit",
            str(tmp_path / "missing-label.json"),
            "--privacy-audit",
            str(tmp_path / "missing-privacy.json"),
            "--classifier-parity",
            str(tmp_path / "missing-parity.json"),
            "--attestation-dir",
            str(tmp_path / "missing-attestations"),
        ]
    )
    assert result == 2


def test_public_label_audit_rejects_raw_disagreement_ids(tmp_path: Path) -> None:
    report = {
        "target_classes": [f"class_{index}" for index in range(9)],
        "sampling_design": "stratified_without_replacement",
        "sample_receipt_sha256": "a" * 64,
        "sample_content_sha256": "b" * 64,
        "independent_annotation_attested": True,
        "test_label_release_authority": {
            "authorization_mode": "post_locked_test_completion",
            "sha256": "c" * 64,
            "authorized_at_utc": "2026-08-25T00:00:00+00:00",
        },
        "annotators": [
            {
                "total_rows": 9,
                "scored_rows": 9,
                "micro_approx_stratified_95": [0.5, 1.0],
                "annotator_role": "domain reviewer A",
                "per_class": {f"class_{index}": {} for index in range(9)},
            },
            {
                "total_rows": 9,
                "scored_rows": 9,
                "micro_approx_stratified_95": [0.5, 1.0],
                "annotator_role": "domain reviewer B",
                "per_class": {f"class_{index}": {} for index in range(9)},
            },
        ],
        "inter_annotator": {
            "paired_scored": 9,
            "observed_agreement": 0.9,
            "cohen_kappa": 0.7,
            "resolved_label_exact_agreement": 0.8,
            "resolved_label_mean_jaccard": 0.85,
            "disagreement_row_ids": ["sensitive-row-id"],
        },
    }
    path = tmp_path / "label.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    gate = q2_readiness._check_label_audit(path)
    assert gate.passed is False
    assert "raw disagreement IDs" in gate.detail


def test_attestation_rejects_out_of_range_metric_even_with_valid_hashes(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "routing_summary.json"
    evidence.write_text("{}\n", encoding="utf-8")
    digest = q2_readiness._sha256(evidence)
    bindings = {
        "split_manifest_sha256": "a" * 64,
        "class_map_sha256": "b" * 64,
        "protocol_digest": "c" * 64,
        "experiment_receipt_sha256": "d" * 64,
        "ordered_test_ids_sha256": "e" * 64,
    }
    report = {
        "schema_version": 1,
        "evidence_type": "routing_validation",
        "status": "complete",
        "reviewer_role": "agency domain reviewer",
        "reviewer_name_or_registry_id": "reviewer-001",
        "reviewer_affiliation": "independent agency",
        "reviewer_independent_of_model_selection": True,
        "reviewed_at_utc": "2026-08-25T00:00:00+00:00",
        "evidence_files": [{"path": evidence.name, "sha256": digest}],
        "sample_size": 10,
        "agency_reviewers": 1,
        "routing_correct": 5,
        "metrics": {"routing_accuracy": -0.5},
        **bindings,
    }
    path = tmp_path / "routing_validation.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    gate = q2_readiness._check_attestation(
        path, "routing_validation", expected_bindings=bindings
    )
    assert gate.passed is False
    assert "valid range" in gate.detail


def _valid_visual_privacy_payload() -> dict[str, object]:
    return {
        "rows_reviewed": 100,
        "review_scope": [
            "faces",
            "people",
            "addresses",
            "documents",
            "house_numbers",
            "license_plates",
        ],
        "coverage_mode": "census",
        "reviewed_artifact_classes": [
            "dataset_images",
            "manuscript_pdf",
            "supplementary_material",
        ],
        "sensitive_findings_detected": 2,
        "sensitive_findings_resolved": 2,
        "unresolved_sensitive_findings": 0,
        "publication_outputs_cleared": True,
        "remediation_reference": "controlled-review-001",
        "dataset_image_manifest_sha256": "d" * 64,
        "manuscript_pdf_sha256": "e" * 64,
        "supplementary_material_manifest_sha256": "f" * 64,
        "evidence_files": [
            {
                "role": "dataset_image_manifest",
                "path": "dataset_images.json",
                "sha256": "d" * 64,
            },
            {
                "role": "final_manuscript_pdf",
                "path": "manuscript.pdf",
                "sha256": "e" * 64,
            },
            {
                "role": "supplementary_material_manifest",
                "path": "supplement.json",
                "sha256": "f" * 64,
            },
        ],
    }


def test_visual_privacy_attestation_requires_zero_unresolved_findings() -> None:
    payload = _valid_visual_privacy_payload()
    payload["sensitive_findings_resolved"] = 1
    payload["unresolved_sensitive_findings"] = 1

    try:
        q2_readiness._validate_visual_privacy(payload)
    except ValueError as exc:
        assert "unresolved sensitive findings" in str(exc)
    else:
        raise AssertionError("privacy attestation accepted an unresolved finding")


def test_visual_privacy_attestation_accepts_reconciled_cleared_review() -> None:
    q2_readiness._validate_visual_privacy(_valid_visual_privacy_payload())


def test_visual_privacy_attestation_rejects_changed_manuscript_digest() -> None:
    payload = _valid_visual_privacy_payload()
    payload["manuscript_pdf_sha256"] = "0" * 64

    try:
        q2_readiness._validate_visual_privacy(payload)
    except ValueError as exc:
        assert "not cross-linked" in str(exc)
    else:
        raise AssertionError("privacy review accepted an unreviewed manuscript hash")


def _valid_phase_b_payload() -> dict[str, object]:
    return {
        "sample_size": 500,
        "cohort_type": "strictly_later_same_domain",
        "development_domain": "jakarta_crm",
        "phase_b_domain": "jakarta_crm",
        "unavailable_during_model_development": True,
        "unseen_until_protocol_freeze": True,
        "single_access_after_freeze": True,
        "retuning_after_unseal": False,
        "access_count": 1,
        "development_data_max_utc": "2026-01-31T23:59:59+00:00",
        "phase_b_cohort_start_utc": "2026-02-01T00:00:00+00:00",
        "phase_b_cohort_end_utc": "2026-03-31T23:59:59+00:00",
        "protocol_frozen_at_utc": "2026-02-15T00:00:00+00:00",
        "phase_b_unsealed_at_utc": "2026-04-01T00:00:00+00:00",
        "evaluated_at_utc": "2026-04-02T00:00:00+00:00",
        "cohort_manifest_sha256": "a" * 64,
        "cohort_membership_sha256": "f" * 64,
        "access_log_sha256": "b" * 64,
        "analysis_plan_sha256": "c" * 64,
        "phase_b_results_sha256": "d" * 64,
        "phase_b_ordered_ids_sha256": "e" * 64,
        "development_source_snapshot_sha256": "8" * 64,
        "phase_b_source_snapshot_sha256": "9" * 64,
        "split_manifest_sha256": "1" * 64,
        "class_map_sha256": "2" * 64,
        "protocol_digest": "3" * 64,
        "experiment_receipt_sha256": "4" * 64,
        "ordered_test_ids_sha256": "5" * 64,
        "export_manifest_sha256": "6" * 64,
        "release_candidate": "selected_candidate",
        "release_model_version": "release-v1",
        "evidence_files": [
            {
                "role": "phase_b_cohort_manifest",
                "path": "phase_b_cohort_manifest.json",
                "sha256": "a" * 64,
            },
            {
                "role": "phase_b_cohort_membership",
                "path": "phase_b_cohort_membership.csv",
                "sha256": "f" * 64,
            },
            {
                "role": "phase_b_access_log",
                "path": "phase_b_access_log.json",
                "sha256": "b" * 64,
            },
            {
                "role": "frozen_analysis_plan",
                "path": "frozen_analysis_plan.json",
                "sha256": "c" * 64,
            },
            {
                "role": "phase_b_per_sample_predictions",
                "path": "phase_b_predictions.csv",
                "sha256": "d" * 64,
            },
        ],
        "metrics": {"macro_f1": 0.7},
    }


def test_phase_b_gate_rejects_relabelled_development_cohort() -> None:
    payload = _valid_phase_b_payload()
    payload["phase_b_cohort_start_utc"] = "2026-01-01T00:00:00+00:00"

    try:
        q2_readiness._validate_phase_b_later_cohort(payload)
    except ValueError as exc:
        assert "strictly later" in str(exc)
    else:
        raise AssertionError("Phase-B gate accepted a reused development cohort")


def test_phase_b_gate_accepts_one_shot_strictly_later_cohort() -> None:
    q2_readiness._validate_phase_b_later_cohort(_valid_phase_b_payload())


def test_phase_b_gate_rejects_digest_not_bound_to_named_evidence() -> None:
    payload = _valid_phase_b_payload()
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, list)
    evidence_files[0]["sha256"] = "d" * 64

    try:
        q2_readiness._validate_phase_b_later_cohort(payload)
    except ValueError as exc:
        assert "not cross-linked" in str(exc)
    else:
        raise AssertionError("Phase-B gate accepted an unrelated evidence digest")


def _phase_b_evidence_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], Path, Path, dict[str, Path]]:
    ids = [f"phase-b-{index}" for index in range(9)]
    header = ["sample_id", "y_true", "y_pred", *[f"prob_{i}" for i in range(9)]]
    lines = [",".join(header)]
    for index, sample_id in enumerate(ids):
        probabilities = ["1" if column == index else "0" for column in range(9)]
        lines.append(",".join([sample_id, str(index), str(index), *probabilities]))
    predictions = tmp_path / "phase_b_predictions.csv"
    predictions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = _valid_phase_b_payload()
    payload["sample_size"] = 9
    payload["metrics"] = {"macro_f1": 1.0}
    payload["phase_b_results_sha256"] = q2_readiness._sha256(predictions)
    payload["phase_b_ordered_ids_sha256"] = q2_readiness._object_sha256(ids)

    source = tmp_path / "phase_a_source.csv"
    source.write_text(
        "row_id,created_at\n"
        "phase-a-train,2026-01-01T00:00:00+00:00\n"
        "phase-a-val,2026-01-15T00:00:00+00:00\n"
        "phase-a-test,2026-01-31T23:59:59+00:00\n",
        encoding="utf-8",
    )
    outputs: dict[str, dict[str, object]] = {}
    for split, sample_id, created_at in (
        ("train", "phase-a-train", "2026-01-01T00:00:00+00:00"),
        ("val", "phase-a-val", "2026-01-15T00:00:00+00:00"),
        ("test", "phase-a-test", "2026-01-31T23:59:59+00:00"),
    ):
        split_path = tmp_path / f"{split}.csv"
        split_path.write_text(
            "row_id,created_at,leakage_group_id\n"
            f"{sample_id},{created_at},phase-a-{split}-group\n",
            encoding="utf-8",
        )
        outputs[split] = {
            "path": split_path.name,
            "sha256": q2_readiness._sha256(split_path),
        }
        if split != "test":
            outputs[split]["rows"] = 1
    split_manifest = tmp_path / "split_manifest.json"
    split_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "parameters": {
                    "id_column": "row_id",
                    "time_column": "created_at",
                },
                "time_column": "created_at",
                "time_range": {
                    "min": "2026-01-01T00:00:00+00:00",
                    "max": payload["development_data_max_utc"],
                },
                "source": {
                    "path": source.name,
                    "sha256": q2_readiness._sha256(source),
                    "rows": 3,
                },
                "outputs": outputs,
            }
        ),
        encoding="utf-8",
    )
    payload["split_manifest_sha256"] = q2_readiness._sha256(split_manifest)
    payload["development_source_snapshot_sha256"] = q2_readiness._sha256(source)

    membership = tmp_path / "phase_b_cohort_membership.csv"
    membership_timestamps = [
        "2026-02-01T00:00:00+00:00",
        *[f"2026-02-{day:02d}T00:00:00+00:00" for day in range(2, 9)],
        "2026-03-31T23:59:59+00:00",
    ]
    membership_lines = [
        (
            "sample_id,created_at_utc,source_row_sha256,source_snapshot_sha256,"
            "leakage_group_id"
        )
    ]
    for index, (sample_id, created_at) in enumerate(
        zip(ids, membership_timestamps, strict=True)
    ):
        membership_lines.append(
            ",".join(
                [
                    sample_id,
                    created_at,
                    f"{index + 16:064x}",
                    str(payload["phase_b_source_snapshot_sha256"]),
                    f"phase-b-group-{index}",
                ]
            )
        )
    membership.write_text("\n".join(membership_lines) + "\n", encoding="utf-8")
    payload["cohort_membership_sha256"] = q2_readiness._sha256(membership)

    cohort_manifest = tmp_path / "phase_b_cohort_manifest.json"
    cohort_manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "cohort_type": payload["cohort_type"],
                "development_domain": payload["development_domain"],
                "phase_b_domain": payload["phase_b_domain"],
                "development_data_max_utc": payload["development_data_max_utc"],
                "phase_b_cohort_start_utc": payload["phase_b_cohort_start_utc"],
                "phase_b_cohort_end_utc": payload["phase_b_cohort_end_utc"],
                "sample_count": len(ids),
                "ordered_sample_ids_sha256": payload["phase_b_ordered_ids_sha256"],
                "cohort_membership_sha256": payload["cohort_membership_sha256"],
                "phase_b_source_snapshot_sha256": payload[
                    "phase_b_source_snapshot_sha256"
                ],
                "source_row_digest_algorithm": "sha256_canonical_source_row_v1",
            }
        ),
        encoding="utf-8",
    )
    payload["cohort_manifest_sha256"] = q2_readiness._sha256(cohort_manifest)

    analysis_plan = tmp_path / "frozen_analysis_plan.json"
    analysis_plan.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "frozen",
                "frozen_at_utc": payload["protocol_frozen_at_utc"],
                "protocol_digest": payload["protocol_digest"],
                "split_manifest_sha256": payload["split_manifest_sha256"],
                "development_source_snapshot_sha256": payload[
                    "development_source_snapshot_sha256"
                ],
                "class_map_sha256": payload["class_map_sha256"],
                "experiment_receipt_sha256": payload["experiment_receipt_sha256"],
                "export_manifest_sha256": payload["export_manifest_sha256"],
                "release_candidate": payload["release_candidate"],
                "release_model_version": payload["release_model_version"],
                "cohort_policy": {
                    "cohort_type": payload["cohort_type"],
                    "development_domain": payload["development_domain"],
                    "phase_b_domain": payload["phase_b_domain"],
                    "development_data_max_utc": payload["development_data_max_utc"],
                    "require_strictly_later": True,
                    "require_same_domain": True,
                    "unavailable_during_model_development": True,
                    "unseen_until_protocol_freeze": True,
                },
                "evaluation_policy": {
                    "access_policy": "single_access_after_freeze",
                    "access_count": 1,
                    "retuning_after_unseal": False,
                    "primary_metric": "macro_f1",
                    "class_count": 9,
                    "probability_columns": [f"prob_{index}" for index in range(9)],
                    "prediction_rule": ("argmax_with_canonical_class_order_tie_break"),
                    "sample_unit": "sample_id",
                },
            }
        ),
        encoding="utf-8",
    )
    payload["analysis_plan_sha256"] = q2_readiness._sha256(analysis_plan)

    access_log = tmp_path / "phase_b_access_log.json"
    access_log.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "access_count": 1,
                "cohort_manifest_sha256": payload["cohort_manifest_sha256"],
                "cohort_membership_sha256": payload["cohort_membership_sha256"],
                "analysis_plan_sha256": payload["analysis_plan_sha256"],
                "access_events": [
                    {
                        "sequence": 1,
                        "event_type": ("phase_b_unseal_and_locked_evaluation_access"),
                        "access_scope": "one_shot_read_only",
                        "accessed_at_utc": payload["phase_b_unsealed_at_utc"],
                        "actor_role": "independent_evaluation_custodian",
                        "protocol_digest": payload["protocol_digest"],
                        "release_candidate": payload["release_candidate"],
                        "release_model_version": payload["release_model_version"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    payload["access_log_sha256"] = q2_readiness._sha256(access_log)

    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, list)
    paths = {
        "phase_b_per_sample_predictions": predictions,
        "phase_b_cohort_manifest": cohort_manifest,
        "phase_b_cohort_membership": membership,
        "phase_b_access_log": access_log,
        "frozen_analysis_plan": analysis_plan,
    }
    digest_fields = {
        "phase_b_per_sample_predictions": "phase_b_results_sha256",
        "phase_b_cohort_manifest": "cohort_manifest_sha256",
        "phase_b_cohort_membership": "cohort_membership_sha256",
        "phase_b_access_log": "access_log_sha256",
        "frozen_analysis_plan": "analysis_plan_sha256",
    }
    for record in evidence_files:
        role = str(record["role"])
        if role in paths:
            record["path"] = paths[role].name
            record["sha256"] = payload[digest_fields[role]]
    report_path = tmp_path / "phase_b_later_cohort_validation.json"
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload, report_path, split_manifest, paths


def _rehash_phase_b_fixture(
    payload: dict[str, object], report_path: Path, paths: dict[str, Path]
) -> None:
    membership = paths["phase_b_cohort_membership"]
    payload["cohort_membership_sha256"] = q2_readiness._sha256(membership)
    cohort_path = paths["phase_b_cohort_manifest"]
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    cohort["cohort_membership_sha256"] = payload["cohort_membership_sha256"]
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
    payload["cohort_manifest_sha256"] = q2_readiness._sha256(cohort_path)
    predictions = paths["phase_b_per_sample_predictions"]
    payload["phase_b_results_sha256"] = q2_readiness._sha256(predictions)
    plan_path = paths["frozen_analysis_plan"]
    payload["analysis_plan_sha256"] = q2_readiness._sha256(plan_path)
    access_path = paths["phase_b_access_log"]
    access_log = json.loads(access_path.read_text(encoding="utf-8"))
    access_log["cohort_manifest_sha256"] = payload["cohort_manifest_sha256"]
    access_log["cohort_membership_sha256"] = payload["cohort_membership_sha256"]
    access_log["analysis_plan_sha256"] = payload["analysis_plan_sha256"]
    access_path.write_text(json.dumps(access_log), encoding="utf-8")
    payload["access_log_sha256"] = q2_readiness._sha256(access_path)

    digest_fields = {
        "phase_b_per_sample_predictions": "phase_b_results_sha256",
        "phase_b_cohort_manifest": "cohort_manifest_sha256",
        "phase_b_cohort_membership": "cohort_membership_sha256",
        "phase_b_access_log": "access_log_sha256",
        "frozen_analysis_plan": "analysis_plan_sha256",
    }
    evidence_files = payload["evidence_files"]
    assert isinstance(evidence_files, list)
    for record in evidence_files:
        role = str(record["role"])
        if role in digest_fields:
            record["sha256"] = payload[digest_fields[role]]
    report_path.write_text(json.dumps(payload), encoding="utf-8")


def _phase_b_failure(
    payload: dict[str, object], report_path: Path, split_manifest: Path
) -> str:
    try:
        q2_readiness._recompute_phase_b_predictions(
            payload,
            report_path,
            phase_a_split_manifest_path=split_manifest,
        )
    except (TypeError, ValueError) as exc:
        return str(exc)
    raise AssertionError("Phase-B semantic gate accepted invalid evidence")


def test_phase_b_macro_f1_is_recomputed_from_hash_bound_predictions(
    tmp_path: Path,
) -> None:
    payload, report_path, split_manifest, _ = _phase_b_evidence_fixture(tmp_path)

    q2_readiness._recompute_phase_b_predictions(
        payload,
        report_path,
        phase_a_split_manifest_path=split_manifest,
    )
    payload["metrics"] = {"macro_f1": 0.5}
    assert "does not recompute" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_unrelated_hashed_cohort_manifest(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    cohort_manifest = paths["phase_b_cohort_manifest"]
    unrelated_manifest = json.loads(cohort_manifest.read_text(encoding="utf-8"))
    unrelated_manifest["sample_count"] = 10
    unrelated_manifest["ordered_sample_ids_sha256"] = q2_readiness._object_sha256(
        ["different-sample"]
    )
    cohort_manifest.write_text(json.dumps(unrelated_manifest), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "cohort manifest" in _phase_b_failure(payload, report_path, split_manifest)


def test_phase_b_rejects_probability_sum_outside_frozen_tolerance(
    tmp_path: Path,
) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    predictions = paths["phase_b_per_sample_predictions"]
    lines = predictions.read_text(encoding="utf-8").splitlines()
    first_row = lines[1].split(",")
    first_row[4] = "0.000005"
    lines[1] = ",".join(first_row)
    predictions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "class-map contract" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_membership_order_different_from_predictions(
    tmp_path: Path,
) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    membership = paths["phase_b_cohort_membership"]
    lines = membership.read_text(encoding="utf-8").splitlines()
    lines[1], lines[2] = lines[2], lines[1]
    membership.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "membership IDs/order" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_recomputes_membership_temporal_bounds(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    payload["phase_b_cohort_start_utc"] = "2026-02-02T00:00:00+00:00"
    cohort_path = paths["phase_b_cohort_manifest"]
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    cohort["phase_b_cohort_start_utc"] = payload["phase_b_cohort_start_utc"]
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "do not recompute" in _phase_b_failure(payload, report_path, split_manifest)


def test_phase_b_rejects_invalid_or_duplicate_source_row_digest(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    membership = paths["phase_b_cohort_membership"]
    lines = membership.read_text(encoding="utf-8").splitlines()
    first_digest = lines[1].split(",")[2]
    second_row = lines[2].split(",")
    second_row[2] = first_digest
    lines[2] = ",".join(second_row)
    membership.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "source-row digests" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_membership_source_snapshot_mismatch(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    membership = paths["phase_b_cohort_membership"]
    lines = membership.read_text(encoding="utf-8").splitlines()
    first_row = lines[1].split(",")
    first_row[3] = "7" * 64
    lines[1] = ",".join(first_row)
    membership.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "one declared source snapshot" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_development_max_must_equal_frozen_phase_a_source(
    tmp_path: Path,
) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    payload["development_data_max_utc"] = "2026-01-30T23:59:59+00:00"
    cohort_path = paths["phase_b_cohort_manifest"]
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    cohort["development_data_max_utc"] = payload["development_data_max_utc"]
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
    plan_path = paths["frozen_analysis_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["cohort_policy"]["development_data_max_utc"] = payload[
        "development_data_max_utc"
    ]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "development maximum differs" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_recomputes_phase_a_manifest_max_from_source(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    split = json.loads(split_manifest.read_text(encoding="utf-8"))
    split["time_range"]["max"] = "2026-01-30T23:59:59+00:00"
    split_manifest.write_text(json.dumps(split), encoding="utf-8")
    payload["split_manifest_sha256"] = q2_readiness._sha256(split_manifest)
    plan_path = paths["frozen_analysis_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["split_manifest_sha256"] = payload["split_manifest_sha256"]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "does not recompute" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_phase_a_sample_id_overlap(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    predictions = paths["phase_b_per_sample_predictions"]
    predictions.write_text(
        predictions.read_text(encoding="utf-8").replace(
            "phase-b-0,0,0", "phase-a-train,0,0"
        ),
        encoding="utf-8",
    )
    membership = paths["phase_b_cohort_membership"]
    membership.write_text(
        membership.read_text(encoding="utf-8").replace(
            "phase-b-0,", "phase-a-train,", 1
        ),
        encoding="utf-8",
    )
    ids = ["phase-a-train", *[f"phase-b-{index}" for index in range(1, 9)]]
    payload["phase_b_ordered_ids_sha256"] = q2_readiness._object_sha256(ids)
    cohort_path = paths["phase_b_cohort_manifest"]
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    cohort["ordered_sample_ids_sha256"] = payload["phase_b_ordered_ids_sha256"]
    cohort_path.write_text(json.dumps(cohort), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "sample IDs overlap" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_phase_a_leakage_group_overlap(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    membership = paths["phase_b_cohort_membership"]
    membership.write_text(
        membership.read_text(encoding="utf-8").replace(
            "phase-b-group-0", "phase-a-train-group", 1
        ),
        encoding="utf-8",
    )
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "leakage groups overlap" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_access_log_timestamp_lie(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    access_path = paths["phase_b_access_log"]
    access_log = json.loads(access_path.read_text(encoding="utf-8"))
    access_log["access_events"][0]["accessed_at_utc"] = "2026-04-01T00:00:01+00:00"
    access_path.write_text(json.dumps(access_log), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "access time differs" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_access_log_count_lie(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    access_path = paths["phase_b_access_log"]
    access_log = json.loads(access_path.read_text(encoding="utf-8"))
    access_log["access_count"] = 2
    access_path.write_text(json.dumps(access_log), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "access log access_count" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_unfrozen_analysis_plan_semantics(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    plan_path = paths["frozen_analysis_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["evaluation_policy"]["primary_metric"] = "accuracy"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "primary_metric is not locked" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def test_phase_b_rejects_analysis_plan_freeze_timestamp_lie(tmp_path: Path) -> None:
    payload, report_path, split_manifest, paths = _phase_b_evidence_fixture(tmp_path)
    plan_path = paths["frozen_analysis_plan"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["frozen_at_utc"] = "2026-02-15T00:00:01+00:00"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    _rehash_phase_b_fixture(payload, report_path, paths)
    assert "plan timestamp differs" in _phase_b_failure(
        payload, report_path, split_manifest
    )


def _valid_raw_parity_payload() -> dict[str, object]:
    export_digest = "9" * 64
    return {
        "raw_input_end_to_end": True,
        "sample_count": 50,
        "components": ["image", "text", "classifier"],
        "metrics": {
            "max_absolute_probability_error": 0.000001,
            "top1_agreement": 1.0,
        },
        "frozen_tolerances": {
            "max_absolute_probability_error": 0.00001,
            "minimum_top1_agreement": 1.0,
        },
        "tolerance_source": "frozen_export_manifest",
        "tolerance_manifest_sha256": export_digest,
        "export_manifest_sha256": export_digest,
        "passed": True,
    }


def test_raw_pipeline_parity_rejects_metrics_outside_frozen_tolerance() -> None:
    payload = _valid_raw_parity_payload()
    metrics = payload["metrics"]
    assert isinstance(metrics, dict)
    metrics["max_absolute_probability_error"] = 0.01

    try:
        q2_readiness._validate_raw_pipeline_parity(payload)
    except ValueError as exc:
        assert "violate frozen tolerances" in str(exc)
    else:
        raise AssertionError("raw parity accepted a failed numerical comparison")


def _valid_runtime_security_payload() -> dict[str, object]:
    return {
        "isolated_supabase_project": True,
        "attestation_worker_connected": True,
        "release_allowlist_enabled": True,
        "database_round_trip_completed": True,
        "trusted_upload_sanitizer_connected": True,
        "credential_material_in_evidence": False,
        "test_runner": "supabase-local-integration",
        "supabase_version": "evidence-bound-version",
        "migration_bundle_sha256": "a" * 64,
        "test_principals": [
            "citizen_a",
            "citizen_b",
            "agency_bm",
            "agency_sda",
            "super_admin",
            "service_role_worker",
        ],
        "checks": {
            "rls_read_isolation": True,
            "storage_owner_isolation": True,
            "trusted_upload_sanitization": True,
            "rpc_privilege_boundaries": True,
            "report_lifecycle": True,
            "release_allowlist": True,
            "probability_consistency": True,
            "review_gate_enforcement": True,
            "assignment_fail_closed": True,
            "confidence_precision_round_trip": True,
        },
        "test_counts": {"positive": 9, "negative": 18, "failed": 0},
        "confidence_round_trip": {
            "supplied": 0.823456,
            "stored": 0.823456,
            "stored_winning_probability": 0.823456,
            "absolute_error": 0.0,
        },
    }


def test_runtime_security_attestation_accepts_complete_live_receipt() -> None:
    q2_readiness._validate_supabase_runtime_security(_valid_runtime_security_payload())


def test_runtime_security_attestation_rejects_rounded_confidence() -> None:
    payload = _valid_runtime_security_payload()
    round_trip = payload["confidence_round_trip"]
    assert isinstance(round_trip, dict)
    round_trip["stored"] = 0.8235
    round_trip["absolute_error"] = 0.000044
    try:
        q2_readiness._validate_supabase_runtime_security(payload)
    except ValueError as exc:
        assert "did not survive" in str(exc)
    else:
        raise AssertionError("runtime security accepted rounded confidence evidence")


def test_raw_pipeline_parity_accepts_metrics_within_frozen_tolerance() -> None:
    q2_readiness._validate_raw_pipeline_parity(_valid_raw_parity_payload())


def test_raw_pipeline_parity_rejects_loosened_caller_authored_tolerance() -> None:
    payload = _valid_raw_parity_payload()
    tolerances = payload["frozen_tolerances"]
    assert isinstance(tolerances, dict)
    tolerances["max_absolute_probability_error"] = 0.1
    try:
        q2_readiness._validate_raw_pipeline_parity(payload)
    except ValueError as exc:
        assert "exact frozen export policy" in str(exc)
    else:
        raise AssertionError("raw parity accepted a caller-authored loose tolerance")


def test_classifier_component_parity_rejects_loosened_tolerance() -> None:
    report = {
        "p50_absolute_probability_error": 1e-7,
        "p95_absolute_probability_error": 2e-7,
        "p99_absolute_probability_error": 3e-7,
        "max_absolute_probability_error": 4e-7,
        "mean_absolute_probability_error": 2e-7,
        "top1_agreement": 1.0,
        "probability_tolerance": 1.0,
        "minimum_top1_agreement": 1.0,
        "passed": True,
    }
    try:
        q2_readiness._validate_classifier_parity_metrics(report, "test")
    except ValueError as exc:
        assert "frozen policy" in str(exc)
    else:
        raise AssertionError("classifier parity accepted a caller-loosened tolerance")


def test_encoder_component_parity_recomputes_frozen_gate() -> None:
    report = {
        "p50_absolute_error": 1e-6,
        "p95_absolute_error": 2e-6,
        "p99_absolute_error": 3e-6,
        "max_absolute_error": 2e-5,
        "mean_absolute_error": 2e-6,
        "minimum_row_cosine_similarity": 1.0,
        "absolute_tolerance": 1e-5,
        "minimum_cosine_similarity": 0.99999,
        "passed": True,
    }
    try:
        q2_readiness._validate_encoder_parity_metrics(report)
    except ValueError as exc:
        assert "violate the frozen policy" in str(exc)
    else:
        raise AssertionError("encoder parity trusted a stale passed flag")


def _encoder_lineage_fixture(tmp_path: Path):
    config = {
        "candidates": [
            {
                "name": "selected",
                "image_encoder": "image_v3",
                "text_encoder": "text_e5",
            }
        ]
    }
    selection = {"selected_candidate": "selected"}
    inputs = {"embeddings": {}}
    manifest = {
        "encoders": {},
        "runtime": {
            "image_model": "image_encoder/model.onnx",
            "text_model": "text_encoder/model.onnx",
        },
        "artifacts": [
            {"path": "image_encoder/model.onnx", "sha256": "1" * 64},
            {"path": "text_encoder/model.onnx", "sha256": "2" * 64},
        ],
    }
    report_paths = []
    for modality, name, component, digest in (
        ("image", "image_v3", "image_encoder", "1" * 64),
        ("text", "text_e5", "text_encoder", "2" * 64),
    ):
        preprocessing = {"contract": modality}
        provenance = {
            "encoder": {"repository": f"org/{name}", "revision": "a" * 40},
            "embedding_sha256": "b" * 64,
            "extraction_code_commit": "c" * 40,
            "preprocessing": preprocessing,
            "preprocessing_sha256": "d" * 64,
            "pooling": "cls" if modality == "image" else "e5_avg",
            "prefix": None if modality == "image" else "query: ",
            "max_length": None if modality == "image" else 256,
            "dimension": 3 if modality == "image" else 5,
            "dtype": "float32",
        }
        inputs["embeddings"][f"{modality}:{name}"] = {
            "path": str((tmp_path / f"{name}.npy").resolve()),
            "sha256": provenance["embedding_sha256"],
            "extraction_receipt": {
                "path": str((tmp_path / f"{name}.receipt.json").resolve()),
                "sha256": "e" * 64,
            },
            "provenance": provenance,
        }
        manifest["encoders"][modality] = {
            "name": name,
            "repository": provenance["encoder"]["repository"],
            "revision": provenance["encoder"]["revision"],
            "extraction_receipt_sha256": "e" * 64,
            "embedding_sha256": provenance["embedding_sha256"],
            "extraction_code_commit": provenance["extraction_code_commit"],
            "preprocessing": preprocessing,
            "preprocessing_sha256": provenance["preprocessing_sha256"],
            "pooling": provenance["pooling"],
            "prefix": provenance["prefix"],
            "max_length": provenance["max_length"],
            "dimension": provenance["dimension"],
            "dtype": provenance["dtype"],
        }
        contract = {
            "encoder_name": name,
            "encoder": provenance["encoder"],
            "extraction_code_commit": provenance["extraction_code_commit"],
            "preprocessing": preprocessing,
            "preprocessing_sha256": provenance["preprocessing_sha256"],
            "pooling": provenance["pooling"],
            "prefix": provenance["prefix"],
            "max_length": provenance["max_length"],
            "embedding_dtype": provenance["dtype"],
            "embedding_cache_sha256": provenance["embedding_sha256"],
            "embedding_extraction_receipt_sha256": "e" * 64,
        }
        contract_path = tmp_path / f"{modality}_contract.json"
        contract_path.write_text(json.dumps(contract), encoding="utf-8")
        report = {
            "component": component,
            "preprocessing_contract": contract_path.name,
            "onnx_component_sha256": {"model.onnx": digest},
        }
        report_path = tmp_path / f"{modality}_parity.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        report_paths.append(report_path)
    return manifest, inputs, config, selection, report_paths


def test_encoder_parity_rejects_wrong_selected_encoder(tmp_path: Path) -> None:
    manifest, inputs, config, selection, paths = _encoder_lineage_fixture(tmp_path)
    contract_path = tmp_path / "image_contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["encoder_name"] = "different_image_encoder"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    try:
        q2_readiness._validate_encoder_export_parity_lineage(
            manifest=manifest,
            inputs=inputs,
            config=config,
            selection=selection,
            encoder_parity_paths=paths,
        )
    except ValueError as exc:
        assert "selected encoder" in str(exc)
    else:
        raise AssertionError("parity for an unselected encoder was accepted")


def test_encoder_parity_rejects_wrong_exported_onnx_hash(tmp_path: Path) -> None:
    manifest, inputs, config, selection, paths = _encoder_lineage_fixture(tmp_path)
    report = json.loads(paths[0].read_text(encoding="utf-8"))
    report["onnx_component_sha256"]["model.onnx"] = "f" * 64
    paths[0].write_text(json.dumps(report), encoding="utf-8")
    try:
        q2_readiness._validate_encoder_export_parity_lineage(
            manifest=manifest,
            inputs=inputs,
            config=config,
            selection=selection,
            encoder_parity_paths=paths,
        )
    except ValueError as exc:
        assert "ONNX components" in str(exc)
    else:
        raise AssertionError("parity for different ONNX bytes was accepted")
