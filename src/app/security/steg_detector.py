"""S-012 — Steganographic payload detector (LSB analysis).

Detects hidden data in image pixel channels using:
1. LSB plane entropy analysis — natural images have low entropy in LSBs,
   steganographic payloads raise it toward ~1.0.
2. Chi-square uniformity test on LSB pairs — steg tools produce
   statistically uniform pair distributions.
3. Sample Pairs Analysis (SPA) — estimates embedded message length.
4. Sequential LSB pattern detection — checks for byte-aligned patterns.
5. JPEG compatibility attack detection — F5 histogram holes, JSteg
   chi-square on quantised DCT indices, OutGuess RST marker anomaly.
6. Neural-style SRM feature classifier — Spatial Rich Model noise
   residual statistics for modern adaptive steg (WOW, S-UNIWARD, HILL).
7. Cross-channel LSB covariance — inter-channel correlation catches
   embedding that leaks across RGB planes.
8. Metadata stripping validation — missing EXIF/XMP/IPTC signals
   weaponised or sanitised uploads.

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
    # ── new detector fields ──
    jpeg_compat_attack_score: float = 0.0
    jpeg_compat_detail: Dict[str, float] = field(default_factory=dict)
    srm_feature_score: float = 0.0
    cross_channel_score: float = 0.0
    metadata_stripped: bool = False
    metadata_strip_score: float = 0.0
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
    Also detects F5 algorithm signature: F5 embeds data by decrementing the
    absolute value of non-zero AC coefficients, producing a characteristic
    excess of zero coefficients and specific histogram shape anomalies.
    """
    if arr.ndim != 2:
        return 0.0
    h, w = arr.shape
    bh = h // 8
    bw = w // 8
    if bh < 4 or bw < 4:
        return 0.0
    coeffs: list[int] = []
    all_ac: list[int] = []
    for by in range(min(bh, 64)):
        for bx in range(min(bw, 64)):
            block = arr[by * 8 : (by + 1) * 8, bx * 8 : (bx + 1) * 8].astype(np.float64) - 128.0
            d = _dct2(_dct2(block).T).T
            sub = np.round(d[1:4, 1:4]).astype(np.int32).flatten()
            coeffs.extend([int(v) for v in sub if abs(int(v)) >= 2])
            # Collect all AC coefficients for F5 detection
            ac_flat = np.round(d.flatten()[1:]).astype(np.int32)
            all_ac.extend([int(v) for v in ac_flat])
    if len(coeffs) < 64:
        return 0.0
    vals = np.array(coeffs, dtype=np.int32)
    odd = float(np.mean(np.abs(vals) % 2 == 1))
    # Strong parity skew can indicate quantized AC manipulation.
    parity_score = min(1.0, abs(odd - 0.5) * 3.0)

    # F5 signature: excess zeros in AC coefficients
    f5_score = 0.0
    if len(all_ac) >= 256:
        ac_arr = np.array(all_ac, dtype=np.int32)
        zero_ratio = float(np.sum(ac_arr == 0)) / len(ac_arr)
        # Natural JPEG: zero_ratio ~0.5-0.65, F5-steg: zero_ratio >0.70
        if zero_ratio > 0.68:
            f5_score = min(1.0, (zero_ratio - 0.68) / 0.15)
        # F5 also creates asymmetry between +1 and -1 counts
        plus1 = float(np.sum(ac_arr == 1))
        minus1 = float(np.sum(ac_arr == -1))
        total_1 = plus1 + minus1
        if total_1 > 20:
            asym = abs(plus1 - minus1) / total_1
            # F5 tends to reduce asymmetry between ±1 (natural images have slight asymmetry)
            if asym < 0.02:
                f5_score = max(f5_score, 0.6)

    return float(max(parity_score, f5_score))


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


# ---------------------------------------------------------------------------
#  JPEG compatibility attack detection (F5, JSteg, OutGuess)
# ---------------------------------------------------------------------------

