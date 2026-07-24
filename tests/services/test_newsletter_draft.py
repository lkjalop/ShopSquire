from src.app.services.newsletter_draft import build_newsletter_draft


def test_newsletter_draft_uses_only_evidence_qualified_products_and_never_sends():
    draft = build_newsletter_draft([
        {
            "sku": "SURPLUS-1",
            "name": "Studio Display",
            "currency": "AUD",
            "list_cents": 100_000,
            "projection": {"dead_stock": True, "dsi_days": 140},
            "action_proposals": {
                "discount": {
                    "eligible": True,
                    "recommended_discount_pct": 0.08,
                }
            },
        },
        {
            "sku": "NORMAL-1",
            "name": "Popular Laptop",
            "projection": {"dead_stock": False, "dsi_days": 12},
            "action_proposals": {"discount": {"eligible": False}},
        },
    ])
    assert draft["featured_skus"] == ["SURPLUS-1"]
    assert draft["deals"] == [{"sku": "SURPLUS-1", "discount_pct": 0.08}]
    assert draft["status"] == "draft"
    assert draft["send_gate"] == "human"
    assert draft["sent"] is False
    assert draft["copy_mode"] == "grounded_template"


def test_newsletter_draft_is_honestly_empty_without_qualified_products():
    draft = build_newsletter_draft([
        {
            "sku": "NORMAL-1",
            "name": "Normal",
            "projection": {"dead_stock": False, "dsi_days": 10},
            "action_proposals": {"discount": {"eligible": False}},
        }
    ])
    assert draft["featured_skus"] == []
    assert draft["status"] == "insufficient_evidence"
    assert draft["sent"] is False
