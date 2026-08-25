# CRM Multimodal Classifier - Model Card (Pre-release)

**Status:** research prototype. No journal-ready model version can be designated
until the locked group-temporal experiment is rerun from preserved artifacts.

## Intended use

Provide a ranked agency-group suggestion and confidence information for human
review when a citizen submits a non-emergency urban complaint in the evaluated
Jakarta context. The user or moderator must be able to correct or abstain.

## Out-of-scope use

- Emergency dispatch, policing, sanctions, eligibility, or other high-impact
  decisions.
- Fully automatic assignment without human review.
- Claims about cities, languages, channels, or time periods not evaluated.
- Treating the nearest seeded office as proof of administrative jurisdiction.

## Architecture under evaluation

- Frozen image encoder and frozen text encoder.
- Per-modality L2 normalisation and early concatenation.
- Five CatBoost multiclass heads trained with the preregistered seeds 13, 42,
  73, 101, and 137.
- Point and PGS candidates both retain the complete checkpoint trajectory
  produced by the same early-stopping rule. The point model is not uniquely
  shrunk to its best iteration; trained/inference tree counts are receipt-bound.
- Point-candidate versus PGS-candidate metrics estimate a bundled
  training+inference treatment, because their checkpoints were trained with
  different `posterior_sampling` settings. A separate preregistered
  inference-only ablation runs native point inference and `VirtEnsembles` on
  each identical posterior-trained checkpoint (same seed, hash, and tree count)
  and stores both per-sample probability vectors.
- Candidate selection, locked evaluation, and serving all use the equal
  arithmetic mean of the five seed-level class-probability vectors.
- The primary winner is selected only from the preregistered exportable
  CatBoost image+text subset. Unimodal, linear, random, TF-IDF, and late-fusion
  systems are secondary baselines/ablations, even if one tops the global
  validation leaderboard.
- A point candidate serves five ONNX heads. For a posterior-sampling candidate,
  each seed's native CatBoost virtual ensembles are averaged first and the five
  seed-level vectors are then averaged equally. The native and ONNX artifact for
  every seed remains receipt-bound and parity checked.
- PGS epistemic MI is defined over the joint `(training seed, virtual member)`
  mixture (`5 x 30 = 150` equal components), and therefore includes both
  within-seed PGS and between-training-seed dispersion.

## Evidence status

Legacy manuscript values (accuracy 0.8074, macro-F1 0.7747) were selected through
a protocol that accessed the test split and are therefore not release metrics.
They may be discussed only as exploratory historical results. The matched-checkpoint
analysis also does not support a claim that PGS improves top-1 performance.

The release model must link to an immutable experiment directory containing:

- input, split, configuration, environment, and model SHA-256 receipts;
- validation-only selection results across declared seeds;
- one-shot test probabilities and predictions;
- paired comparisons and uncertainty/calibration metrics;
- ONNX/native parity results and hardware-specific latency results.

## Required evaluation

Accuracy, macro-F1, balanced accuracy, per-class metrics, confusion matrix,
paired confidence intervals, NLL, Brier score, ECE, reliability data,
error-detection AUROC/AUPRC, risk-coverage/AURC, missing/noisy modality tests,
temporal validation, and preferably external-city validation.

## Human oversight and failure handling

Low confidence, high uncertainty, catch-all output, missing modality, disagreement
between modalities, and out-of-distribution inputs should trigger review rather
than automatic routing. Thresholds must be selected on validation data and stored
with the model; `0.70` is not a universal safety threshold. For PGS, the current
protocol selects a common marginal quantile so the conjunction of confidence and
MI gates reaches the validation target conditional on a routable predicted
label. It reports conditional joint coverage/risk and separate overall coverage
after unconditional catch-all review. It uses identity/no-post-hoc calibration and therefore makes no
calibrated-probability claim; top-label ECE uses 15 equal-width bins with a closed
final boundary. `Instansi lain` is unconditionally review-only.

## Fairness, privacy, and monitoring

Performance must be stratified by available non-sensitive operational dimensions
such as time, channel, geography, image availability, and text length. Do not infer
sensitive personal attributes. Logs must avoid raw narratives/images unless access
and retention are explicitly governed. Monitor drift, abstention, correction,
misrouting, and per-class harm after deployment.
