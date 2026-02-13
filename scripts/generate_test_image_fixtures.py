from __future__ import annotations

import os
import random
from pathlib import Path


def _load_font(size: int):
    try:
        from PIL import ImageFont  # type: ignore

        # Prefer a common Windows font when available for clearer OCR screenshots.
        for name in ("arial.ttf", "Arial.ttf", "C:\\Windows\\Fonts\\arial.ttf"):
            try:
                return ImageFont.truetype(name, size=size)
            except Exception:
                continue
        return ImageFont.load_default()
    except Exception:
        return None


def _save_png(path: Path, img, embedded_text: str):
    try:
        from PIL.PngImagePlugin import PngInfo  # type: ignore

        meta = PngInfo()
        meta.add_text("shopsquire_text", embedded_text)
        img.save(path, format="PNG", pnginfo=meta, optimize=True)
    except Exception:
        img.save(path, format="PNG")


def _solid_fixture(path: Path, title: str, embedded_text: str, accent=(20, 20, 20), bg=(245, 245, 245)):
    from PIL import Image, ImageDraw  # type: ignore

    w, h = 640, 420
    img = Image.new("RGB", (w, h), color=bg)
    d = ImageDraw.Draw(img)

    # Big accent panel to make "wrong image" visually distinct.
    d.rectangle([30, 60, w - 30, h - 40], outline=accent, width=6)
    d.rectangle([60, 90, w - 60, h - 70], fill=(255, 255, 255), outline=accent, width=2)

    font_big = _load_font(42)
    font_med = _load_font(24)
    font_small = _load_font(18)

    d.text((70, 20), title, fill=accent, font=font_med)
    d.text((80, 130), title.upper(), fill=accent, font=font_big)
    d.text((80, 200), embedded_text, fill=accent, font=font_small)
    d.text((80, 235), "TEST FIXTURE - DO NOT USE IN PROD", fill=(100, 100, 100), font=font_small)

    _save_png(path, img, embedded_text=embedded_text)


def _noise_fixture(path: Path, embedded_text: str = "NOISE"):
    from PIL import Image  # type: ignore

    w, h = 640, 420
    px = bytearray()
    rnd = random.Random(1337)
    for _ in range(w * h):
        px.extend([rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)])
    img = Image.frombytes("RGB", (w, h), bytes(px))
    _save_png(path, img, embedded_text=embedded_text)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    out_dir = repo_root / "tests" / "fixtures" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Keep filenames stable (tests rely on them), but regenerate with embedded text.
    _solid_fixture(
        out_dir / "return_ok_laptop.png",
        title="Laptop Return OK",
        embedded_text="LAPTOP SKU:LAPTOP-OK SERIAL:SN-ABC123 ORDER:ORDER-123",
        accent=(30, 90, 160),
    )
    _solid_fixture(
        out_dir / "return_wrong_phone.png",
        title="Wrong Item Phone",
        embedded_text="PHONE SKU:PHONE-XYZ SERIAL:SN-PHONE999 ORDER:ORDER-123",
        accent=(160, 40, 40),
    )
    _solid_fixture(
        out_dir / "return_wrong_receipt.png",
        title="Receipt Document",
        embedded_text="RECEIPT INVOICE ORDER ORDER-123 TOTAL 1999 USD SKU LAPTOP-OK SHIP TO JOHN DOE 123 MAIN ST",
        accent=(40, 120, 40),
    )
    _noise_fixture(out_dir / "return_wrong_noise.png", embedded_text="NOISE")

    # Additional fixtures for SKU mismatch assertions (new tests may use these).
    _solid_fixture(
        out_dir / "return_ok_sku_text.png",
        title="SKU Match",
        embedded_text="SKU:LAPTOP-OK ORDER:ORDER-555 SERIAL:SN-OK555",
        accent=(30, 90, 160),
    )
    _solid_fixture(
        out_dir / "return_wrong_sku_text.png",
        title="SKU Mismatch",
        embedded_text="SKU:PHONE-XYZ ORDER:ORDER-555 SERIAL:SN-BAD555",
        accent=(160, 40, 40),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
