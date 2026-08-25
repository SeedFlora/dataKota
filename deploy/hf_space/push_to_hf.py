#!/usr/bin/env python3
"""Create the HF Space and upload source (model stays in a private repo).

Usage:
    HF_TOKEN=hf_xxx MODEL_REPO_REVISION=<commit> \
    MODEL_MANIFEST_SHA256=<sha256> \
    python deploy/hf_space/push_to_hf.py <user>/<space-name>

Run from the smartCityReport/ repo root.
"""

import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[2]  # smartCityReport/
HF_DIR = Path(__file__).resolve().parent  # deploy/hf_space/


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: push_to_hf.py <user>/<space-name>")
    repo_id = sys.argv[1]
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("set HF_TOKEN env var (write-access token)")
    model_revision = os.environ.get("MODEL_REPO_REVISION", "").strip()
    manifest_sha256 = os.environ.get("MODEL_MANIFEST_SHA256", "").strip()
    model_repo = os.environ.get("MODEL_REPO", "Keinnn1/crm-jakarta-models").strip()
    if len(model_revision) not in range(40, 65) or any(
        char not in "0123456789abcdefABCDEF" for char in model_revision
    ):
        sys.exit("MODEL_REPO_REVISION must be an exact 40-64 hex commit")
    if len(manifest_sha256) != 64 or any(
        char not in "0123456789abcdefABCDEF" for char in manifest_sha256
    ):
        sys.exit("MODEL_MANIFEST_SHA256 must be the exporter 64-hex digest")

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    print(f"[ok] space ready: https://huggingface.co/spaces/{repo_id}")
    for key, value in {
        "MODEL_REPO": model_repo,
        "MODEL_REPO_REVISION": model_revision.lower(),
        "MODEL_MANIFEST_SHA256": manifest_sha256.lower(),
    }.items():
        api.add_space_variable(repo_id=repo_id, key=key, value=value)
    print("[ok] pinned model repository revision and export manifest hash")

    # Root config files (from deploy/hf_space/ -> repo root)
    for name in ("Dockerfile", "requirements.txt", "README.md", ".gitattributes"):
        api.upload_file(
            path_or_fileobj=str(HF_DIR / name),
            path_in_repo=name,
            repo_id=repo_id,
            repo_type="space",
        )
    api.upload_file(
        path_or_fileobj=str(ROOT / "serve_model.py"),
        path_in_repo="serve_model.py",
        repo_id=repo_id,
        repo_type="space",
    )
    api.upload_file(
        path_or_fileobj=str(HF_DIR / "download_models.py"),
        path_in_repo="download_models.py",
        repo_id=repo_id,
        repo_type="space",
    )
    api.upload_file(
        path_or_fileobj=str(ROOT / "agencies_seed.json"),
        path_in_repo="agencies_seed.json",
        repo_id=repo_id,
        repo_type="space",
    )
    print("[ok] uploaded config, server, downloader, and agency registry")

    # Python package
    api.upload_folder(
        folder_path=str(ROOT / "src"),
        path_in_repo="src",
        repo_id=repo_id,
        repo_type="space",
        ignore_patterns=["**/__pycache__/**", "*.pyc"],
    )
    print("[ok] uploaded src/")

    # The Docker build downloads model artifacts from the private model repo via
    # its HF_TOKEN secret. Do not duplicate multi-GB weights in the public Space.
    print("[ok] source uploaded. Space will download private artifacts during build.")
    print("     add a read-only HF_TOKEN Space secret before rebuilding")
    print(f"     pantau build: https://huggingface.co/spaces/{repo_id}  (tab 'Logs')")


if __name__ == "__main__":
    main()
