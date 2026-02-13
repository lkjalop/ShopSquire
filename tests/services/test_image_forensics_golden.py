import io
from PIL import Image, ImageDraw
import pytest
from src.app.services.image_forensics import ImageForensicsService, ForensicsResult


def make_base_image(size=(256, 256), color=(120, 150, 200)):
    img = Image.new("RGB", size, color)
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=95)
    return b.getvalue()


def make_spliced_image(size=(256, 256), color=(120, 150, 200)):
    pil = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(pil)
    # draw a pasted/spliced rectangle (synthetic manipulation)
    rect = (60, 60, 160, 160)
    draw.rectangle(rect, fill=(10, 200, 10))
    b = io.BytesIO()
    pil.save(b, format="JPEG", quality=95)
    return b.getvalue()


def test_splice_detected_by_score():
    svc = ImageForensicsService()
    orig = make_base_image()
    splice = make_spliced_image()

    r1 = svc.analyze(orig)
    r2 = svc.analyze(splice)

    assert isinstance(r1, ForensicsResult)
    assert isinstance(r2, ForensicsResult)
    # manipulation_score should increase for the spliced image
    assert r2.manipulation_score >= r1.manipulation_score
    # expect a meaningful gap for this synthetic splice
    assert (r2.manipulation_score - r1.manipulation_score) >= 0.05
