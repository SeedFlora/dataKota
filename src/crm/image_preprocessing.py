"""Exact exported Hugging Face image-preprocessing contract."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


class ImagePreprocessor:
    """Load and execute the same processor configuration used during export.

    Modern DINOv3 processors resize torch tensors with Torchvision antialiasing.
    A seemingly equivalent Pillow resize differs enough to invalidate a strict
    end-to-end parity claim, so deployment deliberately keeps the reference
    implementation rather than a lightweight approximation.
    """

    def __init__(self, config_path: Path):
        if not config_path.is_file():
            raise FileNotFoundError(f"image processor config not found: {config_path}")
        from transformers import AutoImageProcessor

        self.processor = AutoImageProcessor.from_pretrained(
            str(config_path.parent),
            local_files_only=True,
        )

    def __call__(self, img: Image.Image) -> np.ndarray:
        # These operations are part of the exported preprocessing contract, not
        # processor defaults: orient first, then deterministically discard any
        # alpha channel while converting grayscale/palette inputs to RGB.
        corrected = ImageOps.exif_transpose(img).convert("RGB")
        output = self.processor(images=corrected, return_tensors="np")
        pixels = np.asarray(output["pixel_values"], dtype=np.float32)
        if pixels.ndim != 4 or pixels.shape[0] != 1 or pixels.shape[1] != 3:
            raise ValueError(
                "exported image processor must return shape (1, 3, H, W); "
                f"got {pixels.shape}"
            )
        if not np.isfinite(pixels).all():
            raise ValueError("image processor returned NaN or infinite values")
        return pixels
