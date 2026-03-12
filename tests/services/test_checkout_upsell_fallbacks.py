from __future__ import annotations

from types import SimpleNamespace

from src.app.services import checkout_upsell as svc


def test_product_catalog_falls_back_to_ui_storefront(monkeypatch):
    class _DB:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(
        "src.app.routers.ui_storefront._get_products",
        lambda: [
            {"sku": "UI-1", "name": "UI Product 1", "price": 999, "stock": 5, "specs": {"ram_gb": 16}},
            {"sku": "UI-2", "name": "UI Product 2", "price": 1299, "stock": 2, "specs": {}},
        ],
    )

    rows = svc._product_catalog(_DB())
    assert len(rows) == 2
    assert rows[0]["sku"] == "UI-1"
    assert rows[0]["price_cents"] == 99900
    assert rows[0]["stock"] == 5


def test_checkout_upsell_multi_pass_fallback_returns_candidates(monkeypatch):
    # Cart is expensive and the only candidate is filtered out in primary rank pass
    # (price > 70% cart), so deterministic fallback must still return it via widened bands.
    monkeypatch.setattr(
        svc,
        "_product_catalog",
        lambda _db: [
            {"sku": "CART-1", "name": "Cart", "price_cents": 200000, "stock": 4, "specs": {}},
            {"sku": "ALT-1", "name": "Alt", "price_cents": 180000, "stock": 7, "specs": {}},
        ],
    )
    monkeypatch.setattr(svc, "_draft_order_lines", lambda *_a, **_k: [])
    monkeypatch.setattr(svc, "_interaction_stats", lambda *_a, **_k: {})
    monkeypatch.setattr(svc, "_lifecycle_profile", lambda *_a, **_k: {"segment": "unknown", "orders": 0, "ltv_cents": 0})

    recs = svc.recommend_checkout_upsell(
        SimpleNamespace(),
        cart_skus=["CART-1"],
        limit=3,
        uid_hash="u1",
    )
    assert recs
    assert recs[0]["sku"] == "ALT-1"
    assert recs[0]["model_source"] == "deterministic_fallback"

