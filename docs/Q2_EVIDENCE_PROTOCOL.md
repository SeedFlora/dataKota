# Q2 Evidence Protocol

This file defines the evidence that must exist before numbers from this project
are copied into a journal submission. A checked box means that the referenced
artifact exists and has been independently reviewed; it is not a writing task.

## 1. Data provenance and governance

- [ ] Freeze the source snapshot and record its collection dates, source URLs,
  robots/terms review date, collector version, row count, and SHA-256 digest.
- [ ] Retain stable report id, timestamp, channel, latitude/longitude, original
  agency label, image path, and mapping version in the restricted master table.
- [ ] Document the lawful/ethical basis, access control, retention period,
  deletion process, and whether institutional ethics review or an exemption is
  required. Do not invent an approval number.
- [ ] Run `tools/privacy_audit.py`; then perform a separate pixel-level review for
  faces, people, addresses, house numbers, documents, and license plates. Cover
  dataset images, the rendered manuscript PDF, and every supplementary artifact;
  reconcile detected/resolved findings and release nothing while any sensitive
  finding remains unresolved. Regex and EXIF checks alone are insufficient.
- [ ] Publish only a de-identified derivative, stable ids/hashes, embeddings, or a
  controlled-access procedure approved by the data owner. Public availability is
  not required if it would violate privacy, but reproducibility boundaries must be
  explicit.

## 2. Label validity

- [ ] Preserve the complete 487-to-9 mapping and its versioned rationale.
- [ ] Before opening test labels for an audit, bind either an independent data-
  custodian authorization or the completed locked-test receipt in
  `--release-authority`. Then draw an exact stratified sample with
  `tools/label_audit.py sample`; the default is 450 records with at least 30 per
  class. Model selectors must not receive row-level audit material.
- [ ] Obtain two independent reviews from people familiar with Jakarta agency
  responsibilities. Annotation files must be completed independently before
  adjudication.
- [ ] Report micro and macro plausibility, per-class Wilson intervals, observed
  agreement, Cohen's kappa, disagreement count, adjudication policy, and the
  prevalence of reports that reasonably belong to multiple agencies.
- [ ] Treat `Instansi lain` as a heterogeneous catch-all and report it separately.
  Consider hierarchical or abstaining output rather than forcing every sample to
  an operational destination.

## 3. Leakage-resistant split

- [ ] Restore timestamps and stable ids before splitting.
- [ ] Freeze a `--split-preregistration` against the source hash before reading
  labels, with a custodian, rationale, attempt log, and exact cutoff/fraction
  policy. Run `tools/build_q2_splits.py` with explicit incident/user grouping
  columns when available. Missing/unreadable images fail the prespecified Phase-A build.
- [ ] Review the split manifest, boundary quarantine, largest clusters,
  multi-label clusters, class distributions, and hashes.
- [ ] The experiment runner must require `embedding_index`,
  `leakage_group_id`, and `created_at`; train/validation/test group ids must be
  disjoint and temporal order must be verified.
- [ ] Once model selection begins, do not change the locked test CSV or derive
  thresholds from it.

## 4. Model-selection and statistical analysis

- [ ] Select the candidate by validation macro-F1 computed from the equal-weight
  probability mean across every preregistered seed. Break an exact score tie by
  lower ensemble validation NLL, then smaller summed checkpoint size in bytes,
  then lexical candidate name. Apply this primary ranking only to the explicitly
  preregistered deployment-eligible CatBoost image+text subset. Keep all other
  evaluated candidates visible as secondary baselines/ablations, but do not let
  an unsupported winner create an experiment/export mismatch. Do not parse test
  labels during selection.
- [ ] Run at least five declared seeds with identical budgets. CatBoost point and
  posterior-sampling candidates must use the same maximum iterations, early
  stopping rule, evaluation metric, features, and seed. Retain the complete
  trajectory produced by that shared stopping rule for both treatments; never
  shrink only the point checkpoint to `best_iteration + 1`. Bind trained and
  inference tree counts in every selection-unit receipt.
- [ ] Keep two PGS estimands distinct. The ordinary point-candidate versus
  PGS-candidate row compares a complete training+inference package (a
  point-trained checkpoint versus a posterior-trained checkpoint followed by
  virtual-ensemble inference); name it a package comparison, not an isolated
  PGS inference effect. In addition, preregister and execute the mandatory
  inference-only ablation on every listed posterior checkpoint: compare native
  `predict_proba` against `VirtEnsembles` on the exact same loaded checkpoint,
  seed, SHA-256, and retained tree count. Archive both arms' per-sample
  probabilities and the paired interval/test output.
