"""Image encoder wrappers for the CRM multimodal pipeline.

Each encoder exposes:
    - load(device) → model + preprocessor
    - encode_batch(images: list[PIL.Image]) → (B, D) np.ndarray

All encoders return fp32 numpy for downstream CatBoost compatibility.
Inference is fp16 on GPU for speed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import torch
from PIL import Image, ImageOps


@dataclass
class ImageEncoderSpec:
    name: str
    hf_id: str
    dim: int
    image_size: int
    loader: Callable  # (device) → (model, preprocess_fn)


def _timm_loader(model_name: str, image_size: int):
    """Load a timm model, return (model, preprocess_fn)."""
    import timm
    from timm.data import create_transform, resolve_data_config

    def load(device: str):
        model = timm.create_model(
            model_name, pretrained=True, num_classes=0
        )  # remove head
        model = model.eval().to(device)
        cfg = resolve_data_config({}, model=model)
        cfg["input_size"] = (3, image_size, image_size)
        preprocess = create_transform(**cfg, is_training=False)
        return model, preprocess

    return load


def _hf_loader(hf_id: str):
    """Load an HF AutoModel, return (model, preprocess_fn) using AutoImageProcessor."""
    from transformers import AutoImageProcessor, AutoModel

    def load(device: str):
        processor = AutoImageProcessor.from_pretrained(hf_id)
        model = AutoModel.from_pretrained(hf_id).eval().to(device)

        def preprocess(img: Image.Image) -> torch.Tensor:
            return processor(images=img, return_tensors="pt")["pixel_values"][0]

        return model, preprocess

    return load


IMAGE_ENCODERS = {
    "dinov2_large": ImageEncoderSpec(
        name="dinov2_large",
        hf_id="facebook/dinov2-large",
        dim=1024,
        image_size=224,
        loader=_hf_loader("facebook/dinov2-large"),
    ),
    "hiera_large": ImageEncoderSpec(
        name="hiera_large",
        hf_id="timm/hiera_large_224.mae_in1k_ft_in1k",
        dim=1024,
        image_size=224,
        loader=_timm_loader("hiera_large_224.mae_in1k_ft_in1k", 224),
    ),
    "eva02_large": ImageEncoderSpec(
        name="eva02_large",
        hf_id="timm/eva02_large_patch14_448.mim_m38m_ft_in22k_in1k",
        dim=1024,
        image_size=448,
        loader=_timm_loader("eva02_large_patch14_448.mim_m38m_ft_in22k_in1k", 448),
    ),
    "dinov3_large": ImageEncoderSpec(
        name="dinov3_large",
        hf_id="facebook/dinov3-vitl16-pretrain-lvd1689m",
        dim=1024,
        image_size=224,
        loader=_hf_loader("facebook/dinov3-vitl16-pretrain-lvd1689m"),
    ),
}


def list_encoders() -> list[str]:
    return list(IMAGE_ENCODERS.keys())


@torch.inference_mode()
def encode_batch(
    model, preprocess, images: list[Image.Image], device: str, use_amp: bool = True
) -> np.ndarray:
    """Run forward pass on a batch of PIL images. Returns (B, D) fp32 numpy."""
    batch = torch.stack(
        [preprocess(ImageOps.exif_transpose(img).convert("RGB")) for img in images]
    ).to(device)

    amp_dtype = (
        torch.float16 if use_amp and device.startswith("cuda") else torch.float32
    )
    with torch.autocast(
        device_type=device.split(":")[0],
        dtype=amp_dtype,
        enabled=(amp_dtype != torch.float32),
    ):
        out = model(batch)

    # Normalize output — HF AutoModel returns BaseModelOutput, timm returns tensor
    if hasattr(out, "pooler_output") and out.pooler_output is not None:
        feats = out.pooler_output
    elif hasattr(out, "last_hidden_state"):
        # CLS token pooling
        feats = out.last_hidden_state[:, 0]
    elif isinstance(out, torch.Tensor):
        feats = out
    else:
        raise ValueError(f"Unknown output type: {type(out)}")

    return feats.float().cpu().numpy()
