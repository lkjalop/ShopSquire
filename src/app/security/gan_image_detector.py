"""GAN / Diffusion fake-image detection (P2).

Detects AI-generated images (Midjourney, FLUX, DALL-E, Stable Diffusion)
using multiple statistical and spectral heuristics that do not require
a trained classifier:

1. **Spectral analysis** — GAN/diffusion outputs exhibit characteristic
   frequency-domain artefacts (spectral peaks at regular intervals).
2. **Colour histogram analysis** — AI-generated images often have
   unnaturally smooth histograms vs. natural camera noise.
3. **JPEG quantisation table fingerprinting** — AI images saved as JPEG
   use default tables (no camera-specific Q-table).
4. **Texture regularity** — GANs can produce unnaturally regular
   micro-textures (measured via autocorrelation).
5. **EXIF absence** — AI-generated images lack real camera EXIF.

The composite score represents likelihood that the image is AI-generated.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    import numpy as np  # type: ignore
    from PIL import Image  # type: ignore
except Exception:
    np = None  # type: ignore
    Image = None  # type: ignore


_THRESHOLD = float(os.getenv("GAN_DETECTION_THRESHOLD", "0.55"))


@dataclass
class GANDetectionResult:
    fake_score: float = 0.0
    spectral_regularity: float = 0.0
    histogram_smoothness: float = 0.0
    texture_regularity: float = 0.0
    exif_absent: bool = False
    jpeg_default_qtable: bool = False
    is_likely_fake: bool = False
    explanations: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)


def _spectral_regularity(img: "Image.Image") -> float:
    """Detect regular spectral peaks characteristic of GAN upsampling."""
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    fft = np.fft.fft2(arr)
    mag = np.abs(np.fft.fftshift(fft))
    h, w = mag.shape
    cy, cx = h // 2, w // 2

    # Measure periodicity via autocorrelation of radial spectral profile
    radii: Dict[int, List[float]] = {}
    max_r = min(cy, cx) - 1
    Y, X = np.mgrid[:h, :w]
    R = np.sqrt((Y - cy) ** 2 + (X - cx) ** 2).astype(int)
    for r in range(1, min(max_r, 128)):
        mask = R == r
        if mask.any():
            vals = mag[mask]
            radii[r] = [float(np.mean(vals))]

    if len(radii) < 20:
        return 0.0

    profile = np.array([radii[r][0] for r in sorted(radii.keys())])
    # Normalize
    profile = profile / (np.max(profile) + 1e-12)
    # Autocorrelation for periodicity detection
    n = len(profile)
    ac = np.correlate(profile - profile.mean(), profile - profile.mean(), mode="full")
    ac = ac[n - 1:]  # keep positive lags only
    ac = ac / (ac[0] + 1e-12)
    # Count significant peaks (excluding lag 0)
    peaks = 0
    for i in range(2, min(len(ac), 64)):
        if ac[i] > 0.3 and ac[i] > ac[i - 1] and ac[i] > ac[i + 1] if i + 1 < len(ac) else ac[i] > ac[i - 1]:
            peaks += 1
    return float(min(1.0, peaks / 5.0))


def _histogram_smoothness(img: "Image.Image") -> float:
    """Measure how smooth the colour histogram is — AI images tend toward smoother distributions."""
    arr = np.asarray(img.convert("RGB"), dtype=np.uint8)
    smoothness_scores = []
    for ch in range(3):
        hist, _ = np.histogram(arr[:, :, ch].flatten(), bins=256, range=(0, 256))
        hist_f = hist.astype(np.float64)
        # First derivative roughness
        diffs = np.abs(np.diff(hist_f))
        roughness = float(np.mean(diffs)) / (float(np.mean(hist_f)) + 1e-6)
        # Lower roughness = smoother = more likely AI
        smoothness_scores.append(float(max(0.0, 1.0 - roughness / 2.0)))
    return float(np.mean(smoothness_scores))


def _texture_regularity(img: "Image.Image") -> float:
    """Measure micro-texture regularity via small-patch autocorrelation variance."""
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    h, w = arr.shape
    patch = 64
    if h < patch * 2 or w < patch * 2:
        return 0.0
    # Sample patches
    variances = []
    for _ in range(8):
        y = np.random.randint(0, h - patch)
        x = np.random.randint(0, w - patch)
        p = arr[y:y + patch, x:x + patch]
        p = p - p.mean()
        ac = np.correlate(p.flatten(), p.flatten(), mode="full")
        ac = ac[len(ac) // 2:]
        ac = ac / (ac[0] + 1e-12)
        variances.append(float(np.var(ac[1:32])))
    mean_var = float(np.mean(variances))
    # Low variance of autocorrelation = too regular = likely AI
    return float(min(1.0, max(0.0, 1.0 - mean_var * 50.0)))


def _check_exif(img: "Image.Image") -> bool:
    """Return True if EXIF data is absent (typical of AI-generated images)."""
    try:
        exif = img.getexif()
        if not exif or len(exif) == 0:
            return True
        # Check for camera-specific tags (Make=271, Model=272)
        has_camera = bool(exif.get(271) or exif.get(272))
        return not has_camera
    except Exception:
        return True


def _check_jpeg_qtable(image_bytes: bytes) -> bool:
    """Check if JPEG uses default quantisation tables (no camera-specific tuning)."""
    # JPEG standard luminance Q-table (quality 75 baseline)
    standard_luma = [
        16, 11, 10, 16, 24, 40, 51, 61,
        12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56,
        14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77,
        24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101,
        72, 92, 95, 98, 112, 100, 103, 99,
    ]
    try:
        img = Image.open(io.BytesIO(image_bytes))
        qtables = img.quantization
        if not qtables:
            return True
        # Compare first table with standard
        first_table = list(qtables.get(0, []))
        if len(first_table) < 64:
            return False
        diff = sum(abs(a - b) for a, b in zip(first_table[:64], standard_luma))
        return diff < 100  # very close to standard = likely not from camera
    except Exception:
        return False


def _diffusion_mid_freq_energy(img: "Image.Image") -> float:
    """Detect diffusion-model spectral footprint (FLUX, SD3, DALL-E 3).

    Diffusion models produce characteristic mid-frequency energy distributions
    that differ from both natural images and older GAN architectures.
    The denoising process creates a distinct "band" in the frequency spectrum
    where energy is unnaturally concentrated or depleted relative to the
    natural 1/f power-law decay.
    """
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    fft = np.fft.fft2(arr)
    mag = np.abs(np.fft.fftshift(fft))
    h, w = mag.shape
    cy, cx = h // 2, w // 2

    max_r = min(cy, cx) - 1
    if max_r < 32:
        return 0.0

    # Radial power spectrum in log bins
    Y, X = np.mgrid[:h, :w]
    R = np.sqrt((Y - cy) ** 2 + (X - cx) ** 2)

    # Define frequency bands: low (0-15%), mid (15-50%), high (50-100%)
    low_mask = (R >= 1) & (R < max_r * 0.15)
    mid_mask = (R >= max_r * 0.15) & (R < max_r * 0.50)
    high_mask = (R >= max_r * 0.50) & (R < max_r)

    low_energy = float(np.mean(mag[low_mask])) if low_mask.any() else 1.0
    mid_energy = float(np.mean(mag[mid_mask])) if mid_mask.any() else 0.0
    high_energy = float(np.mean(mag[high_mask])) if high_mask.any() else 0.0

    # Natural images follow approx 1/f decay — mid/low ratio should be small.
    # Diffusion models show elevated mid-frequency energy relative to this expectation.
    mid_low_ratio = mid_energy / (low_energy + 1e-12)
    mid_high_ratio = mid_energy / (high_energy + 1e-12)

    # In natural images: mid_low_ratio ~ 0.1-0.3, diffusion: 0.35-0.6+
    # Score based on deviation from natural expectation
    deviation = max(0.0, mid_low_ratio - 0.25) / 0.35  # normalized 0-1
    # Also check if mid-high ratio is unusually flat (diffusion trait)
    flatness = min(1.0, mid_high_ratio / 5.0) if mid_high_ratio > 2.0 else 0.0

    return float(min(1.0, 0.6 * deviation + 0.4 * flatness))


def detect_fake_image(image_bytes: bytes, *, threshold: float | None = None) -> GANDetectionResult:
    """Detect whether an image is likely AI-generated (GAN/diffusion).

    Returns GANDetectionResult with composite score and explanations.
    """
    thr = threshold if threshold is not None else _THRESHOLD
    if np is None or Image is None:
        return GANDetectionResult(explanations=["numpy/Pillow not available"])

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        return GANDetectionResult(explanations=[f"Cannot open image: {exc}"])

    spectral = _spectral_regularity(img)
    hist_smooth = _histogram_smoothness(img)
    texture = _texture_regularity(img)
    exif_absent = _check_exif(img)
    default_qt = _check_jpeg_qtable(image_bytes)
    diffusion_mid = _diffusion_mid_freq_energy(img)

    # Weighted composite score — 6 signals
    score = float(min(1.0, (
        0.20 * spectral
        + 0.20 * hist_smooth
        + 0.15 * texture
        + 0.15 * diffusion_mid
        + (0.15 if exif_absent else 0.0)
        + (0.15 if default_qt else 0.0)
    )))

    explanations: List[str] = []
    if spectral >= 0.5:
        explanations.append("Spectral regularity suggests GAN upsampling artefacts")
    if hist_smooth >= 0.7:
        explanations.append("Colour histogram unusually smooth — typical of AI-generated images")
    if texture >= 0.6:
        explanations.append("Micro-texture over-regularity detected — may indicate diffusion model output")
    if diffusion_mid >= 0.4:
        explanations.append("Mid-frequency spectral energy anomaly — consistent with diffusion model (FLUX/SD3) artifacts")
    if exif_absent:
        explanations.append("No camera EXIF metadata — consistent with AI generation")
    if default_qt:
        explanations.append("JPEG uses default quantisation tables — no camera-specific tuning")

    return GANDetectionResult(
        fake_score=round(score, 4),
        spectral_regularity=round(spectral, 4),
        histogram_smoothness=round(hist_smooth, 4),
        texture_regularity=round(texture, 4),
        exif_absent=exif_absent,
        jpeg_default_qtable=default_qt,
        is_likely_fake=score >= thr,
        explanations=explanations,
        details={
            "threshold": thr,
            "image_size": list(img.size),
            "diffusion_mid_freq_score": round(diffusion_mid, 4),
        },
    )
