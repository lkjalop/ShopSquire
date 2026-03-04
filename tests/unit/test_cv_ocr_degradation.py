from src.app.services import cv_ocr


def test_extract_text_marks_degraded_when_provider_errors(monkeypatch):
    monkeypatch.setattr(
        cv_ocr,
        "_tesseract_ocr",
        lambda image_bytes: {
            "text": "",
            "confidence": 0.0,
            "boxes": [],
            "provider": "tesseract",
            "error": "tesseract_binary_missing",
        },
    )
    out = cv_ocr.extract_text(b"fake", provider="tesseract")
    assert out.get("degraded") is True
    assert str(out.get("degradation_reason") or "") == "tesseract_binary_missing"
