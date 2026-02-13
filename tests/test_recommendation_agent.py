from src.app.services.recommendations import RecommendationService


def _sample_candidates():
    return [
        {
            "sku": "ELEC-LAP-RTX-001",
            "name": "Gaming Laptop Pro",
            "price_cents": 129999,
            "currency": "USD",
            "stock": 5,
            "specs": {"ram_gb": 32, "storage_gb": 1024, "gpu": "rtx"},
        },
        {
            "sku": "ELEC-LAP-BASIC-001",
            "name": "Office Laptop Basic",
            "price_cents": 69999,
            "currency": "USD",
            "stock": 0,
            "specs": {"ram_gb": 8, "storage_gb": 256},
        },
        {
            "sku": "ELEC-LAP-CREATOR-001",
            "name": "Creator Laptop OLED",
            "price_cents": 159999,
            "currency": "USD",
            "stock": 2,
            "specs": {"ram_gb": 32, "storage_gb": 1024, "display": "oled"},
        },
    ]


def test_build_prompt_shape():
    svc = RecommendationService()
    cands = _sample_candidates()
    constraints = {"intent": "recommend", "query": "gaming laptop"}
    prompt = svc.build_prompt(cands, constraints)
    assert isinstance(prompt, dict)
    assert "candidates" in prompt and isinstance(prompt["candidates"], list)
    assert "constraints" in prompt and isinstance(prompt["constraints"], dict)


def test_rerank_returns_list_and_orders_by_stock_and_specs():
    svc = RecommendationService()
    cands = _sample_candidates()
    constraints = {"budget_max": 200000, "specs": ["gpu:discrete"], "query": "gaming laptop"}
    ranked = svc.rerank_candidates(cands, constraints)
    assert isinstance(ranked, list)
    assert len(ranked) == len(cands)
    # Expect the gaming laptop with stock and discrete GPU to be ranked first
    assert ranked[0]["sku"] == "ELEC-LAP-RTX-001"
