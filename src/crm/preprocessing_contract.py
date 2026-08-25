"""Versioned, modality-specific embedding preprocessing provenance.

The contract is deliberately stricter than a framework config dump. Framework
defaults can change between releases and do not capture upstream decoding or
text cleaning, so every behavior that can alter an embedding is explicit.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any

PREPROCESSING_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40,64}$")
_UNSET = object()


class PreprocessingContractError(ValueError):
    """Raised when preprocessing provenance is incomplete or ambiguous."""


def preprocessing_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreprocessingContractError(f"{name} must be an object")
    return value


def _exact_keys(
    value: Mapping[str, Any], name: str, required: set[str]
) -> Mapping[str, Any]:
    missing = sorted(required.difference(value))
    extra = sorted(set(value).difference(required))
    if missing or extra:
        raise PreprocessingContractError(
            f"{name} keys are not exact; missing={missing}, unexpected={extra}"
        )
    return value


def _nonempty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PreprocessingContractError(f"{name} must be a non-empty string")
    return value


def _exact_version(value: Any, name: str) -> str:
    version = _nonempty_string(value, name)
    if version.strip().lower() in {"latest", "main", "master", "unknown", "unpinned"}:
        raise PreprocessingContractError(f"{name} must be an exact installed version")
    return version


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise PreprocessingContractError(f"{name} must be boolean")
    return value


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value < 1:
        raise PreprocessingContractError(f"{name} must be a positive integer")
    return value


def _choice(value: Any, name: str, choices: set[str]) -> str:
    if value not in choices:
        raise PreprocessingContractError(
            f"{name} must be one of {sorted(choices)}, got {value!r}"
        )
    return str(value)


def _size(value: Any, name: str) -> tuple[int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) is not int or item < 1 for item in value)
    ):
        raise PreprocessingContractError(f"{name} must be [height, width]")
    return int(value[0]), int(value[1])


def _assets(value: Any, name: str, *, required: bool) -> None:
    if not isinstance(value, list) or (required and not value):
        qualifier = "a non-empty" if required else "an"
        raise PreprocessingContractError(f"{name} must be {qualifier} array")
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item_name = f"{name}[{index}]"
        item = _exact_keys(_object(raw, item_name), item_name, {"path", "sha256"})
        path = _nonempty_string(item["path"], f"{item_name}.path")
        posix = PurePosixPath(path)
        if posix.is_absolute() or ".." in posix.parts or "\\" in path or path in seen:
            raise PreprocessingContractError(
                f"{item_name}.path must be a unique safe relative POSIX path"
            )
        seen.add(path)
        digest = item["sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise PreprocessingContractError(
                f"{item_name}.sha256 must be lowercase SHA-256"
            )


def _implementation(value: Any, *, modality: str) -> None:
    name = "preprocessing.implementation"
    if modality == "image":
        fields = {
            "framework",
            "library",
            "library_version",
            "processor_class",
            "configuration_source",
            "processor_repository",
            "processor_revision",
            "assets",
        }
        item = _exact_keys(_object(value, name), name, fields)
        framework = _choice(
            item["framework"],
            f"{name}.framework",
            {"huggingface_transformers", "timm", "torchvision", "custom"},
        )
        library = _nonempty_string(item["library"], f"{name}.library")
        expected_library = {
            "huggingface_transformers": "transformers",
            "timm": "timm",
            "torchvision": "torchvision",
        }.get(framework)
        if expected_library is not None and library != expected_library:
            raise PreprocessingContractError(
                f"{name}.library must be {expected_library!r} for {framework}"
            )
        _exact_version(item["library_version"], f"{name}.library_version")
        _nonempty_string(item["processor_class"], f"{name}.processor_class")
        source = _choice(
            item["configuration_source"],
            f"{name}.configuration_source",
            {"repository_assets", "explicit_parameters"},
        )
        if source == "repository_assets":
            _nonempty_string(
                item["processor_repository"], f"{name}.processor_repository"
            )
            revision = item["processor_revision"]
            if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
                raise PreprocessingContractError(
                    f"{name}.processor_revision must be an immutable commit"
                )
            _assets(item["assets"], f"{name}.assets", required=True)
        else:
            if (
                item["processor_repository"] is not None
                or item["processor_revision"] is not None
            ):
                raise PreprocessingContractError(
                    f"{name} repository/revision must be null for explicit parameters"
                )
            _assets(item["assets"], f"{name}.assets", required=False)
        return

    fields = {
        "framework",
        "library",
        "library_version",
        "tokenizer_class",
        "tokenizer_repository",
        "tokenizer_revision",
        "assets",
    }
    item = _exact_keys(_object(value, name), name, fields)
    framework = _choice(
        item["framework"],
        f"{name}.framework",
        {"huggingface_transformers", "sentence_transformers", "custom"},
    )
    library = _nonempty_string(item["library"], f"{name}.library")
    expected_library = {
        "huggingface_transformers": "transformers",
        "sentence_transformers": "sentence-transformers",
    }.get(framework)
    if expected_library is not None and library != expected_library:
        raise PreprocessingContractError(
            f"{name}.library must be {expected_library!r} for {framework}"
        )
    _exact_version(item["library_version"], f"{name}.library_version")
    _nonempty_string(item["tokenizer_class"], f"{name}.tokenizer_class")
    _nonempty_string(item["tokenizer_repository"], f"{name}.tokenizer_repository")
    revision = item["tokenizer_revision"]
    if not isinstance(revision, str) or not _REVISION_RE.fullmatch(revision):
        raise PreprocessingContractError(
            f"{name}.tokenizer_revision must be an immutable commit"
        )
    _assets(item["assets"], f"{name}.assets", required=True)


def _validate_image(
    value: Mapping[str, Any], *, pooling: Any, output_dtype: Any
) -> None:
    decode = _exact_keys(
        _object(value["decode"], "preprocessing.decode"),
        "preprocessing.decode",
        {
            "backend",
            "backend_version",
            "exif_orientation",
            "color_mode",
            "alpha_channel_policy",
            "animated_image_policy",
            "missing_image_policy",
            "decode_error_policy",
        },
    )
    _nonempty_string(decode["backend"], "preprocessing.decode.backend")
    _exact_version(decode["backend_version"], "preprocessing.decode.backend_version")
    _choice(
        decode["exif_orientation"],
        "preprocessing.decode.exif_orientation",
        {"apply_exif_transpose", "ignore", "reject_if_orientation_present"},
    )
    color_mode = _choice(
        decode["color_mode"],
        "preprocessing.decode.color_mode",
        {"RGB", "RGBA", "L"},
    )
    _choice(
        decode["alpha_channel_policy"],
        "preprocessing.decode.alpha_channel_policy",
        {
            "drop_after_rgb_conversion",
            "composite_on_white",
            "composite_on_black",
            "reject",
            "not_applicable",
        },
    )
    _choice(
        decode["animated_image_policy"],
        "preprocessing.decode.animated_image_policy",
        {"first_frame", "reject"},
    )
    for field in ("missing_image_policy", "decode_error_policy"):
        if decode[field] != "fail":
            raise PreprocessingContractError(
                f"preprocessing.decode.{field} must be 'fail' for Q2 extraction"
            )

    geometry = _exact_keys(
        _object(value["geometry"], "preprocessing.geometry"),
        "preprocessing.geometry",
        {
            "resize_mode",
            "resize_size",
            "interpolation",
            "antialias",
            "preserve_aspect_ratio",
            "crop_mode",
            "crop_size",
        },
    )
    resize_mode = _choice(
        geometry["resize_mode"],
        "preprocessing.geometry.resize_mode",
        {"exact", "shortest_edge", "longest_edge", "none"},
    )
    if resize_mode == "exact":
        _size(geometry["resize_size"], "preprocessing.geometry.resize_size")
        if geometry["preserve_aspect_ratio"] is not False:
            raise PreprocessingContractError(
                "exact resize must set preserve_aspect_ratio=false"
            )
    elif resize_mode in {"shortest_edge", "longest_edge"}:
        _positive_int(geometry["resize_size"], "preprocessing.geometry.resize_size")
        if geometry["preserve_aspect_ratio"] is not True:
            raise PreprocessingContractError(
                f"{resize_mode} resize must set preserve_aspect_ratio=true"
            )
    elif (
        geometry["resize_size"] is not None
        or geometry["preserve_aspect_ratio"] is not False
    ):
        raise PreprocessingContractError(
            "no-resize must use resize_size=null and preserve_aspect_ratio=false"
        )
    interpolation_choices = (
        {"not_applicable"}
        if resize_mode == "none"
        else {"nearest", "bilinear", "bicubic", "lanczos", "area"}
    )
    _choice(
        geometry["interpolation"],
        "preprocessing.geometry.interpolation",
        interpolation_choices,
    )
    _boolean(geometry["antialias"], "preprocessing.geometry.antialias")
    crop_mode = _choice(
        geometry["crop_mode"],
        "preprocessing.geometry.crop_mode",
        {"none", "center"},
    )
    if crop_mode == "none":
        if geometry["crop_size"] is not None:
            raise PreprocessingContractError(
                "preprocessing.geometry.crop_size must be null when crop_mode=none"
            )
    else:
        _size(geometry["crop_size"], "preprocessing.geometry.crop_size")

    numeric = _exact_keys(
        _object(value["numeric"], "preprocessing.numeric"),
        "preprocessing.numeric",
        {
            "input_channel_order",
            "rescale_enabled",
            "rescale_factor",
            "normalize_enabled",
            "mean",
            "std",
            "tensor_layout",
            "tensor_dtype",
        },
    )
    if numeric["input_channel_order"] != color_mode:
        raise PreprocessingContractError(
            "numeric.input_channel_order must match decode.color_mode"
        )
    rescale = _boolean(
        numeric["rescale_enabled"], "preprocessing.numeric.rescale_enabled"
    )
    factor = numeric["rescale_factor"]
    if rescale:
        if (
            isinstance(factor, bool)
            or not isinstance(factor, (int, float))
            or not math.isfinite(float(factor))
            or float(factor) <= 0.0
        ):
            raise PreprocessingContractError(
                "preprocessing.numeric.rescale_factor must be finite and positive"
            )
    elif factor is not None:
        raise PreprocessingContractError(
            "rescale_factor must be null when rescale_enabled=false"
        )
    normalize = _boolean(
        numeric["normalize_enabled"], "preprocessing.numeric.normalize_enabled"
    )
    expected_channels = {"RGB": 3, "RGBA": 4, "L": 1}[color_mode]
    if normalize:
        for field in ("mean", "std"):
            values = numeric[field]
            if (
                not isinstance(values, list)
                or len(values) != expected_channels
                or any(
                    isinstance(item, bool)
                    or not isinstance(item, (int, float))
                    or not math.isfinite(float(item))
                    for item in values
                )
            ):
                raise PreprocessingContractError(
                    f"preprocessing.numeric.{field} must contain one finite value "
                    "per channel"
                )
        if any(float(item) <= 0.0 for item in numeric["std"]):
            raise PreprocessingContractError(
                "preprocessing.numeric.std values must be positive"
            )
    elif numeric["mean"] is not None or numeric["std"] is not None:
        raise PreprocessingContractError(
            "mean/std must be null when normalize_enabled=false"
        )
    _choice(
        numeric["tensor_layout"],
        "preprocessing.numeric.tensor_layout",
        {"NCHW", "NHWC"},
    )
    _choice(
        numeric["tensor_dtype"],
        "preprocessing.numeric.tensor_dtype",
        {"float16", "float32", "float64", "uint8"},
    )

    embedding = _exact_keys(
        _object(value["embedding"], "preprocessing.embedding"),
        "preprocessing.embedding",
        {"pooling", "l2_normalize", "output_dtype"},
    )
    embedded_pooling = _nonempty_string(
        embedding["pooling"], "preprocessing.embedding.pooling"
    )
    if pooling is not _UNSET and embedded_pooling != pooling:
        raise PreprocessingContractError(
            "preprocessing.embedding.pooling differs from receipt.pooling"
        )
    _boolean(embedding["l2_normalize"], "preprocessing.embedding.l2_normalize")
    embedded_dtype = _choice(
        embedding["output_dtype"],
        "preprocessing.embedding.output_dtype",
        {"float16", "float32", "float64"},
    )
    if output_dtype is not _UNSET and embedded_dtype != output_dtype:
        raise PreprocessingContractError(
            "preprocessing.embedding.output_dtype differs from receipt.dtype"
        )


def _validate_text(
    value: Mapping[str, Any],
    *,
    pooling: Any,
    prefix: Any,
    max_length: Any,
    output_dtype: Any,
) -> None:
    cleaning = _exact_keys(
        _object(value["cleaning"], "preprocessing.cleaning"),
        "preprocessing.cleaning",
        {
            "input_encoding",
            "unicode_normalization",
            "strip",
            "collapse_whitespace",
            "lowercase",
            "newline_policy",
            "html_policy",
            "url_policy",
            "mention_policy",
            "control_character_policy",
            "empty_text_policy",
        },
    )
    if cleaning["input_encoding"] != "utf-8":
        raise PreprocessingContractError(
            "preprocessing.cleaning.input_encoding must be 'utf-8'"
        )
    _choice(
        cleaning["unicode_normalization"],
        "preprocessing.cleaning.unicode_normalization",
        {"none", "NFC", "NFKC", "NFD", "NFKD"},
    )
    for field in ("strip", "collapse_whitespace", "lowercase"):
        _boolean(cleaning[field], f"preprocessing.cleaning.{field}")
    _choice(
        cleaning["newline_policy"],
        "preprocessing.cleaning.newline_policy",
        {"preserve", "replace_with_space", "strip"},
    )
    for field in ("html_policy", "url_policy", "mention_policy"):
        _choice(
            cleaning[field],
            f"preprocessing.cleaning.{field}",
            {"preserve", "strip", "replace_with_token"},
        )
    _choice(
        cleaning["control_character_policy"],
        "preprocessing.cleaning.control_character_policy",
        {"preserve", "strip", "reject"},
    )
    _choice(
        cleaning["empty_text_policy"],
        "preprocessing.cleaning.empty_text_policy",
        {"allow", "reject"},
    )

    tokenization = _exact_keys(
        _object(value["tokenization"], "preprocessing.tokenization"),
        "preprocessing.tokenization",
        {
            "prefix",
            "add_special_tokens",
            "truncation",
            "truncation_side",
            "max_length",
            "padding",
            "padding_side",
            "pad_to_multiple_of",
            "return_attention_mask",
            "return_token_type_ids",
        },
    )
    if not isinstance(tokenization["prefix"], str):
        raise PreprocessingContractError(
            "preprocessing.tokenization.prefix must be a string"
        )
    if prefix is not _UNSET and tokenization["prefix"] != prefix:
        raise PreprocessingContractError(
            "preprocessing.tokenization.prefix differs from receipt.prefix"
        )
    for field in ("add_special_tokens", "truncation", "return_attention_mask"):
        _boolean(tokenization[field], f"preprocessing.tokenization.{field}")
    _choice(
        tokenization["truncation_side"],
        "preprocessing.tokenization.truncation_side",
        {"left", "right"},
    )
    token_max_length = _positive_int(
        tokenization["max_length"], "preprocessing.tokenization.max_length"
    )
    if max_length is not _UNSET and token_max_length != max_length:
        raise PreprocessingContractError(
            "preprocessing.tokenization.max_length differs from receipt.max_length"
        )
    _choice(
        tokenization["padding"],
        "preprocessing.tokenization.padding",
        {"longest", "max_length", "do_not_pad"},
    )
    _choice(
        tokenization["padding_side"],
        "preprocessing.tokenization.padding_side",
        {"left", "right"},
    )
    pad_multiple = tokenization["pad_to_multiple_of"]
    if pad_multiple is not None:
        _positive_int(pad_multiple, "preprocessing.tokenization.pad_to_multiple_of")
    _choice(
        tokenization["return_token_type_ids"],
        "preprocessing.tokenization.return_token_type_ids",
        {"auto", "include", "omit"},
    )

    embedding = _exact_keys(
        _object(value["embedding"], "preprocessing.embedding"),
        "preprocessing.embedding",
        {"pooling", "pooling_detail", "l2_normalize", "output_dtype"},
    )
    embedded_pooling = _choice(
        embedding["pooling"],
        "preprocessing.embedding.pooling",
        {"cls", "mean", "e5_avg"},
    )
    expected_detail = (
        "first_token" if embedded_pooling == "cls" else "attention_mask_weighted_mean"
    )
    if embedding["pooling_detail"] != expected_detail:
        raise PreprocessingContractError(
            "preprocessing.embedding.pooling_detail is inconsistent with pooling"
        )
    if pooling is not _UNSET and embedded_pooling != pooling:
        raise PreprocessingContractError(
            "preprocessing.embedding.pooling differs from receipt.pooling"
        )
    _boolean(embedding["l2_normalize"], "preprocessing.embedding.l2_normalize")
    embedded_dtype = _choice(
        embedding["output_dtype"],
        "preprocessing.embedding.output_dtype",
        {"float16", "float32", "float64"},
    )
    if output_dtype is not _UNSET and embedded_dtype != output_dtype:
        raise PreprocessingContractError(
            "preprocessing.embedding.output_dtype differs from receipt.dtype"
        )


def validate_preprocessing_contract(
    value: Any,
    *,
    modality: str,
    pooling: Any = _UNSET,
    prefix: Any = _UNSET,
    max_length: Any = _UNSET,
    output_dtype: Any = _UNSET,
) -> Mapping[str, Any]:
    """Validate and return a complete JSON-compatible preprocessing contract."""
    if modality not in {"image", "text"}:
        raise PreprocessingContractError(f"unsupported modality {modality!r}")
    required = (
        {
            "schema_version",
            "modality",
            "implementation",
            "decode",
            "geometry",
            "numeric",
            "embedding",
        }
        if modality == "image"
        else {
            "schema_version",
            "modality",
            "implementation",
            "cleaning",
            "tokenization",
            "embedding",
        }
    )
    contract = _exact_keys(_object(value, "preprocessing"), "preprocessing", required)
    if contract["schema_version"] != PREPROCESSING_SCHEMA_VERSION:
        raise PreprocessingContractError(
            f"preprocessing.schema_version must be {PREPROCESSING_SCHEMA_VERSION}"
        )
    if contract["modality"] != modality:
        raise PreprocessingContractError(f"preprocessing.modality must be {modality!r}")
    _implementation(contract["implementation"], modality=modality)
    if modality == "image":
        if prefix not in {_UNSET, None} or max_length not in {_UNSET, None}:
            raise PreprocessingContractError(
                "image receipt prefix/max_length must be null"
            )
        _validate_image(contract, pooling=pooling, output_dtype=output_dtype)
    else:
        _validate_text(
            contract,
            pooling=pooling,
            prefix=prefix,
            max_length=max_length,
            output_dtype=output_dtype,
        )
    return contract
