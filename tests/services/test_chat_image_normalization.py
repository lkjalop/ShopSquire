import base64

from src.app.services.chat_image_normalization import normalize_chat_images


def test_normalizes_legacy_and_multi_image_security_without_trusting_ocr() -> None:
    encoded = base64.b64encode(b"image-bytes").decode("ascii")
    result = normalize_chat_images({
        "images": [
            {
                "labels": ["laptop"], "ocr_text": "32 GB RAM",
                "image_b64": encoded, "product_identity": {"brand": "Lenovo"},
                "cv_signals": {"adversarial_score": 0.1},
            },
            {
                "security": {"signals": {
                    "qr_prompt_injection": True,
                    "qr_payloads": ["https://untrusted.example"],
                }},
            },
        ],
    })

    assert result.labels == ["laptop"]
    assert result.ocr_text == "32 GB RAM"
    assert result.product_identity == {"brand": "Lenovo"}
    assert result.cv_signals["qr_prompt_injection"] is True
    assert result.blob == b"image-bytes"
    assert result.image_hash


def test_bounds_image_count_and_rejects_oversized_encoded_payload() -> None:
    result = normalize_chat_images({
        "images": [
            {"labels": [str(index)], "image_b64": "A" * 6_000_001}
            for index in range(8)
        ],
    })

    assert len(result.images) == 3
    assert result.blob == b""
