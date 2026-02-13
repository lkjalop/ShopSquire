import pytest
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult
from PIL import Image
import io


def make_test_image(size=(256, 256), color=(120, 150, 200)):
    img = Image.new("RGB", size, color)
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=95)
    return b.getvalue()


def test_analyze_returns_forensics_result():
    svc = ImageForensicsService()
    img_bytes = make_test_image()
    res = svc.analyze(img_bytes)
    assert isinstance(res, ForensicsResult)
    # required numeric fields
    for f in ("manipulation_score", "splice_score", "copy_move_score", "double_compress_score", "blur_score"):
        v = getattr(res, f)
        assert isinstance(v, float)
        assert 0.0 <= v <= 1.0
    # masks and hashes present
    assert isinstance(res.masks, dict)
    assert isinstance(res.hashes, dict)


def test_analyze_image_backward_compat_wrapper():
    svc = ImageForensicsService()
    img_bytes = make_test_image()
    d = svc.analyze_image(img_bytes)
    # old wrapper returns dict with expected keys
    expected = [
        "manipulation_score",
        "splice_score",
        "copy_move_score",
        "double_compress_score",
        "blur_score",
        "metadata",
        "masks",
        "hashes",
    ]
    for k in expected:
        assert k in d
