"""Download and verify one immutable private Hugging Face model snapshot.

Required environment variables:
  HF_TOKEN                    private-repository read token (build secret)
  MODEL_REPO_REVISION         exact 40-64 hex repository commit
  MODEL_MANIFEST_SHA256       trusted SHA-256 of export_manifest.json

The server repeats the complete manifest/artifact validation at startup.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT if (ROOT / "src").is_dir() else ROOT.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from crm import TARGET_CLASSES
from crm.export_contract import validate_export_manifest

_REVISION_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def download_and_verify(
    *,
    repo_id: str,
    revision: str,
    manifest_sha256: str,
    token: str,
    local_dir: Path,
) -> Path:
    if not _REVISION_RE.fullmatch(revision.lower()):
        raise RuntimeError(
            "MODEL_REPO_REVISION must be an exact 40-64 character hexadecimal commit"
        )
    if not _SHA256_RE.fullmatch(manifest_sha256.lower()):
        raise RuntimeError("MODEL_MANIFEST_SHA256 must be a 64-character SHA-256")
    if not token:
        raise RuntimeError("HF_TOKEN is required for the private model repository")
    snapshot_path = Path(
        snapshot_download(
            repo_id=repo_id,
            repo_type="model",
            revision=revision,
            local_dir=str(local_dir),
            token=token,
        )
    )
    validate_export_manifest(
        snapshot_path,
        expected_manifest_sha256=manifest_sha256.lower(),
        expected_classes=TARGET_CLASSES,
    )
    return snapshot_path


def main() -> int:
    repo_id = os.environ.get("MODEL_REPO", "Keinnn1/crm-jakarta-models").strip()
    revision = _required_env("MODEL_REPO_REVISION")
    manifest_sha256 = _required_env("MODEL_MANIFEST_SHA256")
    token = _required_env("HF_TOKEN")
    target = Path(os.environ.get("MODEL_LOCAL_DIR", "artifacts/export"))
    snapshot = download_and_verify(
        repo_id=repo_id,
        revision=revision,
        manifest_sha256=manifest_sha256,
        token=token,
        local_dir=target,
    )
    print(
        f"[ok] verified {repo_id}@{revision} manifest "
        f"{manifest_sha256.lower()} -> {snapshot}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