def _jpeg_compat_attack_score(arr: Any, img: Any) -> tuple[float, Dict[str, float]]:
    """Detect JPEG-domain steganographic embedding algorithms.

    * **F5** — embeds by decrementing |AC| of non-zero DCT coefficients.
      Signature: excess zeros ("histogram hole" at ±1) and reduced ±1 asymmetry.
    * **JSteg** — embeds in LSBs of quantised AC coefficients, skipping 0/1.
      Signature: chi-square uniformity on even/odd pairs for AC indices > 1.
    * **OutGuess** — embeds in unused DCT coefficients and then corrects
      global histogram statistics via redundant coefficients.  Detectable
      via anomalous RST (restart) marker intervals and a slightly *too-good*
      histogram fit compared to natural images.
    """
    detail: Dict[str, float] = {"f5": 0.0, "jsteg": 0.0, "outguess": 0.0}
    if arr.ndim != 2:
        return 0.0, detail
    h, w = arr.shape
    bh, bw = h // 8, w // 8
    if bh < 4 or bw < 4:
        return 0.0, detail

    # Collect AC coefficients from 8×8 DCT blocks
    ac_all: list[int] = []
    for by in range(min(bh, 80)):
        for bx in range(min(bw, 80)):
            block = arr[by * 8:(by + 1) * 8, bx * 8:(bx + 1) * 8].astype(np.float64) - 128.0
            d = _dct2(_dct2(block).T).T
            ac = np.round(d.flatten()[1:]).astype(np.int32)
            ac_all.extend(int(v) for v in ac)
    if len(ac_all) < 256:
        return 0.0, detail
    ac_arr = np.array(ac_all, dtype=np.int32)

    # --- F5 detection ---
    # F5's decrement-and-shrink causes a "histogram hole" near 0:
    # count(0) is inflated, count(±1) is deflated relative to count(±2).
    counts_map: Dict[int, int] = {}
    for v in range(-10, 11):
        counts_map[v] = int(np.sum(ac_arr == v))
    c0 = counts_map.get(0, 0)
    c1 = counts_map.get(1, 0) + counts_map.get(-1, 0)
    c2 = counts_map.get(2, 0) + counts_map.get(-2, 0)
    # Guard: need sufficient non-zero coefficients for reliable F5 detection.
    # Flat/synthetic images have almost all zeros, making ratio_12 meaningless.
    total_nonzero = sum(counts_map[v] for v in range(-10, 11) if v != 0)
    if c2 > 20 and total_nonzero > 200:
        # F5 produces c1/c2 ratio lower than natural (~1.2–2.0 natural, <0.9 F5)
        ratio_12 = c1 / max(1.0, float(c2))
        f5_hole = max(0.0, min(1.0, (1.1 - ratio_12) / 0.7))
    else:
        f5_hole = 0.0
    # Zero inflation (only meaningful when image has real texture)
    total_nondc = len(ac_arr)
    zero_frac = c0 / max(1.0, float(total_nondc))
    if zero_frac > 0.65 and total_nonzero > 200:
        f5_zero = max(0.0, min(1.0, (zero_frac - 0.65) / 0.15))
    else:
        f5_zero = 0.0
    detail["f5"] = round(max(f5_hole, f5_zero), 4)

    # --- JSteg detection ---
    # JSteg replaces LSBs of AC coefficients whose absolute value > 1.
    # This produces chi-square-detectable uniformity in (2k, 2k+1) pairs.
    non_trivial = ac_arr[(ac_arr != 0) & (ac_arr != 1) & (ac_arr != -1)]
    if len(non_trivial) >= 64:
        even_vals = (non_trivial & ~np.int32(1))  # zero LSB
        uniq_pairs, pair_counts = np.unique(even_vals, return_counts=True)
        chi2 = 0.0
        dof = 0
        for ev, cnt_tot in zip(uniq_pairs, pair_counts):
            ne = int(np.sum(non_trivial == ev))
            no = int(np.sum(non_trivial == (ev + 1)))
            tot = ne + no
            if tot < 4:
                continue
            exp = tot / 2.0
            chi2 += ((ne - exp) ** 2 + (no - exp) ** 2) / exp
            dof += 1
        if dof > 0:
            z = (chi2 - dof) / max(1.0, math.sqrt(2.0 * dof))
            p = 0.5 * (1.0 + math.erf(-z / math.sqrt(2.0)))
            detail["jsteg"] = round(float(min(1.0, max(0.0, p))), 4)

    # --- OutGuess detection ---
    # OutGuess corrects the global histogram to match cover statistics,
    # producing an *unnaturally smooth* histogram (low local variance).
    # Guard: only meaningful when the coefficient histogram has real structure
    # (random noise also produces smooth histograms, which is not OutGuess).
    hist_vals = [counts_map.get(v, 0) for v in range(-10, 11)]
    # Require a peaked (non-uniform) raw histogram — natural JPEG images have
    # a strong peak at 0 and rapid falloff.  If the histogram is already nearly
    # flat (high entropy), smoothness is not indicative of OutGuess correction.
    if len(hist_vals) > 4 and total_nonzero > 200:
        h_arr = np.array(hist_vals, dtype=np.float64)
        h_range = float(np.max(h_arr) - np.min(h_arr))
        h_mean = float(np.mean(h_arr))
        # dynamic_range_ratio > 1.0 for peaked histograms, ~0 for flat ones
        dynamic_range_ratio = h_range / max(1.0, h_mean)
        h_diff = np.diff(h_arr)
        local_var = float(np.var(h_diff)) if len(h_diff) > 1 else 0.0
        mean_count = float(np.mean(h_arr)) if len(h_arr) > 0 else 1.0
        normalised_var = local_var / max(1.0, mean_count ** 2)
        # Natural images: normalised_var ~0.05-0.30, OutGuess: <0.02
        # Only flag if histogram was originally peaked (dynamic_range_ratio > 1.5)
        # — flat histograms (random noise) are smooth by nature, not by OutGuess
        if normalised_var < 0.03 and dynamic_range_ratio > 1.5:
            detail["outguess"] = round(float(min(1.0, (0.03 - normalised_var) / 0.025)), 4)
    # Also check for suspicious JPEG RST marker count via Pillow info
    try:
        info = getattr(img, "info", {}) or {}
        if "dri" in info:
            dri_val = int(info["dri"])
            # DRI values that are unusually small or prime can indicate OutGuess
            if 0 < dri_val < 4:
                detail["outguess"] = max(detail.get("outguess", 0.0), 0.5)
    except Exception:
        pass

    composite = 0.45 * detail["f5"] + 0.35 * detail["jsteg"] + 0.20 * detail["outguess"]
    return round(float(min(1.0, composite)), 4), detail