- [ ] Require schema-version-2 extraction receipts for every embedding cache.
  Validate the complete modality-specific preprocessing contract and semantic
  digest described in docs/PREPROCESSING_PROVENANCE.md: image decode,
  orientation, color, geometry, interpolation, normalization, layout and dtype;
  or text cleaning, exact prefix, tokenizer revision/assets, truncation, padding,
  pooling, normalization and dtype. Reject framework defaults that are not made
  explicit.
- [ ] Include a closest-predecessor-inspired 2024 Jakarta CRM DINOv2 +
  multilingual-E5 + CatBoost controlled baseline on the common split, with
  matched point and PGS variants. Do not call it a reconstruction or replication
  while the predecessor's original split, code, and per-sample protocol remain
  unavailable.
  Also include majority-class and stratified-random sanity checks,
  TF-IDF/linear, embedding linear probe, text-only, image-only, early fusion, and
  at least one late/gated or aligned VLM baseline.
- [ ] Form one primary prediction vector per candidate by taking the equal-weight
  arithmetic mean of probabilities across every preregistered seed. Store all
  per-seed and combined predictions. Freeze exactly 10,000 paired bootstrap
  replicates and seed `271828` in the selection receipt before opening the test
  set. Assign each complete `leakage_group_id` to the earliest UTC calendar month
  it contains and its row-count majority class (smallest class ID breaks a tie),
  then resample the original number of group IDs with replacement independently
  inside each month-by-majority-label stratum. Carry every row of each selected
  group and use identical draws for both systems. For the primary confidence
  interval, hold the deployed prediction vector fixed: average all
  preregistered seed probability tensors exactly once, apply deterministic
  argmax, and only resample whole clusters. Never average nonlinear macro-F1
  values from per-seed hard predictions. Separately run the preregistered 10,000-
  replicate training-seed sensitivity analysis, which additionally resamples the
  full seed list with replacement; label it as a hypothetical training-seed-
  superpopulation analysis, never as the confidence interval for the deployed
  five-head ensemble. Derive cluster and training-seed RNGs from independent
  `SeedSequence(bootstrap_seed).spawn(2)` children; reuse child 0 for the same
  cluster replicate sequence in both analyses and reserve child 1 for seed
  resampling. Archive the derivation/spawn keys, both exact algorithms, roles, RNG seeds, replicate
  counts, seed rules, stratum counts, cluster-to-stratum table, and its semantic
  digest in the immutable receipts. Labels/timestamps define the frozen design;
  model predictions and test scores must never tune it. Also run a cluster-valid
  paired accuracy test with frozen multiplicity correction; do not use row-level
  McNemar when reports inside a leakage group are dependent.
- [ ] Report accuracy, macro-F1, balanced accuracy, per-class precision/recall/F1,
  confusion matrix, and macro one-vs-rest ROC-AUC only when every class is present.
- [ ] Report NLL, multiclass Brier score, ECE with a declared binning rule,
  reliability data, error-detection AUROC/AUPRC, and risk-coverage/AURC.
- [ ] Call a method calibrated only if a held-out calibration evaluation supports
  that statement. A mean uncertainty value is not calibration evidence.
- [ ] The active protocol makes the honest identity/no-post-hoc-calibration choice
  and no calibrated-probability claim. It binds top-label ECE to 15 equal-width
  `[0,1]` bins (`[lower, upper)`, final upper boundary closed). Review thresholds
  are fitted on five-seed validation-ensemble uncertainty. For PGS, confidence
  and MI thresholds share a marginal quantile that is increased until their
  conjunction attains the fixed validation target among predictions whose label
  is routable. Archive the marginal rows, conditional joint coverage/risk, and
  separate overall coverage after unconditional catch-all review. PGS MI is the
  joint training-seed + virtual-member MI over `5 x 30 = 150` equally weighted
  components and includes between-training-seed dispersion. Freeze those thresholds in the selection
  receipt and apply them unchanged to locked evaluation and serving; never
  recompute an operating threshold on either.

## 5. Deployment and routing

- [ ] Export only with `tools/export_q2_model.py` from the frozen selected
  deployment-eligible CatBoost image+text candidate and every preregistered seed.
  The manifest and runtime must
  preserve their frozen order and average the five probability vectors with
  equal weight. Require the locked-test receipt for release, retain the external
  manifest SHA-256 trust anchor, and bind every checkpoint/unit receipt plus
  exact encoder repositories/revisions and every runtime artifact hash.
- [ ] Distinguish an ONNX point-probability seed ensemble from native CatBoost
  virtual-ensemble seed-ensemble inference in API metadata, model cards,
  figures, and manuscript text.
