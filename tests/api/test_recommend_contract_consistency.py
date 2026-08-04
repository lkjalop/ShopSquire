from src.app.services.recommendation_response_contract import (
    assistant_message_claims_products,
    image_cv_signals_from_ocr,
)


def test_assistant_claim_detector():
    assert assistant_message_claims_products("I've found 3 options. Top picks: A; B.") is True
    assert assistant_message_claims_products("No exact products found in this range.") is False


def test_augment_image_cv_signals_from_ocr_detects_payment_overlay():
    out = image_cv_signals_from_ocr("PayID me $150 on 0450 123 456")
    assert out["payment_social_engineering"] is True
