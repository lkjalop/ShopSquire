from src.app.services.llm_router import ProviderRouter, get_global_router, generate_text


def test_select_by_tier_and_generate():
    router = ProviderRouter()

    # Tier 1 should prefer Mistral (stubbed if no key)
    resp1 = router.generate("hello tier1", tier=1)
    assert isinstance(resp1, dict)
    assert "provider" in resp1 or "error" in resp1

    # Tier 2 prefers OpenAI
    resp2 = router.generate("hello tier2", tier=2)
    assert isinstance(resp2, dict)

    # Tier 3 prefers Anthropic
    resp3 = router.generate("hello tier3", tier=3)
    assert isinstance(resp3, dict)

    # global convenience
    g = get_global_router()
    r = generate_text("global call", tier=1)
    assert isinstance(r, dict)
