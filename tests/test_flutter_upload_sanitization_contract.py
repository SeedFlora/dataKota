from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "smart_city_reporter_app"
SANITIZER = APP / "lib" / "core" / "security" / "image_upload_sanitizer.dart"
REPORTS = APP / "lib" / "features" / "reports" / "reports_repository.dart"
AUTH = APP / "lib" / "features" / "auth" / "auth_repository.dart"


def test_sanitizer_is_fail_closed_and_metadata_free_by_construction() -> None:
    source = SANITIZER.read_text(encoding="utf-8")
    for required in (
        "source.openRead()",
        "_validateByteCount(observedLength)",
        "_hasCompleteContainer(format, bytes)",
        "decoder.startDecode(bytes)",
        "info.numFrames != 1",
        "width * height > maxPixels",
        "img.bakeOrientation(decoded)",
        "numChannels: 3",
        "cleanRaster.exif.clear()",
        "cleanRaster.iccProfile = null",
        "cleanRaster.textData = null",
        "quality: jpegQuality",
        "extension: 'jpg'",
        "contentType: 'image/jpeg'",
    ):
        assert required in source
    assert "source.name" not in source
    assert "source.mimeType" not in source
    assert "img.findDecoderForData" not in source


def test_every_storage_upload_uses_sanitized_binary_and_derived_metadata() -> None:
    reports = REPORTS.read_text(encoding="utf-8")
    auth = AUTH.read_text(encoding="utf-8")

    assert reports.count("_imageSanitizer.sanitizeXFile(") == 2
    assert reports.count(".uploadBinary(") == 2
    assert auth.count("_imageSanitizer.sanitizeXFile(") == 1
    assert auth.count(".uploadBinary(") == 1
    assert "ImageUploadSanitizer.reportOutputByteLimit" in reports
    assert "ImageUploadSanitizer.profileOutputByteLimit" in auth
    assert "_uploadAndBindProfilePhoto" in auth
    assert ".remove([objectPath])" in auth
    for source in (reports, auth):
        assert ".upload(" not in source
        assert "import 'dart:io';" not in source
        assert re.search(r"\bFile\s*\(", source) is None
        assert "sanitized.extension" in source
        assert "contentType: sanitized.contentType" in source


def test_client_output_caps_match_private_bucket_limits() -> None:
    sanitizer = SANITIZER.read_text(encoding="utf-8")
    schema = (APP / "supabase" / "schema.sql").read_text(encoding="utf-8")
    assert "reportOutputByteLimit = 10 * 1024 * 1024" in sanitizer
    assert "profileOutputByteLimit = 5 * 1024 * 1024" in sanitizer
    assert "'report-images', 'report-images', false, 10485760" in schema
    assert "'profile-photos', 'profile-photos', false, 5242880" in schema


def test_image_codec_dependency_is_locked() -> None:
    pubspec = (APP / "pubspec.yaml").read_text(encoding="utf-8")
    lock = (APP / "pubspec.lock").read_text(encoding="utf-8")
    assert "image: ^4.9.2" in pubspec
    assert 'version: "4.9.2"' in lock
    assert "1976370a4df3091bb0f72409c187ad1f9132a818bc6b95ca59c0bae1c75c688e" in lock
