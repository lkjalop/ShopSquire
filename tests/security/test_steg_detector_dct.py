from __future__ import annotations

import io

from src.app.security.steg_detector import detect_steganography


def _jpeg_bytes() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (128, 128), color=(140, 90, 60))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def test_steg_detector_emits_dct_scores_for_jpeg():
    res = detect_steganography(_jpeg_bytes())
    assert hasattr(res, "dct_anomaly_score")
    assert hasattr(res, "jpeg_quant_table_score")
    assert 0.0 <= float(res.dct_anomaly_score) <= 1.0
    assert 0.0 <= float(res.jpeg_quant_table_score) <= 1.0
