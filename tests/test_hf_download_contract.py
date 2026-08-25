from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.test_export_contract import CLASSES, _bundle

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy" / "hf_space" / "download_models.py"
SPEC = importlib.util.spec_from_file_location("hf_download_contract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
download_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(download_models)


def test_hf_download_uses_exact_revision_and_validates_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    bundle, manifest_hash = _bundle(tmp_path)
    called = {}

    def fake_snapshot_download(**kwargs):
        called.update(kwargs)
        return str(bundle)

    monkeypatch.setattr(download_models, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(download_models, "TARGET_CLASSES", list(CLASSES))
    result = download_models.download_and_verify(
        repo_id="private/model",
        revision="a" * 40,
        manifest_sha256=manifest_hash,
        token="private-token",
        local_dir=tmp_path / "target",
    )
    assert result == bundle
    assert called["revision"] == "a" * 40
    assert called["repo_id"] == "private/model"
    assert called["token"] == "private-token"


def test_hf_download_rejects_mutable_revision_before_network(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        download_models,
        "snapshot_download",
        lambda **_kwargs: pytest.fail("network helper must not be called"),
    )
    with pytest.raises(RuntimeError, match="exact 40-64"):
        download_models.download_and_verify(
            repo_id="private/model",
            revision="main",
            manifest_sha256="a" * 64,
            token="private-token",
            local_dir=tmp_path / "target",
        )
