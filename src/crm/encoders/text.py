"""Text encoder wrappers for the CRM multimodal pipeline.

Supports four transformer text encoders + one classical baseline (FastText).

Each encoder exposes:
    - load(device) → (model, tokenizer, pool_fn)
    - encode_batch(texts: list[str]) → (B, D) np.ndarray
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch


@dataclass
class TextEncoderSpec:
    name: str
    hf_id: str
    dim: int
    pool: str  # "cls" | "mean" | "e5_avg"
    prefix: str = ""  # instruction prefix (e.g. mE5 "query: ")
    max_length: int = 256


TEXT_ENCODERS = {
    # Paper best — must replicate
    "mE5_large": TextEncoderSpec(
        name="mE5_large",
        hf_id="intfloat/multilingual-e5-large-instruct",
        dim=1024,
        pool="e5_avg",
        prefix="Instruct: Classify the following Indonesian civic report into the correct government agency.\nQuery: ",
        max_length=256,
    ),
    # Indonesian-native
    "indobert": TextEncoderSpec(
        name="indobert",
        hf_id="indobenchmark/indobert-large-p2",
        dim=1024,
        pool="cls",
        max_length=256,
    ),
    # Indonesian encoder-decoder
    "cendol_mt5": TextEncoderSpec(
        name="cendol_mt5",
        hf_id="indonlp/cendol-mt5-large-inst",
        dim=1024,
        pool="mean",
        max_length=256,
    ),
    # SOTA multilingual 2024
    "bge_m3": TextEncoderSpec(
        name="bge_m3",
        hf_id="BAAI/bge-m3",
        dim=1024,
        pool="cls",
        max_length=256,
    ),
    # Indonesian-optimized (2024)
    "nusabert_large": TextEncoderSpec(
        name="nusabert_large",
        hf_id="LazarusNLP/NusaBERT-large",
        dim=1024,
        pool="cls",
        max_length=256,
    ),
}


def list_encoders() -> list[str]:
    return list(TEXT_ENCODERS.keys())


def load_encoder(spec: TextEncoderSpec, device: str):
    """Load an HF text encoder and tokenizer."""
    from transformers import AutoModel, AutoTokenizer, T5EncoderModel

    tokenizer = AutoTokenizer.from_pretrained(spec.hf_id)
    if "mt5" in spec.hf_id.lower() or "cendol" in spec.hf_id.lower():
        model = T5EncoderModel.from_pretrained(spec.hf_id)
    else:
        model = AutoModel.from_pretrained(spec.hf_id)
    model = model.eval().to(device)
    return model, tokenizer


def _average_pool(
    last_hidden: torch.Tensor, attention_mask: torch.Tensor
) -> torch.Tensor:
    """mE5-style average pool (masked)."""
    mask = attention_mask.unsqueeze(-1).float()
    summed = (last_hidden * mask).sum(dim=1)
    count = mask.sum(dim=1).clamp(min=1e-9)
    return summed / count


@torch.inference_mode()
def encode_batch(
    model,
    tokenizer,
    texts: list[str],
    spec: TextEncoderSpec,
    device: str,
    use_amp: bool = True,
) -> np.ndarray:
    """Tokenize + forward + pool. Returns (B, D) fp32 numpy, L2-normalized."""
    texts = [spec.prefix + t for t in texts]
    enc = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=spec.max_length,
        return_tensors="pt",
    ).to(device)

    amp_dtype = (
        torch.float16 if use_amp and device.startswith("cuda") else torch.float32
    )
    with torch.autocast(
        device_type=device.split(":")[0],
        dtype=amp_dtype,
        enabled=(amp_dtype != torch.float32),
    ):
        out = model(**enc)

    hidden = out.last_hidden_state
    if spec.pool == "cls":
        feats = hidden[:, 0]
    elif spec.pool == "mean":
        mask = enc["attention_mask"].unsqueeze(-1).float()
        feats = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
    elif spec.pool == "e5_avg":
        feats = _average_pool(hidden, enc["attention_mask"])
    else:
        raise ValueError(f"Unknown pool: {spec.pool}")

    # L2 normalize (standard for retrieval / contrastive embeddings)
    feats = torch.nn.functional.normalize(feats.float(), p=2, dim=1)
    return feats.cpu().numpy()
