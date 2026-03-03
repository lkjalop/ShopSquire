"""Diffusion-model image detection via spectral analysis.

Detects AI-generated images (Stable Diffusion, DALL-E, Midjourney, etc.)
by analyzing high-frequency noise signatures in the frequency domain.

Key insight: Diffusion models leave distinctive spectral fingerprints —
their denoising process creates characteristic patterns in the Fourier
transform that differ from natural camera noise.

Works on raw bytes (no GPU required).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class DiffusionDetectionResult:
    is_ai_generated: bool
    confidence: float  # 0.0–1.0
    signals: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Spectral analysis on raw pixel data
# ---------------------------------------------------------------------------

def _bytes_to_grayscale_grid(
    raw_pixels: bytes,
    width: int,
    height: int,
    channels: int = 3,
) -> List[List[float]]:
    """Convert raw RGB/RGBA pixel bytes to a grayscale 2D grid [0.0–255.0]."""
    grid: List[List[float]] = []
    for y in range(height):
        row: List[float] = []
        for x in range(width):
            offset = (y * width + x) * channels
            if offset + 2 < len(raw_pixels):
                r = raw_pixels[offset]
                g = raw_pixels[offset + 1]
                b = raw_pixels[offset + 2]
                gray = 0.299 * r + 0.587 * g + 0.114 * b
            else:
                gray = 0.0
            row.append(gray)
        grid.append(row)
    return grid


def _dft_1d(signal: List[float]) -> List[float]:
    """Compute magnitude of 1D DFT (pure Python, no NumPy/SciPy)."""
    n = len(signal)
    magnitudes = []
    for k in range(n // 2):
        re_part = 0.0
        im_part = 0.0
        for t in range(n):
            angle = 2.0 * math.pi * k * t / n
            re_part += signal[t] * math.cos(angle)
            im_part -= signal[t] * math.sin(angle)
        magnitudes.append(math.sqrt(re_part * re_part + im_part * im_part))
    return magnitudes


def _analyze_spectral_rows(grid: List[List[float]], sample_rows: int = 16) -> Dict[str, float]:
    """Run 1D DFT on sampled rows and compute high-frequency energy ratio."""
    height = len(grid)
    width = len(grid[0]) if grid else 0
    if height < 4 or width < 8:
        return {"hf_ratio": 0.0, "spectral_flatness": 0.0, "peak_freq_norm": 0.0}

    step = max(1, height // sample_rows)
    hf_ratios: List[float] = []
    flatness_values: List[float] = []
    peak_freqs: List[float] = []

    for y in range(0, height, step):
        row = grid[y]
        if len(row) < 8:
            continue
        # Use a window to reduce spectral leakage
        n = len(row)
        windowed = [row[i] * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) for i in range(n)]
        mags = _dft_1d(windowed)
        if not mags:
            continue

        total_energy = sum(m * m for m in mags) + 1e-12
        # High-frequency: top 25% of spectrum
        cutoff = len(mags) * 3 // 4
        hf_energy = sum(mags[i] * mags[i] for i in range(cutoff, len(mags)))
        hf_ratios.append(hf_energy / total_energy)

        # Spectral flatness (geometric mean / arithmetic mean of magnitudes)
        log_sum = sum(math.log(m + 1e-12) for m in mags)
        geo_mean = math.exp(log_sum / len(mags))
        arith_mean = sum(mags) / len(mags) + 1e-12
        flatness_values.append(geo_mean / arith_mean)

        # Peak frequency (normalized)
        peak_idx = max(range(len(mags)), key=lambda i: mags[i])
        peak_freqs.append(peak_idx / len(mags))

    if not hf_ratios:
        return {"hf_ratio": 0.0, "spectral_flatness": 0.0, "peak_freq_norm": 0.0}

    return {
        "hf_ratio": sum(hf_ratios) / len(hf_ratios),
        "spectral_flatness": sum(flatness_values) / len(flatness_values),
        "peak_freq_norm": sum(peak_freqs) / len(peak_freqs),
    }


def _analyze_noise_uniformity(grid: List[List[float]], block_size: int = 8) -> float:
    """Measure how uniform the local noise variance is across blocks.

    Diffusion models tend to produce unnaturally uniform noise distributions
    compared to real camera sensors (which show vignetting, sensor noise patterns).
    Returns a uniformity score (0.0 = varied noise, 1.0 = perfectly uniform).
    """
    height = len(grid)
    width = len(grid[0]) if grid else 0
    if height < block_size * 2 or width < block_size * 2:
        return 0.0

    variances: List[float] = []
    for by in range(0, height - block_size, block_size):
        for bx in range(0, width - block_size, block_size):
            values = []
            for dy in range(block_size):
                for dx in range(block_size):
                    values.append(grid[by + dy][bx + dx])
            if values:
                mean = sum(values) / len(values)
                var = sum((v - mean) ** 2 for v in values) / len(values)
                variances.append(var)

    if len(variances) < 4:
        return 0.0

    mean_var = sum(variances) / len(variances)
    if mean_var < 1e-6:
        return 1.0  # near-zero variance everywhere → very uniform
    std_var = math.sqrt(sum((v - mean_var) ** 2 for v in variances) / len(variances))
    cv = std_var / (mean_var + 1e-12)  # coefficient of variation
    # Lower CV = more uniform = more suspicious
    uniformity = max(0.0, 1.0 - cv)
    return uniformity


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_diffusion_image(
    raw_pixels: bytes,
    width: int,
    height: int,
    channels: int = 3,
) -> DiffusionDetectionResult:
    """Analyze raw pixel data for diffusion-model generation signatures.

    Parameters
    ----------
    raw_pixels : bytes
        Flat array of pixel data (RGB or RGBA order).
    width, height : int
        Image dimensions.
    channels : int
        3 for RGB, 4 for RGBA.

    Returns
    -------
    DiffusionDetectionResult
        Verdict with confidence score and signal explanations.
    """
    if len(raw_pixels) < width * height * channels * 0.5:
        return DiffusionDetectionResult(
            is_ai_generated=False, confidence=0.0,
            signals=["insufficient_data"],
            details={"error": "raw_pixels too short for declared dimensions"},
        )

    grid = _bytes_to_grayscale_grid(raw_pixels, width, height, channels)
    spectral = _analyze_spectral_rows(grid)
    noise_uniformity = _analyze_noise_uniformity(grid)

    signals: List[str] = []
    score = 0.0

    # High-frequency energy ratio — diffusion models produce distinctive HF patterns
    hf = spectral["hf_ratio"]
    if hf < 0.02:
        signals.append("low_hf_energy")
        score += 0.30
    elif hf > 0.15:
        signals.append("high_hf_energy")
        score += 0.10  # some diffusion models oversharpen

    # Spectral flatness — AI images tend toward flatter spectra
    sf = spectral["spectral_flatness"]
    if sf > 0.4:
        signals.append("flat_spectrum")
        score += 0.25

    # Noise uniformity — unnaturally uniform noise = synthetic
    if noise_uniformity > 0.7:
        signals.append("uniform_noise")
        score += 0.25
    elif noise_uniformity > 0.5:
        signals.append("somewhat_uniform_noise")
        score += 0.10

    # Peak frequency clustering
    pf = spectral["peak_freq_norm"]
    if 0.0 < pf < 0.05:
        signals.append("low_peak_freq")
        score += 0.10

    confidence = min(score, 1.0)
    is_ai = confidence >= 0.45

    return DiffusionDetectionResult(
        is_ai_generated=is_ai,
        confidence=round(confidence, 3),
        signals=signals,
        details={
            "hf_ratio": round(hf, 4),
            "spectral_flatness": round(sf, 4),
            "noise_uniformity": round(noise_uniformity, 4),
            "peak_freq_norm": round(pf, 4),
        },
    )
