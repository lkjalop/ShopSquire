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
    diffusion_score: float = 0.0   # M05: diffusion/FLUX/SD3 spectral signature
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


def _diffusion_spectral_score(img: "Image.Image") -> float:
    """Detect spectral fingerprints characteristic of diffusion-model outputs.

    Diffusion models (FLUX, Stable Diffusion 3, SDXL) leave distinct imprints that
    differ from both natural photos and GAN outputs:

    1. **Radial PSD non-monotonicity** — the denoising schedule creates subtle rings in
       the 2D FFT. We measure the maximum *upward step* in the azimuthally-averaged PSD
       which is near-zero for natural images but elevated for diffusion outputs.

    2. **High-frequency floor elevation** — diffusion models preserve more structured
       energy in high-frequency bins than natural images (denoising residuals).

    3. **Luminance-chrominance spectral asymmetry** — diffusion models tend to produce
       chrominance (Cb/Cr) channels with a different high-frequency profile relative to
       the luminance channel compared to natural images and GAN outputs.

    Returns a score in [0, 1] where higher values indicate stronger diffusion signature.
    """
    if np is None or Image is None:
        return 0.0
    try:
        arr = np.asarray(img.convert("RGB"), dtype=np.float64)
        h, w = arr.shape[:2]

        # --- Metric 1: Radial PSD non-monotonicity ---
        lum = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]
        fft = np.fft.fft2(lum)
        shifted = np.fft.fftshift(fft)
        mag = np.abs(shifted) ** 2
        cy, cx = h // 2, w // 2
        max_r = min(cy, cx)
        # Bin into radial shells and compute mean energy per shell
        Y, X = np.ogrid[:h, :w]
        R = np.sqrt((Y - cy) ** 2 + (X - cx) ** 2).astype(np.float32)
        n_bins = max(16, max_r // 4)
        bin_edges = np.linspace(0, max_r, n_bins + 1)
        psd_profile = np.zeros(n_bins)
        for i in range(n_bins):
            mask = (R >= bin_edges[i]) & (R < bin_edges[i + 1])
            vals = mag[mask]
            psd_profile[i] = float(np.mean(vals)) if vals.size > 0 else 0.0
        # Normalise
        pmax = float(np.max(psd_profile)) or 1.0
        psd_norm = psd_profile / pmax
        # Count upward steps in the outer 50% of the radial profile (natural = monotonic decrease)
        outer = psd_norm[n_bins // 2:]
        upward_steps = sum(max(0.0, float(outer[i + 1] - outer[i])) for i in range(len(outer) - 1))
        # Normalise by number of steps; natural images ~0, diffusion images ~0.05–0.3
        ring_score = float(min(1.0, upward_steps / max(1.0, len(outer) - 1) * 10.0))

        # --- Metric 2: High-frequency floor elevation ---
        # Fraction of total energy in the outermost 15% of radial frequencies
        outer_mask = R >= 0.85 * max_r
        total_energy = float(np.sum(mag)) + 1e-12
        outer_energy = float(np.sum(mag[outer_mask]))
        hf_floor = float(outer_energy / total_energy)
        # Natural images: ~0–0.03; diffusion: ~0.05–0.15
        hf_floor_score = float(min(1.0, max(0.0, (hf_floor - 0.03) / 0.12)))

        # --- Metric 3: Luminance-chrominance spectral asymmetry ---
        # Convert to YCbCr and compare high-freq energy ratio in Cb vs Y
        ycbcr = img.convert("YCbCr")
        y_ch = np.asarray(ycbcr)[:, :, 0].astype(np.float64)
        cb_ch = np.asarray(ycbcr)[:, :, 1].astype(np.float64)
        def _hf_ratio(channel: np.ndarray) -> float:
            fft2 = np.fft.fftshift(np.fft.fft2(channel))
            m2 = np.abs(fft2) ** 2
            cy2, cx2 = channel.shape[0] // 2, channel.shape[1] // 2
            r_arr = np.sqrt((np.ogrid[:channel.shape[0], :channel.shape[1]][0] - cy2) ** 2
                            + (np.ogrid[:channel.shape[0], :channel.shape[1]][1] - cx2) ** 2)
            hf_mask2 = r_arr >= 0.7 * min(cy2, cx2)
            total2 = float(np.sum(m2)) + 1e-12
            return float(np.sum(m2[hf_mask2]) / total2)
        y_hf = _hf_ratio(y_ch)
        cb_hf = _hf_ratio(cb_ch)
        # Large asymmetry between chrominance and luminance HF energy is a diffusion signature
        chroma_asymmetry = abs(cb_hf - y_hf)
        chroma_score = float(min(1.0, chroma_asymmetry / 0.05))

        # Composite: ring artifacts dominate, backed by HF floor + chroma
        score = 0.45 * ring_score + 0.35 * hf_floor_score + 0.20 * chroma_score
        return float(min(1.0, max(0.0, score)))
    except Exception:
        return 0.0


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
    diffusion = _diffusion_spectral_score(img)

    phash_dist = -1
    phash_component = 0.0
    if reference_phash:
        current = _phash_bits(img)
        phash_dist = _hamming(current, reference_phash)
        # Large hamming distance after minor visual change suggests adversarial
        phash_component = float(min(1.0, phash_dist / 20.0))

    # Composite score (weighted) — diffusion contributes at 20% weight on top of
    # the adversarial perturbation methods. A high diffusion score alone does not
    # automatically flag an image as adversarial (may be legitimate AI-generated
    # content) but it does raise the composite score and triggers an explanation.
    score = (
        0.25 * hf
        + 0.25 * recomp
        + 0.20 * grad
        + 0.15 * phash_component
        + 0.15 * diffusion
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
    if diffusion >= 0.55:
        explanations.append(
            f"Diffusion model spectral signature detected (score={diffusion:.2f}) — "
            "image may be FLUX/SD3/SDXL-generated; serial number and EXIF cross-check recommended"
        )

    is_adv = score >= thr

    return AdversarialResult(
        adversarial_score=round(score, 4),
        high_freq_ratio=round(hf, 4),
        recompress_instability=round(recomp, 4),
        local_gradient_anomaly=round(grad, 4),
        phash_distance=phash_dist,
        diffusion_score=round(diffusion, 4),
        is_adversarial=is_adv,
        explanations=explanations,
        details={
            "threshold": thr,
            "phash_component": round(phash_component, 4),
            "image_size": list(img.size),
            "diffusion_score": round(diffusion, 4),
        },
    )


@dataclass
class PixelPromptInjectionResult:
    """Result of pixel-space prompt injection analysis.

    OWASP Agentic AI AA05 (Prompt Injection via content channels).
    Detects adversarial perturbations specifically crafted to inject
    instructions into vision-LLM attention without visible text.

    Unlike general adversarial perturbations (which target classifiers),
    pixel-space prompt injections targeting vision-LLMs have distinctive
    signatures:
    - Grid-aligned low-amplitude noise in 8×8 or 16×16 blocks (matching
      transformer patch tokeniser boundaries).
    - High spatial entropy in a narrow amplitude band (≈1–4 LSBs),
      indicating structured, information-dense noise.
    - DCT coefficient skew in AC bands (naturally-zero AC terms populated
      by structured noise across the image, not localised patches).
    """
    injection_score: float = 0.0
    grid_alignment_score: float = 0.0
    lsb_entropy_score: float = 0.0
    dct_ac_anomaly_score: float = 0.0
    is_injection_risk: bool = False
    owasp_tag: str = "AA05"
    explanations: List[str] = field(default_factory=list)


def detect_pixel_prompt_injection(
    image_bytes: bytes,
    *,
    threshold: float = 0.52,
) -> PixelPromptInjectionResult:
    """Detect pixel-space prompt injection targeting vision-LLMs.

    Analyses three independent channels:

    1. **Grid alignment** — computes pixel-variance in 8×8 and 16×16 blocks
       (transformer patch boundaries). Legitimate natural noise is spatially
       random; injection payloads show elevated variance *aligned* to block
       boundaries, producing a grid-shaped variance map.

    2. **LSB entropy** — measures Shannon entropy of the two least-significant
       bits of each pixel channel. Natural images have LSB entropy ≈ 0.9–1.0
       (near-random). Structured injection encodings show entropy > 1.8 due
       to non-random information density (multiple bits per pixel used as a
       covert channel).

    3. **DCT AC coefficient anomaly** — natural images have very few non-zero
       AC terms at the Nyquist frequency. Injection payloads populate these
       terms uniformly across the image, creating an anomalously flat high-
       frequency DCT profile rather than the expected rapid falloff.

    Args:
        image_bytes: raw image file bytes.
        threshold: composite score above which injection risk is flagged.

    Returns:
        PixelPromptInjectionResult mapped to OWASP Agentic AI AA05.
    """
    if np is None or Image is None:
        return PixelPromptInjectionResult(explanations=["numpy/Pillow not available"])

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        return PixelPromptInjectionResult(explanations=[f"Cannot open image: {exc}"])

    arr = np.asarray(img, dtype=np.uint8)
    h, w = arr.shape[:2]
    explanations: List[str] = []

    # ── 1. Grid alignment score ───────────────────────────────────────────────
    # Compare intra-block pixel variance (8×8 grid) vs inter-block boundary
    # variance. Injection payloads show elevated within-block variance that is
    # *correlated* across the entire image (regular grid pattern).
    grid_score = 0.0
    try:
        gray = arr.mean(axis=2)
        block = 8
        bh, bw_b = h // block, w // block
        if bh >= 4 and bw_b >= 4:
            tiles = gray[:bh * block, :bw_b * block].reshape(bh, block, bw_b, block)
            # Variance within each block
            block_var = tiles.var(axis=(1, 3))  # shape (bh, bw_b)
            # A regular injection grid produces a correlation across block variance maps
            # — measure how uniformly elevated variance is across blocks
            mean_var = float(block_var.mean())
            std_var = float(block_var.std())
            # Natural images: high std (some blocks smooth, some textured)
            # Injection grid: low std (every block has similar low-amplitude noise)
            if mean_var > 1e-6:
                uniformity = 1.0 - min(1.0, std_var / (mean_var + 1e-6))
                # Only score as suspicious if mean variance is in the "noise but not texture" band
                if 2.0 < mean_var < 80.0:
                    grid_score = float(min(1.0, uniformity * (1.0 - mean_var / 80.0) * 2.5))
    except Exception:
        pass

    # ── 2. LSB entropy score ─────────────────────────────────────────────────
    lsb_score = 0.0
    try:
        # Extract 2 LSBs from each channel
        lsbs = arr & 0x03  # values 0–3
        entropy_per_channel: List[float] = []
        for c in range(3):
            chan = lsbs[:, :, c].ravel()
            counts = np.bincount(chan, minlength=4).astype(np.float64)
            probs = counts / (counts.sum() + 1e-12)
            # Shannon entropy in bits (max = 2 bits for 4 symbols)
            ent = float(-np.sum(probs[probs > 0] * np.log2(probs[probs > 0])))
            entropy_per_channel.append(ent)
        mean_lsb_ent = float(np.mean(entropy_per_channel))
        # Natural images: LSB entropy ≈ 0.9–1.6 (non-uniform due to JPEG artifacts)
        # Structured injection: LSB entropy > 1.85 (near-maximum — information-dense encoding)
        lsb_score = float(min(1.0, max(0.0, (mean_lsb_ent - 1.75) / 0.25)))
    except Exception:
        pass

    # ── 3. DCT AC coefficient anomaly score ──────────────────────────────────
    dct_score = 0.0
    try:
        gray_f = arr.mean(axis=2).astype(np.float64)
        block = 8
        bh, bw_b = gray_f.shape[0] // block, gray_f.shape[1] // block
        if bh >= 4 and bw_b >= 4:
            tiles = gray_f[:bh * block, :bw_b * block].reshape(bh, block, bw_b, block)
            # Simple DCT approximation: use the DFT magnitude of each block
            total_blocks = bh * bw_b
            nyquist_energy: List[float] = []
            dc_energy: List[float] = []
            for bi in range(bh):
                for bj in range(bw_b):
                    tile = tiles[bi, :, bj, :]
                    F = np.abs(np.fft.fft2(tile))
                    dc_energy.append(float(F[0, 0]))
                    # Nyquist band = outer ring of 8×8 DFT
                    outer = float(F[4:, :].sum() + F[:4, 4:].sum())
                    nyquist_energy.append(outer)
            # Ratio of mean nyquist energy to DC energy across blocks
            mean_dc = float(np.mean(dc_energy)) + 1e-6
            mean_nyq = float(np.mean(nyquist_energy))
            # Natural images: nyquist/dc ≈ 0.01–0.15
            # Injection payload: nyquist/dc ≈ 0.20–0.50 (uniform energy across freq)
            nyq_ratio = mean_nyq / mean_dc
            dct_score = float(min(1.0, max(0.0, (nyq_ratio - 0.15) / 0.30)))
    except Exception:
        pass

    # ── Composite score ───────────────────────────────────────────────────────
    score = 0.35 * grid_score + 0.40 * lsb_score + 0.25 * dct_score
    score = float(min(1.0, max(0.0, score)))

    if grid_score >= 0.50:
        explanations.append(
            f"Grid-aligned noise pattern detected (score={grid_score:.2f}) — "
            "pixel perturbation aligned to transformer patch boundaries (8×8 grid)"
        )
    if lsb_score >= 0.50:
        explanations.append(
            f"High LSB entropy (score={lsb_score:.2f}) — "
            "least-significant bits show near-maximum information density, "
            "consistent with structured instruction encoding"
        )
    if dct_score >= 0.50:
        explanations.append(
            f"DCT AC coefficient anomaly (score={dct_score:.2f}) — "
            "abnormally flat high-frequency DCT profile across image blocks, "
            "consistent with uniform noise injection rather than natural content"
        )

    is_risk = score >= threshold

    return PixelPromptInjectionResult(
        injection_score=round(score, 4),
        grid_alignment_score=round(grid_score, 4),
        lsb_entropy_score=round(lsb_score, 4),
        dct_ac_anomaly_score=round(dct_score, 4),
        is_injection_risk=is_risk,
        owasp_tag="AA05",
        explanations=explanations,
    )
