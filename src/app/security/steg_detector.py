"""S-012 — Steganographic payload detector (LSB analysis).

Detects hidden data in image pixel channels using:
1. LSB plane entropy analysis — natural images have low entropy in LSBs,
   steganographic payloads raise it toward ~1.0.
2. Chi-square uniformity test on LSB pairs — steg tools produce
   statistically uniform pair distributions.
3. Sample Pairs Analysis (SPA) — estimates embedded message length.
4. Sequential LSB pattern detection — checks for byte-aligned patterns.

This is a mandatory pre-processing gate on all inbound images.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore
except Exception:
    np = None  # type: ignore
    Image = None  # type: ignore


@dataclass
class StegResult:
    steg_score: float = 0.0
    lsb_entropy_r: float = 0.0
    lsb_entropy_g: float = 0.0
    lsb_entropy_b: float = 0.0
    chi_square_p: float = 1.0
    spa_estimate: float = 0.0
    sequential_pattern_score: float = 0.0
    dct_anomaly_score: float = 0.0
    jpeg_quant_table_score: float = 0.0
    is_suspicious: bool = False
    explanations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


def _channel_lsb_entropy(channel: Any) -> float:
    """Shannon entropy of the LSB plane (0 or 1 values)."""
    lsb = (channel.flatten() & 1).astype(np.uint8)
    ones = int(np.sum(lsb))
    total = len(lsb)
    zeros = total - ones
    if zeros == 0 or ones == 0:
        return 0.0
    p0 = zeros / total
    p1 = ones / total
    return -(p0 * math.log2(p0) + p1 * math.log2(p1))


def _chi_square_lsb(channel: Any) -> float:
    """Chi-square test on LSB pair frequencies.

    Steg tools produce near-uniform pair distributions (p → 1.0).
    Natural images have non-uniform distributions (p → 0.0).
    Returns p-value approximation (higher = more suspicious).
    """
    flat = channel.flatten().astype(np.int32)
    # Pair consecutive values by their PoV (pair of values) category
    # Values differing only in LSB form a pair: (2k, 2k+1)
    even = flat & ~1  # zero the LSB
    # Count frequency of each even value
    vals, counts = np.unique(even, return_counts=True)
    if len(vals) < 2:
        return 0.0
    # For each pair category, count occurrences of even vs odd
    chi2 = 0.0
    dof = 0
    for v, c in zip(vals, counts):
        mask_even = flat == v
        mask_odd = flat == (v + 1)
        n_even = int(np.sum(mask_even))
        n_odd = int(np.sum(mask_odd))
        total = n_even + n_odd
        if total < 2:
            continue
        expected = total / 2.0
        chi2 += ((n_even - expected) ** 2) / expected
        chi2 += ((n_odd - expected) ** 2) / expected
        dof += 1
    if dof < 1:
        return 0.0
    # Approximate p-value using normal approximation for large dof
    z = (chi2 - dof) / max(1.0, math.sqrt(2.0 * dof))
    # Convert z-score to approximate p-value (higher z = lower chi2 deviation = more uniform = more suspicious)
    # We want suspicious = high p-value (uniform)
    p_approx = 0.5 * (1.0 + math.erf(-z / math.sqrt(2.0)))
    return float(min(1.0, max(0.0, p_approx)))


def _spa_estimate(channel: Any) -> float:
    """Sample Pairs Analysis — estimates hidden message length as fraction of capacity.

    Based on Dumitrescu, Wu, Wang (2003) simplified approach.
    """
    flat = channel.flatten().astype(np.int32)
    n = len(flat) - 1
    if n < 100:
        return 0.0
    # Count close pairs (differ by exactly 1 = potential LSB flip)
    diffs = np.abs(flat[:-1] - flat[1:])
    close_pairs = int(np.sum(diffs == 1))
    zero_pairs = int(np.sum(diffs == 0))
    total_pairs = n
    if total_pairs < 1:
        return 0.0
    # Estimate: ratio of close pairs indicates LSB modification
    # Natural images: close_pairs/total typically 0.1-0.25
    # Steg images: close_pairs/total typically 0.35+
    ratio = close_pairs / total_pairs
    # Normalize to 0..1 where >0.35 is suspicious
    estimate = max(0.0, min(1.0, (ratio - 0.15) / 0.30))
    return float(estimate)


def _sequential_pattern_score(channel: Any, block_size: int = 8) -> float:
    """Detect byte-aligned sequential patterns in LSB plane.

    Steganographic data often has structure at byte boundaries.
    """
    lsb = (channel.flatten() & 1).astype(np.uint8)
    n = len(lsb)
    if n < block_size * 10:
        return 0.0
    # Check for non-random runs at byte boundaries
    blocks = n // block_size
    if blocks < 10:
        return 0.0
    lsb_blocks = lsb[:blocks * block_size].reshape(blocks, block_size)
    # Convert each block to a byte value
    weights = np.array([2 ** i for i in range(block_size)], dtype=np.uint8)
    byte_vals = np.dot(lsb_blocks, weights).astype(np.uint8)
    # Check entropy of the byte stream — random = ~8.0, structured data < 7.0
    unique, counts = np.unique(byte_vals, return_counts=True)
    probs = counts / float(len(byte_vals))
    ent = -float(np.sum(probs * np.log2(probs + 1e-12)))
    # Structured data has lower entropy
    # Score: 0 if entropy >= 7.5 (random), 1 if entropy <= 4.0 (highly structured)
    score = max(0.0, min(1.0, (7.5 - ent) / 3.5))
    return float(score)


def _dct2(block: Any) -> Any:
    """Small DCT-II implementation without scipy dependency."""
    n = block.shape[0]
    k = np.arange(n, dtype=np.float64)
    x = np.arange(n, dtype=np.float64)
    cos_m = np.cos((np.pi / n) * (x[:, None] + 0.5) * k[None, :])
    return np.dot(block, cos_m)


def _jpeg_dct_anomaly_score(arr: Any) -> float:
    """Approximate DCT-domain anomaly score for JPEG-style embedding.

    Looks at odd/even parity imbalance on rounded low-frequency AC coefficients.
    """
    if arr.ndim != 2:
        return 0.0
    h, w = arr.shape
    bh = h // 8
    bw = w // 8
    if bh < 4 or bw < 4:
        return 0.0
    coeffs: list[int] = []
    for by in range(min(bh, 64)):
        for bx in range(min(bw, 64)):
            block = arr[by * 8 : (by + 1) * 8, bx * 8 : (bx + 1) * 8].astype(np.float64) - 128.0
            d = _dct2(_dct2(block).T).T
            sub = np.round(d[1:4, 1:4]).astype(np.int32).flatten()
            coeffs.extend([int(v) for v in sub if abs(int(v)) >= 2])
    if len(coeffs) < 64:
        return 0.0
    vals = np.array(coeffs, dtype=np.int32)
    odd = float(np.mean(np.abs(vals) % 2 == 1))
    # Strong parity skew can indicate quantized AC manipulation.
    skew = min(1.0, abs(odd - 0.5) * 3.0)
    return float(skew)


def _jpeg_quant_table_score(img: Any) -> float:
    """Score suspicious JPEG quantization table patterns.

    A very flat/custom quantization profile can indicate JPEG-domain steg tools.
    """
    try:
        qt = getattr(img, "quantization", None)
        if not isinstance(qt, dict) or not qt:
            return 0.0
        vals: list[int] = []
        for _, table in qt.items():
            if isinstance(table, (list, tuple)):
                vals.extend([int(v) for v in table[:64]])
        if len(vals) < 64:
            return 0.0
        arr = np.array(vals, dtype=np.int32)
        uniq_ratio = float(len(np.unique(arr))) / float(len(arr))
        # Highly repetitive tables are unusual for natural camera/JPEG pipelines.
        return float(max(0.0, min(1.0, (0.22 - uniq_ratio) / 0.22)))
    except Exception:
        return 0.0


_STEG_THRESHOLD = 0.45


def detect_steganography(
    image_bytes: bytes,
    *,
    threshold: float | None = None,
) -> StegResult:
    """Run LSB steganographic analysis on raw image bytes.

    Args:
        image_bytes: raw file bytes.
        threshold: composite score above which the image is flagged suspicious.

    Returns:
        StegResult with per-channel entropy, chi-square, SPA, and composite score.
    """
    thr = threshold if threshold is not None else _STEG_THRESHOLD
    if np is None or Image is None:
        return StegResult(explanations=["numpy/Pillow not available"])

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        return StegResult(explanations=[f"Cannot open image: {exc}"])

    arr = np.asarray(img, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] < 3:
        return StegResult(explanations=["Image does not have RGB channels"])

    r_ch, g_ch, b_ch = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    # Per-channel LSB entropy
    ent_r = _channel_lsb_entropy(r_ch)
    ent_g = _channel_lsb_entropy(g_ch)
    ent_b = _channel_lsb_entropy(b_ch)
    avg_entropy = (ent_r + ent_g + ent_b) / 3.0

    # Chi-square on green channel (most commonly used for steg)
    chi_p = _chi_square_lsb(g_ch)

    # SPA on green channel
    spa = _spa_estimate(g_ch)

    # Sequential pattern analysis on green channel
    seq = _sequential_pattern_score(g_ch)

    dct_score = 0.0
    qtable_score = 0.0
    try:
        # Analyze luminance channel for JPEG-style DCT perturbations.
        lum = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.uint8)
        dct_score = _jpeg_dct_anomaly_score(lum)
        qtable_score = _jpeg_quant_table_score(img)
    except Exception:
        dct_score = 0.0
        qtable_score = 0.0

    # Composite score: weighted combination
    # High LSB entropy (→1.0), high chi-square p (→1.0), high SPA, structured patterns,
    # and JPEG DCT-domain anomalies.
    composite = (
        0.24 * max(0.0, (avg_entropy - 0.90) / 0.10)  # natural ~0.85-0.95, steg ~0.99+
        + 0.24 * chi_p
        + 0.20 * spa
        + 0.12 * seq
        + 0.14 * dct_score
        + 0.06 * qtable_score
    )
    composite = float(min(1.0, max(0.0, composite)))

    explanations = []
    if avg_entropy > 0.97:
        explanations.append(f"LSB entropy very high ({avg_entropy:.4f}), typical of steganographic embedding")
    if chi_p > 0.5:
        explanations.append(f"Chi-square uniformity high (p={chi_p:.4f}), LSB pairs suspiciously uniform")
    if spa > 0.4:
        explanations.append(f"SPA estimates {spa:.1%} of capacity may contain hidden data")
    if seq > 0.3:
        explanations.append(f"Sequential LSB patterns detected (score={seq:.3f})")
    if dct_score > 0.4:
        explanations.append(f"JPEG DCT-domain anomaly detected (score={dct_score:.3f})")
    if qtable_score > 0.4:
        explanations.append(f"JPEG quantization table appears unusually repetitive (score={qtable_score:.3f})")

    return StegResult(
        steg_score=round(composite, 4),
        lsb_entropy_r=round(ent_r, 4),
        lsb_entropy_g=round(ent_g, 4),
        lsb_entropy_b=round(ent_b, 4),
        chi_square_p=round(chi_p, 4),
        spa_estimate=round(spa, 4),
        sequential_pattern_score=round(seq, 4),
        dct_anomaly_score=round(dct_score, 4),
        jpeg_quant_table_score=round(qtable_score, 4),
        is_suspicious=composite >= thr,
        explanations=explanations,
        details={
            "threshold": thr,
            "avg_lsb_entropy": round(avg_entropy, 4),
            "composite_weights": {
                "entropy": 0.24,
                "chi_square": 0.24,
                "spa": 0.20,
                "sequential": 0.12,
                "dct_domain": 0.14,
                "jpeg_qtable": 0.06,
            },
        },
    )
