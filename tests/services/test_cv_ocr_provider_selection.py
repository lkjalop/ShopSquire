from src.app.services import cv_ocr


def test_explicit_bounded_ocr_provider_overrides_environment_default(monkeypatch):
    monkeypatch.setenv("CV_OCR_PROVIDER", "glm-ocr")
    called = []
    monkeypatch.setattr(
        cv_ocr,
        "_tesseract_ocr",
        lambda _blob: called.append("tesseract") or {
            "text": "RAM 64 GB",
            "confidence": 0.9,
            "boxes": [],
            "provider": "tesseract",
        },
    )
    monkeypatch.setattr(
        cv_ocr,
        "_glm_ocr",
        lambda _blob: (_ for _ in ()).throw(AssertionError("environment must not override caller")),
    )

    result = cv_ocr.extract_text(b"image", provider="tesseract")

    assert called == ["tesseract"]
    assert result["provider"] == "tesseract"
    assert result["text"] == "RAM 64 GB"