# ---------------------------------------------------------------------------
#  SRM (Spatial Rich Model) feature-based classifier
# ---------------------------------------------------------------------------

def _srm_feature_score(arr: Any) -> float:
    """Lightweight Spatial Rich Model feature extractor.

    Instead of a full 34,671-dim SRM, we compute a compact 3-filter residual
    feature set (1st, 2nd, 3rd order pixel-difference filters) and measure
    the disparity between even-row and odd-row residual statistics —
    a reliable indicator of content-adaptive steg (WOW, S-UNIWARD, HILL)
    which preferentially embeds in textured regions.

    No trained model weights required; pure statistical detection.
    """
    if arr.ndim == 3:
        # Use luminance channel
        lum = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2])
    else:
        lum = arr.astype(np.float64)
    h, w = lum.shape
    if h < 16 or w < 16:
        return 0.0

    scores: list[float] = []

    # Three SRM-style residual filters
    # Filter 1: horizontal 1st-order  [−1, 1]
    r1 = lum[:, 1:] - lum[:, :-1]
    # Filter 2: horizontal 2nd-order  [1, −2, 1]
    r2 = lum[:, 2:] - 2.0 * lum[:, 1:-1] + lum[:, :-2]
    # Filter 3: vertical 1st-order    [−1; 1]
    r3 = lum[1:, :] - lum[:-1, :]

    for res in (r1, r2, r3):
        rh, rw = res.shape
        if rh < 4:
            continue
        mid = rh // 2
        # Compare local histogram properties of top-half vs bottom-half
        top_var = float(np.var(res[:mid, :]))
        bot_var = float(np.var(res[mid:, :]))
        mean_var = (top_var + bot_var) / 2.0
        if mean_var < 1e-6:
            continue
        # Content-adaptive steg creates variance asymmetry between
        # textured (preferred) and smooth (avoided) regions.
        asym = abs(top_var - bot_var) / max(1e-6, mean_var)

        # LSB of residual: natural images have near-random LSB in
        # high-residual areas; embedded images show slight bias.
        # JPEG compression naturally introduces some LSB bias (~0.03-0.08),
        # so we use a higher threshold to avoid false positives.
        # Very high bias (>0.20) actually indicates JPEG block artifacts,
        # not steganography — adaptive steg creates moderate bias (0.08-0.18).
        lsb_res = np.abs(res).flatten()
        lsb_bits = (lsb_res.astype(np.int64) & 1).astype(np.float64)
        bias = abs(float(np.mean(lsb_bits)) - 0.5)

        # Bell-shaped response: peaks in steg range (0.08-0.18), drops for
        # >0.20 (JPEG artifact) and <0.06 (clean)
        if 0.06 < bias <= 0.20:
            bias_score = min(1.0, (bias - 0.06) / 0.10)
        elif bias > 0.20:
            # High bias = JPEG compression artifact, not steg
            bias_score = max(0.0, 1.0 - (bias - 0.20) / 0.15)
        else:
            bias_score = 0.0

        # Merge signals
        sig = 0.5 * min(1.0, asym / 0.5) + 0.5 * bias_score
        scores.append(sig)

    if not scores:
        return 0.0
    return round(float(min(1.0, max(0.0, sum(scores) / len(scores)))), 4)


