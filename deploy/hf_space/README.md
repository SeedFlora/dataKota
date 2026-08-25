---
title: CRM Jakarta Multimodal Classifier
emoji: 🏙️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Early-fusion (DINOv3 + mE5) -> CatBoost dinas classifier
---

# CRM Jakarta — Multimodal Classifier (server-side inference)

FastAPI server untuk klasifikasi laporan CRM Jakarta (image + text -> early fusion ->
five receipt-bound CatBoost seed heads -> equal probability mean -> predicted
dinas). Point-candidate inference uses five ONNX Runtime sessions; a selected
posterior-sampling candidate uses the five manifested native heads.

## Endpoints
- `GET /health`
- `POST /predict` — multipart: `image` (file) + `laporan` (text) + optional `latitude`, `longitude`

Public URL: `https://<user>-<space>.hf.space` (HTTPS otomatis).

## Required pinned model settings

Configure these before a build:

- Secret `HF_TOKEN`: read access to the private model repository.
- Variable `MODEL_REPO`: repository id.
- Variable `MODEL_REPO_REVISION`: exact 40-64 hex commit, never `main` or a tag.
- Variable `MODEL_MANIFEST_SHA256`: digest printed by
  `tools/export_q2_model.py`.

The build fails if the revision is mutable, the manifest hash differs, any of
the five frozen classifier members is missing, or any manifested
model/tokenizer/preprocessing artifact has changed. The runtime repeats the same
validation and averages the five heads in their receipt-bound seed order.
`GET /health` exposes the verified seeds/member hashes, model/encoder revisions,
ONNX Runtime providers, and receipt digests.

The agency registry reload endpoint is disabled by default. Registry writes are
performed in Supabase by authorized administrators; applying them to the model
server is an operator/backend action. No reload secret is embedded in the
Flutter APK. If operational reload is needed, set `ENABLE_AGENCY_RELOAD=true`
and a server-only `AGENCY_RELOAD_TOKEN` of at least 32 characters.
