from src.app.services.synthetic_reco_lab import (
    seed_multicategory_catalog,
    seed_synthetic_interactions,
    evaluate_recommendation_behavior,
)


def test_synthetic_multicategory_seed_and_eval_smoke():
    out1 = seed_multicategory_catalog(include_categories=["laptops", "fashion", "homewares"], per_category=8, clear_existing_synthetic=True)
    assert out1.get("status") == "ok"
    assert int(out1.get("seeded") or 0) >= 24

    out2 = seed_synthetic_interactions(users=8, interactions_per_user=10, days_back=30, seed=42)
    assert out2.get("status") in {"ok", "no_products"}

    out3 = evaluate_recommendation_behavior(top_n=3)
    assert out3.get("status") == "ok"
    assert "overall_precision" in out3
    assert "bitemporal_trace_ok_ratio" in out3
