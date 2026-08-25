# ONNX Runtime GPU 1.23.x uses CUDA 12.x and cuDNN 9.x. This image provides
# CUDA 12.8 plus cuDNN 9; requesting CUDA is asserted again by serve_model.py.
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04@sha256:ac55d124da4882b497f732d8dfd9a702d5447a5f29d08d56da6f64f0a1eb34bc

ARG EXPORT_MANIFEST_SHA256

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ORT_PROVIDER=CUDAExecutionProvider \
    EXPORT_MANIFEST_SHA256=${EXPORT_MANIFEST_SHA256}

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-dev python3-venv python-is-python3 \
      libgomp1 libglib2.0-0 libsm6 libxext6 libxrender1 zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

RUN test -n "$EXPORT_MANIFEST_SHA256" && \
    python -c "import re,os; assert re.fullmatch(r'[0-9a-fA-F]{64}', os.environ['EXPORT_MANIFEST_SHA256'])"

COPY requirements-serve.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-serve.txt && \
    pip uninstall -y onnxruntime && \
    pip install --no-cache-dir onnxruntime-gpu==1.23.2

COPY src/ ./src/
COPY serve_model.py agencies_seed.json ./

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "serve_model:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
