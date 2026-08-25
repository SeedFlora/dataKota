"""Synthetic complete preprocessing contracts used only by tests."""

from __future__ import annotations

from hashlib import sha256
from typing import Any


def image_preprocessing(
    *,
    pooling: str = "cls_token",
    output_dtype: str = "float32",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "modality": "image",
        "implementation": {
            "framework": "custom",
            "library": "synthetic-image-pipeline",
            "library_version": "1.0.0",
            "processor_class": "tests.SyntheticImageProcessor",
            "configuration_source": "explicit_parameters",
            "processor_repository": None,
            "processor_revision": None,
            "assets": [
                {
                    "path": "preprocessor_config.json",
                    "sha256": sha256(b"{}").hexdigest(),
                }
            ],
        },
        "decode": {
            "backend": "Pillow",
            "backend_version": "10.4.0",
            "exif_orientation": "apply_exif_transpose",
            "color_mode": "RGB",
            "alpha_channel_policy": "drop_after_rgb_conversion",
            "animated_image_policy": "first_frame",
            "missing_image_policy": "fail",
            "decode_error_policy": "fail",
        },
        "geometry": {
            "resize_mode": "exact",
            "resize_size": [16, 16],
            "interpolation": "bicubic",
            "antialias": True,
            "preserve_aspect_ratio": False,
            "crop_mode": "none",
            "crop_size": None,
        },
        "numeric": {
            "input_channel_order": "RGB",
            "rescale_enabled": True,
            "rescale_factor": 1.0 / 255.0,
            "normalize_enabled": True,
            "mean": [0.5, 0.5, 0.5],
            "std": [0.5, 0.5, 0.5],
            "tensor_layout": "NCHW",
            "tensor_dtype": "float32",
        },
        "embedding": {
            "pooling": pooling,
            "l2_normalize": False,
            "output_dtype": output_dtype,
        },
    }


def text_preprocessing(
    *,
    pooling: str = "e5_avg",
    prefix: str = "query: ",
    max_length: int = 16,
    output_dtype: str = "float32",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "modality": "text",
        "implementation": {
            "framework": "custom",
            "library": "synthetic-tokenizer",
            "library_version": "1.0.0",
            "tokenizer_class": "tests.SyntheticTokenizer",
            "tokenizer_repository": "example/synthetic-tokenizer",
            "tokenizer_revision": "3" * 40,
            "assets": [{"path": "tokenizer.json", "sha256": sha256(b"{}").hexdigest()}],
        },
        "cleaning": {
            "input_encoding": "utf-8",
            "unicode_normalization": "none",
            "strip": False,
            "collapse_whitespace": False,
            "lowercase": False,
            "newline_policy": "preserve",
            "html_policy": "preserve",
            "url_policy": "preserve",
            "mention_policy": "preserve",
            "control_character_policy": "preserve",
            "empty_text_policy": "reject",
        },
        "tokenization": {
            "prefix": prefix,
            "add_special_tokens": True,
            "truncation": True,
            "truncation_side": "right",
            "max_length": max_length,
            "padding": "longest",
            "padding_side": "right",
            "pad_to_multiple_of": None,
            "return_attention_mask": True,
            "return_token_type_ids": "auto",
        },
        "embedding": {
            "pooling": pooling,
            "pooling_detail": "attention_mask_weighted_mean",
            "l2_normalize": True,
            "output_dtype": output_dtype,
        },
    }
