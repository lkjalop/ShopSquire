import io
from PIL import Image, ImageDraw
import pytest


def _make_base(size=(256, 256), color=(120, 150, 200), quality=95):
    img = Image.new("RGB", size, color)
    b = io.BytesIO()
    img.save(b, format="JPEG", quality=quality)
    return b.getvalue()


def _make_spliced(size=(256, 256), color=(120, 150, 200)):
    pil = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(pil)
    rect = (60, 60, 160, 160)
    draw.rectangle(rect, fill=(10, 200, 10))
    b = io.BytesIO()
    pil.save(b, format="JPEG", quality=95)
    return b.getvalue()


def _make_recompressed(size=(256, 256), color=(120, 150, 200)):
    # create and save at low quality to simulate recompression
    return _make_base(size=size, color=color, quality=70)


@pytest.fixture(scope="session")
def golden_base():
    return _make_base()


@pytest.fixture(scope="session")
def golden_splice():
    return _make_spliced()


@pytest.fixture(scope="session")
def golden_recompressed():
    return _make_recompressed()


@pytest.fixture(scope="session")
def golden_corpus(golden_base, golden_splice, golden_recompressed):
    return {
        "base": golden_base,
        "spliced": golden_splice,
        "recompressed": golden_recompressed,
    }
