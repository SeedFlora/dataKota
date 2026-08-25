"""Early-fusion utilities for combining image + text embeddings."""

from __future__ import annotations

import numpy as np


def early_fusion(
    img_emb: np.ndarray, txt_emb: np.ndarray, l2_per_modality: bool = True
) -> np.ndarray:
    """Concatenate image + text embeddings along feature axis.

    Args:
        img_emb: (N, D_img)
        txt_emb: (N, D_txt)
        l2_per_modality: L2-normalize each modality before concat so that
            neither dominates the distance metric downstream (paper implicit).

    Returns:
        (N, D_img + D_txt) fp32 array
    """
    if img_emb.shape[0] != txt_emb.shape[0]:
        raise ValueError(
            f"row mismatch: img {img_emb.shape[0]} vs txt {txt_emb.shape[0]}"
        )

    if l2_per_modality:
        img_emb = _l2(img_emb)
        txt_emb = _l2(txt_emb)

    return np.concatenate([img_emb, txt_emb], axis=1).astype(np.float32)


def _l2(x: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    norm = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.clip(norm, eps, None)


def class_weights(labels: np.ndarray, num_classes: int) -> dict[int, float]:
    """Paper's class weight formula:  w_l = N / (C * N_l)."""
    N = len(labels)
    counts = np.bincount(labels, minlength=num_classes)
    return {l: N / (num_classes * max(counts[l], 1)) for l in range(num_classes)}