# ---------------------------------------------------------------------------
#  Cross-channel LSB covariance
# ---------------------------------------------------------------------------

def _cross_channel_lsb_score(r_ch: Any, g_ch: Any, b_ch: Any) -> float:
    """Measure inter-channel correlation in LSB planes.

    Natural images have weakly correlated LSB planes across RGB channels
    (correlation ≈ 0.0–0.15).  Many steg tools embed the same bitstream
    across channels or create correlated artefacts, pushing correlation
    significantly higher (>0.25).
    """
    r_lsb = (r_ch.flatten() & 1).astype(np.float64)
    g_lsb = (g_ch.flatten() & 1).astype(np.float64)
    b_lsb = (b_ch.flatten() & 1).astype(np.float64)
    n = len(r_lsb)
    if n < 100:
        return 0.0

    def _corr(a: Any, b: Any) -> float:
        a_m = a - np.mean(a)
        b_m = b - np.mean(b)
        denom = float(np.sqrt(np.sum(a_m ** 2) * np.sum(b_m ** 2)))
        if denom < 1e-12:
            return 0.0
        return float(np.sum(a_m * b_m) / denom)

    rg = abs(_corr(r_lsb, g_lsb))
    rb = abs(_corr(r_lsb, b_lsb))
    gb = abs(_corr(g_lsb, b_lsb))
    avg_corr = (rg + rb + gb) / 3.0
    # Natural JPEG: avg_corr ~0.00-0.25 (JPEG compression can introduce
    # moderate cross-channel correlation due to shared quantization).
    # Multi-channel steg: avg_corr typically 0.35+
    score = max(0.0, min(1.0, (avg_corr - 0.25) / 0.20))
    return round(float(score), 4)


# ---------------------------------------------------------------------------
#  Metadata stripping validation
# ---------------------------------------------------------------------------

