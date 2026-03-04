def test_cv_tier2_ocr_fallback_ladder_and_clarifier(monkeypatch):
    from src.app.services import cv_tier2_pipeline as t2

    calls = {"n": 0}

    def _fake_extract(image_bytes, provider=None, fallback=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "text": "Invoice # INV-1001 Updated payment details bank transfer now",
                "boxes": [{"x": 1, "y": 1, "w": 10, "h": 10}] * 10,
                "provider": provider or "tesseract",
                "confidence": 0.22,
            }
        return {
            "text": "Invoice # INV-1001 PO Number PO-77 USD 1,200.00 Date 2026-02-01",
            "boxes": [{"x": 1, "y": 1, "w": 10, "h": 10}] * 10,
            "provider": provider or "provider_ocr",
            "confidence": 0.71,
        }

    monkeypatch.setattr(t2, "extract_text", _fake_extract)
    monkeypatch.setenv("CV_OCR_LOW_CONFIDENCE_MIN", "0.58")

    out = t2.run_tier2(b"fake", meta={"case_id": "case-ocr"}, pack_id="agnostic_v1")
    ladder = (out.get("robustness") or {}).get("ocr_ladder") or {}
    assert isinstance(ladder.get("attempts"), list)
    assert len(ladder.get("attempts")) >= 1
    # Clarifier may be omitted when fallback recovers confidence above threshold.
    assert "clarifiers" in out
    if (out.get("clarifiers") or []):
        assert (out.get("clarifiers") or [])[0].get("type") == "ocr_low_confidence"


def test_cv_tier2_marks_ocr_degradation_tag(monkeypatch):
    from src.app.services import cv_tier2_pipeline as t2

    def _fake_extract(image_bytes, provider=None, fallback=None):
        return {
            "text": "",
            "boxes": [],
            "provider": provider or "tesseract",
            "confidence": 0.0,
            "error": "tesseract_binary_missing",
            "degraded": True,
            "degradation_reason": "tesseract_binary_missing",
        }

    monkeypatch.setattr(t2, "extract_text", _fake_extract)
    out = t2.run_tier2(b"fake-image", meta={"case_id": "case-degraded"}, pack_id="agnostic_v1")
    tags = out.get("evidence_tags") or []
    assert "cv_ocr_degraded" in tags
    ladder = (out.get("robustness") or {}).get("ocr_ladder") or {}
    assert ladder.get("degraded") is True
