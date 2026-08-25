# Deployment and Export Release Protocol

This protocol prevents a convenient notebook export from being mistaken for
the model evaluated by the Q2 experiment.

## Release chain

1. Build the grouped strict-temporal split with a frozen
   `--split-preregistration`.
2. Run validation selection and the one-shot locked test with
   `tools/run_q2_experiment.py`.
3. Run `tools/export_q2_model.py` with
   `--policy locked_test_complete`. The selected candidate must be a multimodal
   CatBoost candidate from the config's preregistered
   `deployment_eligible_candidates` subset. Other evaluated systems are
   secondary baselines/ablations and cannot define the release, even if they top
   the global validation leaderboard. The exporter includes all five
   preregistered seed heads in their frozen order; it exposes no best-seed
   selector.
4. Store the printed `export_manifest.json` SHA-256 outside the bundle as
   `EXPORT_MANIFEST_SHA256`. Store the Hugging Face repository's exact commit as
   `MODEL_REPO_REVISION`.
5. Run classifier parity, image/text tensor-boundary parity, and the separate
   raw-image/raw-text end-to-end parity gate over every locked-test id. A tensor
   parity report explicitly has `raw_input_end_to_end=false` and cannot satisfy
   the end-to-end gate.
6. Run the release checker and do not promote the service while any required
   evidence gate is missing.

`selection_complete` export exists only for labelled development previews. The
server refuses it by default; `ALLOW_SELECTION_ONLY_EXPORT=true` is an explicit
non-release override and must not be used for a paper result or release.

## Startup invariants

Before loading model data, `serve_model.py` verifies the externally pinned
manifest hash, its semantic digest, every file size/hash, ordered class map,
model version assertion (when configured), encoder repositories and immutable
revisions, tokenizer/preprocessing assets, and encoder/classifier dimensions.
If CUDA is requested but unavailable or not activated, startup fails instead of
falling back to CPU silently.

The export manifest schema is version 4. Each encoder carries the exact
schema-version-1 modality preprocessing object and its semantic SHA-256 from the
schema-version-2 extraction receipt. The exporter and downloaded-bundle
validator require every non-model processor/tokenizer file to appear in that
object with the same hash; undeclared, missing, or substituted assets fail the
release. See docs/PREPROCESSING_PROVENANCE.md.

The manifest also freezes image-then-text concatenation, float32 output, and
per-modality L2 normalization with epsilon `1e-9`; the exporter refuses a run
trained with another fusion-normalization rule. Non-negotiable component
policies are encoder maximum absolute error `1e-5` plus minimum row cosine
similarity `0.99999`, and classifier maximum probability error `1e-5` plus
top-1 agreement `1.0`. Raw-input end-to-end parity separately requires maximum
probability error `1e-5` and top-1 agreement `1.0`. Caller-authored looser
tolerances fail the parity commands, bundle validation, runtime assertion, and
readiness audit.

The deployed prediction rule is the same rule used for validation selection and
locked evaluation: equal arithmetic mean of the five seed-level probability
vectors. Point and PGS candidates retain the full trajectory produced by their
shared early-stopping rule; the exporter verifies each native checkpoint against
its receipt-bound trained/inference tree count. This common checkpoint policy
does not by itself make separately trained point and posterior candidates an
inference-only ablation. The locked evidence package must additionally compare
native `predict_proba` and `VirtEnsembles` on each exact same posterior-trained
checkpoint (same hash, seed, and retained tree count); the release manifest is
not allowed to relabel a package comparison as an isolated PGS effect.
A selected point candidate serves all five ONNX heads. A selected
posterior-sampling candidate automatically serves all five manifested native
`.cbm` heads, requires at least `2 * V + 1` retained trees per head, and first
passes a configured `VirtEnsembles` smoke test plus native/ONNX point-probability
parity for every member and for their mean. The PGS probability is averaged
within each seed before applying the equal seed weights. Its epistemic statistic
is the joint training-seed + PGS component mutual information over all
`5 x 30 = 150` equally weighted `(seed, virtual-member)` components; it includes
between-training-seed dispersion rather than representing PGS-only within-seed
MI.

The signed manifest is the only source of confidence and (for PGS) epistemic-
review thresholds. For PGS, the two gates are fitted jointly: their common
marginal quantile is increased until the conjunction reaches the preregistered
validation target conditional on the predicted label being routable. Marginal
and joint conditional coverage/risk plus overall coverage after unconditional
catch-all review are archived. The resulting thresholds are applied unchanged; runtime environment
variables cannot replace them. The calibration block also records the explicit
identity/no-calibration family and exact top-label ECE bin semantics.

## Routing invariants

Only `SUPABASE_SERVICE_ROLE_KEY` (or the legacy server-side
`SUPABASE_SERVICE_KEY`) is considered authoritative. An anon key is never used
for routing. The registry must cover each of the eight routable agency labels
with an active, geocoded agency. The heterogeneous `Instansi lain` catch-all is
excluded from coverage, is always sent to human review, and can never produce an
automatic assignment. Missing routable coverage, database failure, or seed
fallback adds a review reason and suppresses automatic assignment. `/health` exposes only
sanitized states (`verified`, `incomplete`, `untrusted_fallback`, or
`unavailable`), not database error text.

`agencies_seed.json` is a development/display fallback. It is never an
authorization source for automatic dispatch.

## Container strategy

The GPU image uses CUDA 12.8 and cuDNN 9 for ONNX Runtime GPU 1.23.2. Local
artifacts remain outside the build context and are mounted read-only. The Hugging
Face Space downloads one private repository commit and verifies its pinned
manifest during the build. In both cases, the requested ONNX provider is asserted
again after session creation and reported by `/health`.