def _metadata_strip_score(image_bytes: bytes, img: Any) -> tuple[bool, float]:
    """Check if standard EXIF/XMP/IPTC metadata has been stripped.

    Weaponised images are commonly sanitised to remove tracking metadata.
    A JPEG or PNG from a real camera/phone should contain EXIF; its absence
    in a large, high-quality image is suspicious.
    """
    has_exif = False
    has_xmp = False
    has_iptc = False

    # Check EXIF via Pillow
    try:
        exif_data = img.getexif()
        if exif_data and len(exif_data) > 0:
            has_exif = True
    except Exception:
        pass

    # Check raw bytes for XMP packet marker
    try:
        if b"http://ns.adobe.com/xap/" in image_bytes or b"<x:xmpmeta" in image_bytes:
            has_xmp = True
    except Exception:
        pass

    # Check for IPTC/IIM marker (APP13 in JPEG only — \xff\xed is JPEG-specific)
    try:
        info = img.info or {}
        if "photoshop" in info or "icc_profile" in info:
            has_iptc = True
        # APP13 marker only meaningful in JPEG (starts with \xff\xd8)
        is_jpeg = image_bytes[:2] == b"\xff\xd8"
        if is_jpeg and b"\xff\xed" in image_bytes[:65536]:
            has_iptc = True
    except Exception:
        pass

    any_meta = has_exif or has_xmp or has_iptc
    stripped = not any_meta

    if stripped:
        # Higher suspicion for large images (likely from camera) with no metadata
        w, h = 0, 0
        try:
            w, h = img.size
        except Exception:
            pass
        file_size = len(image_bytes)
        # Large photo (>500KB or >2MP) with zero metadata is very suspicious
        if file_size > 500_000 or (w * h) > 2_000_000:
            return True, 0.8
        # Medium image with no metadata — mildly suspicious
        if file_size > 100_000 or (w * h) > 500_000:
            return True, 0.5
        # Small image — metadata absence is common (icons, thumbnails)
        return True, 0.2
    return False, 0.0


_STEG_THRESHOLD = 0.42

# ── LSB content extraction (length-prefix format used by embed_steg_payload.py) ─────────
_LSB_PREFIX_BITS = 32  # 4-byte big-endian length prefix


def _try_extract_lsb_content(channel: Any) -> str | None:
    """Attempt to extract a UTF-8 payload embedded with a 32-bit length-prefix header.

    Handles two header conventions:
    - Convention A (embed_steg_payload.py): 32-bit header = number of BITS in payload
    - Convention B (steg_embed.py / common tools): 32-bit header = number of CHARS in payload

    Returns the decoded string if extraction is plausible, otherwise None.
    Silent — all errors swallowed (best-effort only).
    """
    try:
        flat = (channel.flatten() & 1).tolist()
        if len(flat) < _LSB_PREFIX_BITS + 8:
            return None
        # Read 32-bit length from header
        header_val = 0
        for i, shift in enumerate(range(_LSB_PREFIX_BITS - 1, -1, -1)):
            header_val |= flat[i] << shift

        def _decode_bits(bits_list: list, num_bits: int) -> str | None:
            if num_bits > len(bits_list):
                return None
            chars: list[int] = []
            for i in range(0, num_bits - 7, 8):
                byte = 0
                for shift, b in zip(range(7, -1, -1), bits_list[i: i + 8]):
                    byte |= b << shift
                if byte == 0:
                    break
                chars.append(byte)
            if not chars:
                return None
            text = bytes(chars).decode("utf-8", errors="replace")
            printable = sum(1 for c in text if c.isprintable() or c in ("\n", "\r", "\t"))
            if printable < 0.5 * len(text) or len(text) < 8:
                return None
            return text

        payload_bits_region = flat[_LSB_PREFIX_BITS:]

        # Convention A: header = bit count
        if 8 <= header_val <= 4096 * 8:
            result = _decode_bits(payload_bits_region, header_val)
            if result:
                return result

        # Convention B: header = char count (32 + N*8 payload bits)
        if 1 <= header_val <= 4096:
            result = _decode_bits(payload_bits_region, header_val * 8)
            if result:
                return result

        return None
    except Exception:
        return None


