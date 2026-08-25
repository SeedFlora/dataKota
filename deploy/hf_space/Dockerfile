# Hugging Face Space (Docker SDK) — CRM Jakarta multimodal inference, CPU-only.
# Model weights live in a PRIVATE model repo (Keinnn1/crm-jakarta-models) and are
# downloaded at build time via the HF_TOKEN build secret, so they never live in
# this public Space repo.
FROM python:3.11-slim

# onnxruntime butuh libgomp (OpenMP runtime)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV HF_HOME=/tmp/hf_cache \
    PYTHONUNBUFFERED=1 \
    ORT_PROVIDER=CPUExecutionProvider

ARG MODEL_REPO=Keinnn1/crm-jakarta-models
ARG MODEL_REPO_REVISION
ARG MODEL_MANIFEST_SHA256
ENV MODEL_REPO=${MODEL_REPO} \
    MODEL_REPO_REVISION=${MODEL_REPO_REVISION} \
    MODEL_MANIFEST_SHA256=${MODEL_MANIFEST_SHA256} \
    EXPORT_MANIFEST_SHA256=${MODEL_MANIFEST_SHA256}

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download one pinned snapshot and validate the receipt-bound manifest before
# the build can continue. Source is copied first so the same validator is used
# by the downloader and the runtime server.
COPY src/ src/
COPY download_models.py .
RUN test -n "$MODEL_REPO_REVISION" && test -n "$MODEL_MANIFEST_SHA256"
RUN --mount=type=secret,id=HF_TOKEN,mode=0444,required=true \
    HF_TOKEN="$(cat /run/secrets/HF_TOKEN)" python download_models.py

# Cache-bust: bump nilai ini utk paksa rebuild layer kode TANPA re-download model.
ARG CACHEBUST=20260616162604
# Kode + master data instansi (layer paling akhir, sering berubah)
COPY serve_model.py agencies_seed.json ./

EXPOSE 7860
CMD ["uvicorn", "serve_model:app", "--host", "0.0.0.0", "--port", "7860"]
