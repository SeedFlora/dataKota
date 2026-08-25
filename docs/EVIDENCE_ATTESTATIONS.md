# External evidence attestations

`tools/q2_readiness.py` deliberately separates reproducible software evidence
from reviews that code cannot manufacture. Store the latter as JSON files under
`artifacts/attestations/`; keep underlying sensitive records under controlled
access. An attestation is a receipt, not a substitute for the actual protocol or
an independent reviewer.

Every file has this common envelope:

```json
{
  "schema_version": 1,
  "evidence_type": "governance_review",
  "status": "complete",
  "reviewer_role": "institutional ethics or data-governance reviewer",
  "reviewer_name_or_registry_id": "institutional identifier (may be non-public)",
  "reviewer_affiliation": "reviewing institution",
  "reviewer_independent_of_model_selection": true,
  "reviewed_at_utc": "2026-08-25T00:00:00+00:00",
  "summary": "Concise, non-sensitive finding",
  "limitations": [],
  "controlled_evidence_reference": "internal protocol/document identifier",
  "split_manifest_sha256": "64 hex characters",
  "class_map_sha256": "64 hex characters",
  "protocol_digest": "64 hex characters",
  "experiment_receipt_sha256": "64 hex characters",
  "ordered_test_ids_sha256": "64 hex characters",
  "export_manifest_sha256": "external 64-hex deployment trust anchor",
  "evidence_files": [
    {"path": "relative/path/to/non-sensitive-review-output.pdf", "sha256": "64 hex characters"}
  ]
}
```

The checker opens every `evidence_files` record and recomputes its hash. Keep a
non-sensitive protocol/result summary in the evidence package even when raw
records remain under controlled access. A schema-complete attestation is not a
cryptographic signature and does not authenticate the reviewer.

Required type-specific fields:

- `governance_review.json`: `decision` is `approved`, `exempt`, or
  `not_required`, with a real `decision_reference` and `jurisdiction_basis`.
  Never invent an approval or exemption identifier.
- `visual_privacy_review.json`: positive integer `rows_reviewed`; describe the
  secure face, person, address, document, house-number, and license-plate
  procedure and list all six terms in `review_scope`. Set `coverage_mode` to
  `census` or `risk_based_sample` (the latter also requires `sampling_basis`).
  `reviewed_artifact_classes` must cover `dataset_images`, `manuscript_pdf`, and
  `supplementary_material`. Report non-negative integer
  `sensitive_findings_detected`, `sensitive_findings_resolved`, and
  `unresolved_sensitive_findings`; the counts must reconcile, unresolved must
  be zero, and `publication_outputs_cleared` must be true. Any detected and
  resolved finding also requires a controlled `remediation_reference`. Bind
  `dataset_image_manifest_sha256`, `manuscript_pdf_sha256`, and
  `supplementary_material_manifest_sha256` to verified `evidence_files` records
  with roles `dataset_image_manifest`, `final_manuscript_pdf`, and
  `supplementary_material_manifest`. Rebuilding any reviewed output invalidates
  the attestation until it is reviewed and hashed again.
- `routing_validation.json`: positive `sample_size`, positive
  `agency_reviewers`, `routing_correct`, and numeric
  `metrics.routing_accuracy` in `[0,1]`; the numerator must reproduce the rate.
- `external_validation.json`: positive `sample_size`, distinct `source_domain`
  and `development_domain`, and numeric `metrics.macro_f1` in `[0,1]`; no
  retuning on this set.
