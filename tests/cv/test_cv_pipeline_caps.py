import os
from io import BytesIO


def _png_bytes() -> bytes:
    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"PIL required for this test: {exc}")
    img = Image.new("RGB", (64, 64), color=(255, 255, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_cv_pipeline_skips_large_images(monkeypatch):
    from src.app.cv.cv_pipeline import run_pipeline

    monkeypatch.setenv("CV_MAX_IMAGES", "10")
    # The pipeline enforces a sane lower bound for max bytes; verify clamping + behavior.
    monkeypatch.setenv("CV_MAX_IMAGE_BYTES", "100")  # will clamp to 10_000
    out = run_pipeline([("big.bin", b"x" * 20000), ("small.png", _png_bytes())], pack=None, roi_model_path=None, ocr_provider="embedded")
    assert out.get("caps", {}).get("max_image_bytes") == 10000
    imgs = out.get("images") or []
    assert len(imgs) == 2
    assert imgs[0].get("skipped") == "too_large"
