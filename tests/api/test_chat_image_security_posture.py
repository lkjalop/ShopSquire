from src.app.routers.chat import _derive_image_security_posture


def test_chat_image_security_posture_degraded():
    out = _derive_image_security_posture(
        {
            "qr_code_detected": True,
            "qr_prompt_injection": False,
            "qr_external_url_detected": False,
            "ocr_prompt_injection": False,
            "manipulation_detected": False,
            "adversarial_score": 0.0,
        }
    )
    assert out["route"] == "visual_sanitized"
    assert out["image_untrusted"] is True
    assert out["chat_lockdown"] is False


def test_chat_image_security_posture_lockdown_for_malicious_qr():
    out = _derive_image_security_posture(
        {
            "qr_code_detected": True,
            "qr_prompt_injection": True,
            "qr_external_url_detected": True,
            "ocr_prompt_injection": True,
            "manipulation_detected": True,
            "adversarial_score": 0.9,
        }
    )
    assert out["route"] == "lockdown"
    assert out["chat_lockdown"] is True
    assert out["needs_human_review"] is True


def test_chat_image_security_posture_uncertain_ocr_is_untrusted():
    out = _derive_image_security_posture(
        {
            "qr_code_detected": False,
            "qr_prompt_injection": False,
            "qr_external_url_detected": False,
            "ocr_prompt_injection": False,
            "ocr_low_confidence_uncertain": True,
            "manipulation_detected": False,
            "adversarial_score": 0.0,
        }
    )
    assert out["route"] == "escalate"
    assert out["image_untrusted"] is True
    assert out["image_degraded_mode"] is True
