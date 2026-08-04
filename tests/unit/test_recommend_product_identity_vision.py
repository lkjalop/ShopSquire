import base64

from src.app.services.product_identity_agent import (
    resolve_cached_product_identity,
)


def test_recommend_uses_vision_product_identity_from_cached_image_blob():
    kv = {
        "image_blob_cache": {
            "img-hash-1": base64.b64encode(b"fake-image-bytes").decode("ascii"),
        },
    }
    result = resolve_cached_product_identity(
        kv=kv,
        image_hash="img-hash-1",
        user_query="find alternatives like this",
        trace_id="trace-vision-1",
        identify_fn=lambda image_bytes, **_kwargs: {
            "ok": True,
            "identified": bool(image_bytes),
            "brand": "Lenovo",
            "product_type": "laptop",
            "cpu_tier": "midrange",
            "confidence": 0.92,
        },
        constraints_fn=lambda identity: (
            {"identity_brand": "Lenovo"} if identity.get("identified") else {}
        ),
    )

    assert result["source"] == "vision_image"
    assert result["constraints"]["identity_brand"] == "Lenovo"
