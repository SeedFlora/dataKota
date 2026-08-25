# Trusted AI release registration

`attest_report_ai_evidence` fails closed until a database operator registers the
exact deployed export in `public.ai_model_releases`. The inference worker has
`EXECUTE` on the attestation RPC, but it has no table privileges on the release
allowlist. Do not grant those privileges to `service_role`.

## Operator procedure

1. Complete the locked export, raw-input encoder parity, classifier parity,
   release-manifest verification, and external hash anchoring.
2. Recompute the SHA-256 of `export_manifest.json` independently. Confirm that
   `class_map.semantic_sha256`, model identity, inference method, ordered nine
   labels, and validation-frozen review thresholds match the reviewed export.
3. In an operator-controlled migration, insert one row with literal values. Do
   not interpolate request data and do not use a mutable `latest` alias.
4. Keep `attestation_enabled=false` until deployment health reports the same
   hashes and all runtime integration tests pass, including a database
   round-trip with a non-four-decimal confidence whose stored value still
   equals the winning JSON probability within `1e-12`. Enable the row in a
   separate, reviewed transaction.
5. To revoke a release, set `attestation_enabled=false`; never reuse either
   digest for a different artifact.

Example shape (all angle-bracket values must be replaced and reviewed):

```sql
insert into public.ai_model_releases (
  export_manifest_sha256,
  class_map_sha256,
  model_name,
  model_version,
  inference_method,
  ordered_class_labels,
  confidence_threshold,
  uncertainty_method,
  epistemic_uncertainty_threshold,
  attestation_enabled
) values (
  '<64-hex export_manifest.json file SHA-256>',
  '<64-hex class-map semantic SHA-256>',
  '<immutable model name>',
  '<immutable model version>',
  'onnx_equal_weight_seed_ensemble',
  '["Dinas Bina Marga", "Satuan Polisi Pamong Praja", "Dinas Perhubungan", "Kelurahan", "Dinas Pertamanan dan Hutan", "Dinas Sumber Daya Air", "Dinas Cipta Karya, Tata Ruang, dan Pertanahan", "Badan Pembinaan Badan Usaha Milik Daerah", "Instansi lain"]'::jsonb,
  <validation-frozen minimum confidence>,
  null,
  null,
  false
);
```

For a PGS release, use
`catboost_virtual_ensemble_seed_ensemble`,
`joint_training_seed_pgs_component_mutual_information_nats`, and the
validation-frozen maximum joint training-seed/PGS-component epistemic mutual
information. Point-model releases must keep both uncertainty fields `null`.

## What the database revalidates per attestation

- exact enabled release identity and both digests;
- exactly the canonical nine probability keys, numeric values in `[0,1]`, and
  total probability within `1e-6` of one;
- confidence equals the maximum probability and the enum slug equals the
  deterministic class-order argmax;
- uncertainty method, threshold, completeness, non-negativity, and
  mutual-information identity;
- confidence, uncertainty, catch-all, registry, and user-override review gates;
- verified active agency/category consistency; and
- mandatory review when no complete assignment exists, and no assignment at all
  whenever any review gate is active.

The client submission RPC always stores AI fields as untrusted and cannot write
an assignment. A separately deployed worker must re-run or independently bind
the inference evidence before calling the attestation RPC. Pass the FastAPI
`predicted_category_slug` field as `p_prediction`; never forward the human
`predicted_dinas` display label into the enum-slug contract. Likewise, map the
assignment's explicit `agency_category_slug` to
`p_assigned_agency_category`; do not infer an enum from free-form agency text.
Until that worker and the database are tested together against a real Supabase
project, production auto-routing remains blocked.
