from io import BytesIO


def test_image_normalizer_returns_png_and_meta():
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PIL required for this test: {exc}")

    from src.app.cv.image_normalizer import normalize_image_bytes

    img = Image.new("RGB", (2400, 800), color=(10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    raw = buf.getvalue()

    out = normalize_image_bytes(raw, max_dim=1024)
    assert out.image_bytes
    assert out.meta.get("ok") is True
    assert out.meta.get("format") == "png"
    assert out.meta.get("width") <= 1024

