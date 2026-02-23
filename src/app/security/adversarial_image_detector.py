"""S-007 — Adversarial image detector.

Detects adversarial perturbation patterns in uploaded images using:
1. Perceptual hash (phash) comparison against known-clean references.
2. High-frequency noise analysis (adversarial patches produce distinctive
   spectral signatures in FFT domain).
3. JPEG re-compression stability test — adversarial perturbations are fragile
   under lossy re-encoding.
4. Local pixel variance analysis — adversarial patches often create unnatural
   high-frequency gradients in localised regions.

This module is deterministic (no ML model required) but can optionally use a
lightweight classifier when available.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore
except Exception:
    np = None  # type: ignore
    Image = None  # type: ignore


@dataclass
class AdversarialResult:
    adversarial_score: float = 0.0
    high_freq_ratio: float = 0.0
    recompress_instability: float = 0.0
    local_gradient_anomaly: float = 0.0
    phash_distance: int = -1
    is_adversarial: bool = False
    explanations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


def _phash_bits(img: "Image.Image") -> str:
    """Compute a 64-bit perceptual hash (DCT-based)."""
    g = img.convert("L").resize((32, 32), Image.BILINEAR)
    f = np.asarray(g, dtype=np.float64)

    def dct1(a: np.ndarray) -> np.ndarray:
        n = a.shape[0]
        k = np.arange(n).reshape(-1, 1)
        i = np.arange(n).reshape(1, -1)
        coef = np.cos(np.pi * (2 * i + 1) * k / (2 * n))
        alpha = np.where(k == 0, np.sqrt(1.0 / n), np.sqrt(2.0 / n))
        return alpha * (coef @ a)

    F = dct1(dct1(f).T).T
    low = F[:8, :8]
    med = float(np.median(low[1:, 1:]))
    bits = (low[1:, 1:] > med).astype(np.uint8).flatten()
    return "".join("1" if b else "0" for b in bits)


def _hamming(a: str, b: str) -> int:
    return sum(c1 != c2 for c1, c2 in zip(a, b))


def _high_freq_energy_ratio(img: "Image.Image") -> float:
    """Ratio of high-frequency energy in 2-D FFT — adversarial noise is spectrally distinctive."""
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    fft = np.fft.fft2(arr)
    shifted = np.fft.fftshift(fft)
    mag = np.abs(shifted)
    h, w = mag.shape
    cy, cx = h // 2, w // 2
    radius = min(cy, cx) // 4  # inner low-freq region
    Y, X = np.ogrid[:h, :w]
    low_mask = ((Y - cy) ** 2 + (X - cx) ** 2) <= radius ** 2
    total_energy = float(np.sum(mag ** 2)) + 1e-12
    low_energy = float(np.sum(mag[low_mask] ** 2))
    high_energy = total_energy - low_energy
    return float(high_energy / total_energy)


def _recompress_instability(img: "Image.Image", quality: int = 75) -> float:
    """Measure pixel-level instability after JPEG re-compression.

    Adversarial perturbations are fragile: re-compressing significantly
    changes the perturbed region while natural images remain stable.
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    recomp = np.asarray(Image.open(buf).convert("RGB"), dtype=np.float64)
    diff = np.abs(arr - recomp)
    mean_diff = float(np.mean(diff))
    # Normalise to 0..1 range where > 0.6 suggests adversarial fragility
    return float(min(1.0, mean_diff / 15.0))


def _local_gradient_anomaly(img: "Image.Image", block: int = 16) -> float:
    """Detect unnaturally high local gradients in small patches — a hallmark of adversarial patches."""
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    h, w = arr.shape
    # Sobel-like horizontal and vertical gradients
    gx = np.abs(arr[:, 1:] - arr[:, :-1])
    gy = np.abs(arr[1:, :] - arr[:-1, :])
    grad = (gx[:h - 1, :w - 1] + gy[:h - 1, :w - 1]) / 2.0
    # Block-wise max gradient
    bh, bw = grad.shape[0] // block, grad.shape[1] // block
    if bh < 2 or bw < 2:
        return 0.0
    blocks = grad[:bh * block, :bw * block].reshape(bh, block, bw, block)
    block_means = blocks.mean(axis=(1, 3))
    global_mean = float(np.mean(block_means))
    if global_mean < 1e-6:
        return 0.0
    # Ratio of max block to global mean — adversarial patches spike this
    max_block = float(np.max(block_means))
    ratio = max_block / (global_mean + 1e-6)
    return float(min(1.0, max(0.0, (ratio - 3.0) / 7.0)))


_ADVERSARIAL_THRESHOLD = float(os.getenv("ADVERSARIAL_SCORE_THRESHOLD", "0.55"))


def detect_adversarial(
    image_bytes: bytes,
    *,
    reference_phash: str | None = None,
    threshold: float | None = None,
) -> AdversarialResult:
    """Run adversarial perturbation detection on raw image bytes.

    Args:
        image_bytes: raw file bytes (JPEG/PNG/WebP).
        reference_phash: optional known-good perceptual hash for comparison.
        threshold: score above which the image is flagged adversarial.

    Returns:
        AdversarialResult with composite score and explanations.
    """
    thr = threshold if threshold is not None else _ADVERSARIAL_THRESHOLD
    if np is None or Image is None:
        return AdversarialResult(explanations=["numpy/Pillow not available"])

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        return AdversarialResult(explanations=[f"Cannot open image: {exc}"])

    hf = _high_freq_energy_ratio(img)
    recomp = _recompress_instability(img)
    grad = _local_gradient_anomaly(img)

    phash_dist = -1
    phash_component = 0.0
    if reference_phash:
        current = _phash_bits(img)
        phash_dist = _hamming(current, reference_phash)
        # Large hamming distance after minor visual change suggests adversarial
        phash_component = float(min(1.0, phash_dist / 20.0))

    # Composite score (weighted)
    score = (
        0.30 * hf
        + 0.30 * recomp
        + 0.25 * grad
        + 0.15 * phash_component
    )
    score = float(min(1.0, max(0.0, score)))

    explanations: List[str] = []
    if hf >= 0.85:
        explanations.append("Unusually high frequency energy ratio — potential adversarial noise")
    if recomp >= 0.6:
        explanations.append("Pixel instability under JPEG re-compression — adversarial perturbation likely fragile")
    if grad >= 0.5:
        explanations.append("Localised high-gradient anomaly detected — possible adversarial patch")
    if phash_dist >= 12:
        explanations.append(f"Perceptual hash distance {phash_dist} from reference — significant deviation")

    is_adv = score >= thr

    return AdversarialResult(
        adversarial_score=round(score, 4),
        high_freq_ratio=round(hf, 4),
        recompress_instability=round(recomp, 4),
        local_gradient_anomaly=round(grad, 4),
        phash_distance=phash_dist,
        is_adversarial=is_adv,
        explanations=explanations,
        details={
            "threshold": thr,
            "phash_component": round(phash_component, 4),
            "image_size": list(img.size),
        },
    )
