import time
from io import BytesIO

import pytest

from PIL import Image, ImageFilter

from src.app.services.image_forensics import ImageForensicsService


def make_image(size=(256, 256), color=(180, 180, 180)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def splice_image(base: Image.Image) -> bytes:
    img = base.copy()
    w, h = img.size
    patch = Image.new("RGB", (w // 4, h // 4), (250, 20, 20))
    img.paste(patch, (w // 3, h // 3))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def copy_move_image(base: Image.Image) -> bytes:
    img = base.copy()
    w, h = img.size
    patch = Image.new("RGB", (w // 6, h // 6), (20, 250, 20))
    img.paste(patch, (w // 6, h // 6))
    img.paste(patch, (w // 2, h // 2))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def blurry_image(base: Image.Image) -> bytes:
    img = base.copy().filter(ImageFilter.GaussianBlur(radius=4))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def test_clean_image_low_manipulation():
    svc = ImageForensicsService()
    b = make_image()
    res = svc.analyze(b)
    assert res.manipulation_score <= 0.4
    assert res.splice_score <= 0.5
    assert res.copy_move_score <= 0.4
    assert "ahash" in res.hashes and "phash" in res.hashes and len(res.hashes["ahash"]) == 64


def test_splice_raises_splice_score():
    svc = ImageForensicsService()
    base = Image.new("RGB", (320, 320), (180, 180, 180))
    b = splice_image(base)
    res = svc.analyze(b)
    # Heuristic: splice present -> splice_score noticeable
    assert res.splice_score >= 0.4
    # If area large enough, mask present
    area_ratio = 0.0
    if res.masks.get("ela"):
        w, h = 320, 320
        for b in res.masks["ela"]:
            area_ratio += ((b["max_x"] - b["min_x"]) * (b["max_y"] - b["min_y"])) / (w * h)
    assert area_ratio >= 0.02


def test_copy_move_detection():
    svc = ImageForensicsService()
    base = Image.new("RGB", (360, 360), (128, 128, 128))
    b = copy_move_image(base)
    res = svc.analyze(b)
    assert res.copy_move_score >= 0.4
    assert len(res.masks.get("copy_move", [])) >= 1


def test_blur_detection():
    svc = ImageForensicsService()
    base = Image.new("RGB", (256, 256), (160, 160, 160))
    b = blurry_image(base)
    res = svc.analyze(b)
    assert res.blur_score >= 0.4


@pytest.mark.parametrize("resize", [(1.0), (0.9), (1.1)])
@pytest.mark.parametrize("quality", [85, 92])
def test_resave_resize_invariance(resize, quality):
    svc = ImageForensicsService()
    base = Image.new("RGB", (256, 256), (180, 180, 180))
    sp = splice_image(base)
    img = Image.open(BytesIO(sp)).convert("RGB")
    new_size = (max(32, int(img.width * resize)), max(32, int(img.height * resize)))
    img2 = img.resize(new_size)
    buf = BytesIO()
    img2.save(buf, format="JPEG", quality=quality)
    res = svc.analyze(buf.getvalue())
    assert res.splice_score >= 0.3


def test_performance_small_image_under_threshold():
    svc = ImageForensicsService()
    base = Image.new("RGB", (640, 360), (180, 180, 180))
    b = splice_image(base)
    t0 = time.time()
    _ = svc.analyze(b)
    elapsed_ms = (time.time() - t0) * 1000
    assert elapsed_ms < 700, f"Forensics took too long: {elapsed_ms:.2f}ms"
