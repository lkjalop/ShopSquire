"""Tests for enhanced steganography detection — JPEG compat attacks,
SRM features, cross-channel correlation, and metadata stripping."""
from __future__ import annotations

import io
import numpy as np
import pytest
from PIL import Image

from src.app.security.steg_detector import (
    StegResult,
    detect_steganography,
)


def _jpeg_bytes(size=(256, 256), color=(140, 90, 60), quality=88) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


# ---------- JPEG Compatibility Attack Detection (F5/JSteg/OutGuess) ----------

class TestJPEGCompatAttack:
    def test_has_jpeg_compat_fields(self):
        res = detect_steganography(_jpeg_bytes())
        assert hasattr(res, "jpeg_compat_attack_score")
        assert hasattr(res, "jpeg_compat_detail")
        assert isinstance(res.jpeg_compat_detail, dict)
        for key in ("f5", "jsteg", "outguess"):
            assert key in res.jpeg_compat_detail

    def test_solid_jpeg_no_f5_false_positive(self):
        """Solid-color JPEG must not trigger F5 (too few AC coefficients)."""
        res = detect_steganography(_jpeg_bytes())
        assert res.jpeg_compat_detail["f5"] == 0.0

    def test_compat_scores_in_range(self):
        np.random.seed(99)
        noise = np.random.randint(20, 240, (512, 512, 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(noise).save(buf, format="JPEG", quality=75)
        res = detect_steganography(buf.getvalue())
        assert 0.0 <= res.jpeg_compat_attack_score <= 1.0
        for v in res.jpeg_compat_detail.values():
            assert 0.0 <= v <= 1.0


# ---------- SRM Feature Classifier ----------

class TestSRMFeatures:
    def test_has_srm_field(self):
        res = detect_steganography(_jpeg_bytes())
        assert hasattr(res, "srm_feature_score")
        assert 0.0 <= res.srm_feature_score <= 1.0

    def test_uniform_image_low_srm(self):
        """Solid-color image should produce near-zero SRM score."""
        res = detect_steganography(_jpeg_bytes(color=(128, 128, 128)))
        assert res.srm_feature_score < 0.1

    def test_random_noise_low_srm(self):
        """Pure random noise has symmetric residuals → low SRM."""
        np.random.seed(7)
        noise = np.random.randint(0, 255, (256, 256, 3), dtype=np.uint8)
        res = detect_steganography(_png_bytes(noise))
        assert res.srm_feature_score < 0.2


# ---------- Cross-Channel LSB Correlation ----------

class TestCrossChannelCorrelation:
    def test_has_cross_channel_field(self):
        res = detect_steganography(_jpeg_bytes())
        assert hasattr(res, "cross_channel_score")
        assert 0.0 <= res.cross_channel_score <= 1.0

    def test_independent_channels_low_score(self):
        """Channels with independent random LSBs should score low."""
        np.random.seed(12)
        arr = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
        res = detect_steganography(_png_bytes(arr))
        assert res.cross_channel_score < 0.15

    def test_identical_channels_high_score(self):
        """If all three channels are identical, LSB correlation should be 1.0."""
        np.random.seed(33)
        mono = np.random.randint(60, 200, (128, 128), dtype=np.uint8)
        arr = np.stack([mono, mono, mono], axis=-1)
        res = detect_steganography(_png_bytes(arr))
        assert res.cross_channel_score > 0.5


# ---------- Metadata Stripping Validation ----------

class TestMetadataStripping:
    def test_has_metadata_fields(self):
        res = detect_steganography(_jpeg_bytes())
        assert hasattr(res, "metadata_stripped")
        assert hasattr(res, "metadata_strip_score")
        assert isinstance(res.metadata_stripped, bool)

    def test_synthetic_image_stripped(self):
        """PIL-generated images have no EXIF → should flag as stripped."""
        res = detect_steganography(_jpeg_bytes())
        assert res.metadata_stripped is True

    def test_large_png_no_meta_high_score(self):
        """Large PNG without metadata should get elevated strip score."""
        np.random.seed(42)
        arr = np.random.randint(0, 255, (1920, 1080, 3), dtype=np.uint8)
        res = detect_steganography(_png_bytes(arr))
        assert res.metadata_stripped is True
        assert res.metadata_strip_score >= 0.5

    def test_small_image_low_strip_score(self):
        """Small thumbnails without metadata should barely flag."""
        res = detect_steganography(_jpeg_bytes(size=(32, 32)))
        assert res.metadata_strip_score <= 0.3


# ---------- Composite / Integration ----------

class TestComposite:
    def test_clean_solid_not_suspicious(self):
        res = detect_steganography(_jpeg_bytes())
        assert not res.is_suspicious

    def test_composite_weights_sum_to_1(self):
        res = detect_steganography(_jpeg_bytes())
        weights = res.details.get("composite_weights", {})
        assert abs(sum(weights.values()) - 1.0) < 0.01

    def test_all_new_fields_in_result(self):
        res = detect_steganography(_jpeg_bytes())
        for attr in (
            "jpeg_compat_attack_score", "jpeg_compat_detail",
            "srm_feature_score", "cross_channel_score",
            "metadata_stripped", "metadata_strip_score",
        ):
            assert hasattr(res, attr), f"Missing: {attr}"
