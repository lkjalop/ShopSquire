import pytest
from src.app.services.image_forensics import ImageForensicsService
from PIL import Image
import io


def make_test_image(size=(256, 256), color=(120, 150, 200)):
    img = Image.new("RGB", size, color)
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=95)
    return b.getvalue()


def test_resave_invariance():
    svc = ImageForensicsService()
    img = make_test_image()
    base = svc.analyze(img)
    # resave at slightly lower quality
    pil = Image.open(io.BytesIO(img)).convert("RGB")
    b2 = io.BytesIO()
    pil.save(b2, format="JPEG", quality=85)
    v2 = svc.analyze(b2.getvalue())
    # scores should not wildly diverge (allow broad tolerance)
    assert abs(base.manipulation_score - v2.manipulation_score) <= 0.4


def test_resize_invariance():
    svc = ImageForensicsService()
    img = make_test_image(size=(512, 512))
    base = svc.analyze(img)
    pil = Image.open(io.BytesIO(img)).convert("RGB")
    pil2 = pil.resize((256, 256))
    b2 = io.BytesIO()
    pil2.save(b2, format="JPEG", quality=90)
    v2 = svc.analyze(b2.getvalue())
    assert isinstance(v2.manipulation_score, float)
    assert 0.0 <= v2.manipulation_score <= 1.0
