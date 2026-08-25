#!/usr/bin/env python3
"""Redeploy KODE ke Space (bukan model). Upload file yang berubah -> Space rebuild.

Model 7.4GB TIDAK ikut (sudah di repo private + di-cache di image layer SEBELUM
kode). Tiap run otomatis bump CACHEBUST di Dockerfile supaya layer kode selalu
rebuild bersih (hindari container stale), tapi layer download model tetap cached.

Usage:
    HF_TOKEN=hf_xxx python deploy/hf_space/redeploy.py
"""

import os
import re
import sys
import time
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]  # smartCityReport/
HF_DIR = Path(__file__).resolve().parent  # deploy/hf_space/
SPACE = os.environ.get("SPACE_ID", "Keinnn1/crm-jakarta")


def bump_cachebust() -> None:
    """Ganti nilai ARG CACHEBUST di Dockerfile dengan timestamp baru."""
    df = HF_DIR / "Dockerfile"
    txt = df.read_text()
    stamp = time.strftime("%Y%m%d%H%M%S")
    new = re.sub(r"ARG CACHEBUST=\S+", f"ARG CACHEBUST={stamp}", txt)
    df.write_text(new)
    print(f"[ok] CACHEBUST -> {stamp}")


def main() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("set HF_TOKEN env var (write-access token)")
    bump_cachebust()
    api = HfApi(token=token)

    for name in ("Dockerfile", "requirements.txt", "README.md", "download_models.py"):
        api.upload_file(
            path_or_fileobj=str(HF_DIR / name),
            path_in_repo=name,
            repo_id=SPACE,
            repo_type="space",
        )
    for name in ("serve_model.py", "agencies_seed.json"):
        api.upload_file(
            path_or_fileobj=str(ROOT / name),
            path_in_repo=name,
            repo_id=SPACE,
            repo_type="space",
        )
    api.upload_folder(
        folder_path=str(ROOT / "src"),
        path_in_repo="src",
        repo_id=SPACE,
        repo_type="space",
        ignore_patterns=["**/__pycache__/**", "*.pyc"],
    )
    print(f"[ok] redeployed -> https://huggingface.co/spaces/{SPACE} (rebuild jalan)")


if __name__ == "__main__":
    main()
