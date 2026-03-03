import base64

from src.app.deps import get_redis
from src.app.services.memory import Memory
from src.app.services.recommendations import RecommendationService
from src.app.routers import recommend as recommend_router
from tests.test_recommend import client, _write_flags


def test_recommend_uses_vision_product_identity_from_cached_image_blob(monkeypatch):
    orig_retrieve = RecommendationService.retrieve_candidates
    try:
        RecommendationService.retrieve_candidates = lambda self, query, limit=10: [
            {"id": "p1", "sku": "VID-1", "name": "Laptop A", "price_cents": 149900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
            {"id": "p2", "sku": "VID-2", "name": "Laptop B", "price_cents": 159900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 16}},
        ]
        _write_flags(
            {
                "USE_AGENT_CAPABILITIES": True,
                "AGENT_ROLLOUT_PERCENT": 100,
                "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
                "KILL_SWITCH": False,
                "DECISION_LOG_WRITES_ENABLED": False,
                "DEGRADATION": {"enabled": True},
                "TEST_FORCE_BAD_SKU": False,
            }
        )
        uid = "u-vision-identity-1"
        mem = Memory(get_redis())
        kv = mem.get_kv(uid) or {}
        kv["image_blob_cache"] = {"img-hash-1": base64.b64encode(b"fake-image-bytes").decode("ascii")}
        mem.set_kv(uid, kv)

        import src.app.services.product_identity_agent as pia

        monkeypatch.setattr(
            pia,
            "identify_product_from_image",
            lambda image_bytes, user_query=None, trace_id=None, timeout_s=12.0: {
                "ok": True,
                "identified": True,
                "brand": "Lenovo",
                "product_type": "laptop",
                "cpu_tier": "midrange",
                "confidence": 0.92,
            },
        )
        monkeypatch.setattr(
            pia,
            "identify_product_from_text",
            lambda labels, ocr_text, user_query=None, trace_id=None: {
                "ok": True,
                "identified": False,
                "confidence": 0.0,
            },
        )
        monkeypatch.setattr(
            pia,
            "specs_to_constraints",
            lambda identity: {"identity_brand": "Lenovo"} if identity.get("identified") else {},
        )

        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": uid,
                "query": "find alternatives like this",
                "image_hash": "img-hash-1",
                "image_labels": "laptop,lenovo",
            },
        )
        assert r.status_code == 200
        body = r.json()
        prod_id = body.get("product_identity") or {}
        assert prod_id.get("source") == "vision_image"
        assert (prod_id.get("constraints") or {}).get("identity_brand") == "Lenovo"
    finally:
        RecommendationService.retrieve_candidates = orig_retrieve