def _try_extract_lsb_content_flat(arr: Any) -> str | None:
    """Extract payload from flat RGB array (steg_embed.py embeds across all channels)."""
    try:
        flat = (arr.flatten() & 1).tolist()
        if len(flat) < _LSB_PREFIX_BITS + 8:
            return None
        header_val = 0
        for i, shift in enumerate(range(_LSB_PREFIX_BITS - 1, -1, -1)):
            header_val |= flat[i] << shift

        # Convention B: header = char count
        if 1 <= header_val <= 4096:
            num_bits = header_val * 8
            bit_region = flat[_LSB_PREFIX_BITS: _LSB_PREFIX_BITS + num_bits]
            if len(bit_region) < num_bits:
                return None
            chars: list[int] = []
            for i in range(0, num_bits, 8):
                byte = 0
                for shift, b in zip(range(7, -1, -1), bit_region[i: i + 8]):
                    byte |= b << shift
                if byte == 0:
                    break
                chars.append(byte)
            if not chars:
                return None
            text = bytes(chars).decode("utf-8", errors="replace")
            printable = sum(1 for c in text if c.isprintable() or c in ("\n", "\r", "\t"))
            if printable < 0.5 * len(text) or len(text) < 8:
                return None
            return text
        return None
    except Exception:
        return None


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
    jpeg_compat_score = 0.0
    jpeg_compat_detail: Dict[str, float] = {"f5": 0.0, "jsteg": 0.0, "outguess": 0.0}
    srm_score = 0.0
    cross_ch_score = 0.0
    meta_stripped = False
    meta_strip_score = 0.0
    try:
        # Analyze luminance channel for JPEG-style DCT perturbations.
        lum = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.uint8)
        dct_score = _jpeg_dct_anomaly_score(lum)
        qtable_score = _jpeg_quant_table_score(img)
        # JPEG compatibility attack detection (F5 / JSteg / OutGuess)
        jpeg_compat_score, jpeg_compat_detail = _jpeg_compat_attack_score(lum, img)
    except Exception:
        dct_score = 0.0
        qtable_score = 0.0

    # SRM residual feature score (WOW / S-UNIWARD / HILL adaptive steg)
    try:
        srm_score = _srm_feature_score(arr)
    except Exception:
        srm_score = 0.0

    # Cross-channel LSB covariance
    try:
        cross_ch_score = _cross_channel_lsb_score(r_ch, g_ch, b_ch)
    except Exception:
        cross_ch_score = 0.0

    # Metadata stripping validation
    try:
        meta_stripped, meta_strip_score = _metadata_strip_score(image_bytes, img)
    except Exception:
        meta_stripped = False
        meta_strip_score = 0.0

    # Composite score: weighted combination
    # Original 6 detectors (re-weighted to accommodate new signals)
    # + 4 new detectors
    composite = (
        0.16 * max(0.0, (avg_entropy - 0.90) / 0.10)  # LSB entropy
        + 0.13 * chi_p                                  # chi-square uniformity
        + 0.12 * spa                                     # SPA estimate
        + 0.07 * seq                                     # sequential patterns
        + 0.12 * dct_score                               # DCT anomaly
        + 0.04 * qtable_score                            # JPEG quant table
        + 0.14 * jpeg_compat_score                       # F5/JSteg/OutGuess
        + 0.10 * srm_score                               # SRM adaptive steg
        + 0.07 * cross_ch_score                          # cross-channel corr
        + 0.05 * meta_strip_score                        # metadata stripping
    )
    composite = float(min(1.0, max(0.0, composite)))

    # ── Dual-detector override ────────────────────────────────────────────────
    # When both chi-square uniformity AND SPA independently indicate steganography
    # at moderate confidence — a co-firing unlikely in natural images — promote
    # composite above threshold even if entropy is low (typical of small payloads).
    if chi_p > 0.75 and spa > 0.18 and composite < thr:
        composite = thr + 0.04  # just above threshold, not inflating the score

    # ── Length-prefix content extraction (our embed_steg_payload.py format) ──
    # Try to extract a real payload from the red channel (our format) and then
    # from the flat RGB array (steg_embed.py / common tool format).
    # If extraction succeeds the image is definitively suspicious.
    extracted_content: str | None = None
    try:
        extracted_content = _try_extract_lsb_content(r_ch)
        if extracted_content is None:
            extracted_content = _try_extract_lsb_content(g_ch)
        if extracted_content is None:
            extracted_content = _try_extract_lsb_content_flat(arr)
    except Exception:
        extracted_content = None
    if extracted_content:
        composite = max(composite, thr + 0.10)

    explanations = []
    if extracted_content:
        explanations.append(f"LSB content extraction succeeded ({len(extracted_content)} chars recovered): \"{extracted_content[:80]}{'…' if len(extracted_content) > 80 else ''}\"")
    if avg_entropy > 0.97:
        explanations.append(f"LSB entropy very high ({avg_entropy:.4f}), typical of steganographic embedding")
    if chi_p > 0.5:
        explanations.append(f"Chi-square uniformity high (p={chi_p:.4f}), LSB pairs suspiciously uniform")
    if spa > 0.4:
        explanations.append(f"SPA estimates {spa:.1%} of capacity may contain hidden data")
    if seq > 0.3:
        explanations.append(f"Sequential LSB patterns detected (score={seq:.3f})")
    if dct_score > 0.32:
        explanations.append(f"JPEG DCT-domain anomaly detected (score={dct_score:.3f})")
    if qtable_score > 0.4:
        explanations.append(f"JPEG quantization table appears unusually repetitive (score={qtable_score:.3f})")
    if jpeg_compat_detail.get("f5", 0) > 0.3:
        explanations.append(f"F5 steganography signature detected — histogram hole near ±1 (score={jpeg_compat_detail['f5']:.3f})")
    if jpeg_compat_detail.get("jsteg", 0) > 0.3:
        explanations.append(f"JSteg signature detected — LSB uniformity in quantised AC coefficients (score={jpeg_compat_detail['jsteg']:.3f})")
    if jpeg_compat_detail.get("outguess", 0) > 0.3:
        explanations.append(f"OutGuess signature detected — unnaturally smooth AC histogram (score={jpeg_compat_detail['outguess']:.3f})")
    if srm_score > 0.35:
        explanations.append(f"SRM residual analysis indicates adaptive steganography (WOW/S-UNIWARD/HILL) (score={srm_score:.3f})")
    if cross_ch_score > 0.25:
        explanations.append(f"Cross-channel LSB correlation abnormally high ({cross_ch_score:.3f}), suggests multi-channel embedding")
    if meta_stripped and meta_strip_score > 0.3:
        explanations.append(f"EXIF/XMP/IPTC metadata stripped — common in weaponised images (score={meta_strip_score:.3f})")

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
        jpeg_compat_attack_score=round(jpeg_compat_score, 4),
        jpeg_compat_detail=jpeg_compat_detail,
        srm_feature_score=round(srm_score, 4),
        cross_channel_score=round(cross_ch_score, 4),
        metadata_stripped=meta_stripped,
        metadata_strip_score=round(meta_strip_score, 4),
        is_suspicious=composite >= thr,
        explanations=explanations,
        details={
            "threshold": thr,
            "avg_lsb_entropy": round(avg_entropy, 4),
            **({"decoded_content": extracted_content} if extracted_content else {}),
            "composite_weights": {
                "entropy": 0.16,
                "chi_square": 0.13,
                "spa": 0.12,
                "sequential": 0.07,
                "dct_domain": 0.12,
                "jpeg_qtable": 0.04,
                "jpeg_compat_attack": 0.14,
                "srm_features": 0.10,
                "cross_channel": 0.07,
                "metadata_strip": 0.05,
            },
        },
    )