- [ ] Verify tensor-boundary encoder and classifier parity on the locked test
  data and separately verify the raw-image/raw-text end-to-end path. Store
  tolerances, maximum/percentile absolute error, label agreement, package
  versions, and input hashes. Encoder parity must reuse the exact preprocessing
  digest, extraction receipt, and locked-test cache rows of the selected
  candidate; its ONNX component hashes must equal the exported bytes. Classifier
  parity must deterministically reconstruct image-then-text fused features from
  those same caches and frozen L2 rule. The export freezes encoder
  tensor-boundary maximum absolute error `1e-5` and minimum row cosine
  similarity `0.99999`, classifier maximum probability error `1e-5` and top-1
  agreement `1.0`, and raw end-to-end maximum probability error `1e-5` and
  top-1 agreement `1.0`; a caller cannot loosen any of them. Do not claim PGS
  is exported to ONNX.
- [ ] Benchmark warm and cold latency, p50/p95/p99, throughput, memory, hardware,
  batch size, network inclusion, and sample count.
- [ ] Treat nearest-office output as a candidate recommendation until a signed or
  cited administrative-jurisdiction registry and stakeholder audit exist.
- [ ] Measure routing accuracy against agency-approved ground truth; straight-line
  distance is not a jurisdiction test.

## 6. Generalisation and human evaluation

- [ ] Evaluate a genuinely later/new Jakarta cohort that was never used for
  model selection, inspection, or prior reporting. Repartitioning the same
  61,773 rows can produce a leakage-resistant rerun but cannot restore a
  confirmatory untouched test claim. Archive a hash-bound
  `phase_b_later_cohort_validation.json` recording the development maximum date,
  later-cohort start/end, protocol freeze, one-time unsealing/access log, analysis
  plan, and explicit absence of post-unseal retuning. Include a hash-bound ordered
  membership CSV with `sample_id`, UTC `created_at_utc`, canonical source-row
  SHA-256, Phase-B source-snapshot SHA-256, and (when available)
  `leakage_group_id`; bind it to the schema-v2 cohort manifest. Readiness must
  recompute membership minimum/maximum and ordered-ID digest, require exact
  order equality with predictions, compare the development maximum and source
  digest against the hash-verified Phase-A source/split manifest, reject Phase-A
  ID overlap, and reject group overlap whenever the membership carries groups.
  The frozen analysis plan must semantically lock protocol, release, cohort,
  primary metric, class/probability order, access, and retuning rules before
  unsealing. The one-shot access log must contain exactly one parsed event whose
  timestamp equals the recorded unseal time; storing hashes without these
  semantic cross-checks is insufficient. Include hash-bound true/predicted labels
  and all nine probabilities, the exact class map and selected release linkage;
  readiness must recompute sample count, argmax and macro-F1. The Phase-A locked
  historical test gate and different-domain external validation do not satisfy
  this separate same-domain temporal requirement.
- [ ] Prefer an external city/platform evaluation. If access is unavailable,
  restrict the claim to the collected Jakarta period.
- [ ] Test missing image/text, blurred image, short/noisy text, mismatched
  modalities, channel shift, and open-set/catch-all behaviour.
- [ ] If usability remains in the paper, use a validated Indonesian 10-item SUS,
  report all item responses and scoring, and add task success, completion time,
  error/correction rate, and qualitative protocol. A modified 9-item score must
  not be compared directly with the standard SUS benchmark.
- [ ] Include citizens beyond the current student-heavy convenience sample and
  evaluate agency operators/moderators for the triage workflow.

## 7. Release gate

The submission may state only results present in an immutable run directory with
input manifest, resolved configuration, environment receipt, selection receipt,
one-shot test receipt, predictions, metrics, and checksums. Missing external
validation, ethics review, label audit, routing validation, or representative user
evidence must be described as a limitation, never converted into a positive claim.

Run the fail-closed audit with the exact versioned export and the manifest digest
stored outside that directory:

```bash
python tools/q2_readiness.py \
  --experiment-run artifacts/q2_experiments/<experiment>/<run> \
  --export-dir artifacts/export-q2-001 \
  --export-manifest-sha256 <external-64-hex-digest> \
  --encoder-parity artifacts/parity/image_encoder_report.json \
  --encoder-parity artifacts/parity/text_encoder_report.json \
  --output artifacts/q2_readiness.json
```

Exit code zero verifies machine-readable schema, files, hashes, and crosslinks.
It does not authenticate reviewers, establish scientific validity, or predict
editorial acceptance.