- `phase_b_later_cohort_validation.json`: a positive sample from the same
  declared task/source domain but a cohort whose start is strictly later than
  `development_data_max_utc`. It must attest that the cohort was unavailable
  during model development, unseen until the protocol freeze, accessed once
  after freeze, complete before unsealing, and never used for retuning. Record
  UTC development/cohort/freeze/unseal/evaluation timestamps, `access_count: 1`,
  `retuning_after_unseal: false`, numeric `metrics.macro_f1`, the selected release
  candidate/version, and the externally anchored export-manifest digest. The
  attestation must bind five independently hashed evidence roles:
  `phase_b_cohort_manifest`, `phase_b_cohort_membership`, `phase_b_access_log`,
  `frozen_analysis_plan`, and `phase_b_per_sample_predictions`. Record their
  digests in `cohort_manifest_sha256`, `cohort_membership_sha256`,
  `access_log_sha256`, `analysis_plan_sha256`, and `phase_b_results_sha256`.
  Also record lowercase SHA-256 values for the frozen Phase-A source snapshot in
  `development_source_snapshot_sha256` and the controlled Phase-B source snapshot
  in `phase_b_source_snapshot_sha256`.

  The membership CSV has exactly this ordered header, optionally followed by
  `leakage_group_id`:
  `sample_id,created_at_utc,source_row_sha256,source_snapshot_sha256`. Rows must
  be in prediction order; IDs must be unique; timestamps must be UTC; source-row
  digests must be unique lowercase SHA-256; and every row must bind the one
  declared Phase-B source snapshot. If `leakage_group_id` is present, it must be
  non-empty. Readiness recomputes the cohort minimum/maximum timestamps and
  ordered-ID digest, requires exact ID/order equality with the prediction CSV,
  rejects every Phase-A ID overlap, and rejects Phase-A leakage-group overlap
  when the optional group column is supplied. It also opens the hashed Phase-A
  source snapshot and split outputs: the source maximum must reproduce
  `split_manifest.time_range.max`, and the attested `development_data_max_utc`
  and `development_source_snapshot_sha256` must exactly match that frozen source.

  The hashed cohort manifest uses `schema_version: 2`; repeats cohort type,
  domains, development maximum, cohort start/end, `sample_count`, and
  `ordered_sample_ids_sha256`; binds `cohort_membership_sha256` and
  `phase_b_source_snapshot_sha256`; and declares
  `source_row_digest_algorithm: sha256_canonical_source_row_v1`. The prediction
  CSV contains unique ordered `sample_id`, integer `y_true`/`y_pred`, and all
  nine `prob_0`...`prob_8` columns. Readiness recomputes sample count,
  canonical-order argmax, probability validity, and nine-class macro-F1.

  `frozen_analysis_plan` uses `schema_version: 1`, `status: frozen`, and an exact
  `frozen_at_utc`. It cross-links the protocol, split manifest, Phase-A source,
  class map, experiment receipt, export manifest, and selected release. Its
  `cohort_policy` must lock same-domain strictly-later eligibility and the
  development maximum. Its `evaluation_policy` must lock one read-only access,
  no retuning, `macro_f1`, nine classes, the nine probability columns,
  `sample_id`, and `argmax_with_canonical_class_order_tie_break`.
  `phase_b_access_log` uses `schema_version: 1`, `access_count: 1`, cross-links
  the cohort manifest, membership, and analysis plan, and contains exactly one
  `access_events` entry. That event has `sequence: 1`, event type
  `phase_b_unseal_and_locked_evaluation_access`, scope `one_shot_read_only`, a
  non-empty `actor_role`, the frozen protocol/release, and an `accessed_at_utc`
  exactly equal to `phase_b_unsealed_at_utc` within the cohort-end/evaluation
  window. Hash-only or self-declared timestamp evidence does not satisfy this
  gate. This remains separate from different-domain external validation and is
  the only gate that can support a Phase-B confirmatory performance claim.
- `usability_validation.json`: `standard_sus_items: 10`, positive
  `participants`, both `citizen` and `agency_operator` in
  `participant_groups`, plus `task_success`, `completion_time`, `error_rate`,
  and numeric `correction_rate` in `task_metrics`, plus
  `completion_time_unit`.
- `latency_benchmark.json`: `hardware`, at least 100 measured samples, and
  `cold_start`, `p50`, `p95`, `p99`, `throughput`, and `peak_memory` in
  `metrics`. State units, batch size, warm-up, and whether network time is
  included; all metric values must be finite and nonnegative, with `units`,
  `batch_size`, and `warmup_runs`.
- `supabase_runtime_security_validation.json`: a receipt from an isolated live
  Supabase integration run with the trusted attestation worker, trusted
  server-side upload sanitizer, and exact release allowlist enabled. The
  sanitizer must decode and re-encode bytes before a service credential writes
  them; a Dart-only sanitizer does not satisfy this gate. Identify the
  runner/version and migration-bundle SHA-256; cover direct malicious
  Storage-upload bypass attempts, both citizen roles, two differently scoped
  agency operators, super admin, and service-role worker. All RLS,
  private-storage, trusted-upload sanitization, RPC privilege,
  lifecycle, allowlist, probability, review, and assignment checks must pass,
  with at least the 18 negative and nine positive cases in
  `smart_city_reporter_app/supabase/SECURITY_TEST_PROTOCOL.md`. Include a
  non-four-decimal confidence round trip whose stored score equals both the
  supplied score and stored winning probability within `1e-12`. Evidence must
  explicitly state that it contains no credentials.
- `end_to_end_raw_pipeline_parity.json`: `raw_input_end_to_end: true`, positive
  `sample_count`, components `image`, `text`, and `classifier`, plus numeric
  maximum probability error and top-1 agreement. Require `passed: true`,
  `tolerance_source: frozen_export_manifest`, a `tolerance_manifest_sha256`
  equal to the bound export manifest, and `frozen_tolerances` containing the
  exact manifest policy: maximum absolute probability error `1e-5` and minimum
  top-1 agreement `1.0`. Observations must satisfy both frozen limits; a looser
  attestation-authored policy fails. Tensor-boundary encoder parity reports do
  not satisfy this separate gate.

Run the release audit only after the immutable experiment and parity reports
exist:

```bash
python tools/q2_readiness.py \
  --experiment-run artifacts/q2_experiments/<experiment>/<run> \
  --export-dir artifacts/export-q2-001 \
  --export-manifest-sha256 <externally-stored-64-hex-digest> \
  --encoder-parity artifacts/parity/image_encoder_report.json \
  --encoder-parity artifacts/parity/text_encoder_report.json \
  --output artifacts/q2_readiness.json
```

Exit code `0` means the declared evidence package is schema-complete and its
hash crosslinks passed every machine-readable gate. Exit code `2` means at least
one required item remains missing or invalid. The command cannot authenticate a
reviewer, validate the scientific content independently, or predict editorial
acceptance.
