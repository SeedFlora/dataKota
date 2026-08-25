from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crm.image_preprocessing import ImagePreprocessor

try:
    from transformers import DINOv3ViTImageProcessor
    from transformers.utils import is_torch_available, is_torchvision_available

    REFERENCE_BACKEND_AVAILABLE = is_torch_available() and is_torchvision_available()
except (ImportError, RuntimeError):  # pragma: no cover - lightweight test env
    DINOv3ViTImageProcessor = None
    REFERENCE_BACKEND_AVAILABLE = False


class ImagePreprocessorTest(unittest.TestCase):
    @unittest.skipUnless(
        REFERENCE_BACKEND_AVAILABLE,
        "torch and torchvision are required for DINOv3 reference parity",
    )
    def test_matches_exported_dinov3_processor_exactly(self):
        try:
            reference_processor = DINOv3ViTImageProcessor()
        except (ImportError, RuntimeError, AttributeError) as error:
            self.skipTest(f"DINOv3 reference backend unavailable: {error}")
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "preprocessor_config.json"
            config_path.write_text(
                json.dumps(reference_processor.to_dict()),
                encoding="utf-8",
            )
            deployed_processor = ImagePreprocessor(config_path)

            rng = np.random.default_rng(20260825)
            image = Image.fromarray(
                rng.integers(0, 256, size=(173, 291, 3), dtype=np.uint8),
                mode="RGB",
            )
            expected = reference_processor(images=image, return_tensors="np")[
                "pixel_values"
            ]
            deployed = deployed_processor(image)

        np.testing.assert_array_equal(deployed, expected.astype(np.float32))

    def test_missing_processor_config_fails_loudly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "preprocessor_config.json"
            with self.assertRaises(FileNotFoundError):
                ImagePreprocessor(missing)

    def test_invalid_processor_output_fails_without_transformers_backend(self):
        class InvalidProcessor:
            def __call__(self, **_kwargs):
                return {"pixel_values": np.full((1, 3, 2, 2), np.nan)}

        processor = ImagePreprocessor.__new__(ImagePreprocessor)
        processor.processor = InvalidProcessor()
        image = Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8), mode="RGB")
        with self.assertRaisesRegex(ValueError, "NaN or infinite"):
            processor(image)

    def test_raw_rgba_grayscale_and_exif_inputs_are_oriented_then_rgb(self):
        class CapturingProcessor:
            def __init__(self):
                self.images: list[Image.Image] = []

            def __call__(self, *, images, **_kwargs):
                self.images.append(images.copy())
                return {"pixel_values": np.zeros((1, 3, 2, 2), dtype=np.float32)}

        capture = CapturingProcessor()
        processor = ImagePreprocessor.__new__(ImagePreprocessor)
        processor.processor = capture

        rgba = Image.new("RGBA", (2, 2), (10, 20, 30, 40))
        grayscale = Image.fromarray(
            np.array([[0, 64], [128, 255]], dtype=np.uint8), mode="L"
        )
        oriented = Image.fromarray(
            np.array(
                [
                    [[255, 0, 0], [0, 255, 0]],
                    [[0, 0, 255], [255, 255, 0]],
                ],
                dtype=np.uint8,
            ),
            mode="RGB",
        )
        oriented.getexif()[274] = 3

        for image in (rgba, grayscale, oriented):
            processor(image)

        assert [image.mode for image in capture.images] == ["RGB", "RGB", "RGB"]
        np.testing.assert_array_equal(
            np.asarray(capture.images[0]), np.asarray(rgba.convert("RGB"))
        )
        np.testing.assert_array_equal(
            np.asarray(capture.images[1]), np.asarray(grayscale.convert("RGB"))
        )
        np.testing.assert_array_equal(
            np.asarray(capture.images[2]),
            np.asarray(ImageOps.exif_transpose(oriented).convert("RGB")),
        )


if __name__ == "__main__":
    unittest.main()
