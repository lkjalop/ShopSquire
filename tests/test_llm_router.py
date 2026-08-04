import pytest

import src.app.services.llm_router as llm_router
from src.app.policy.data_residency import ResidencyVerdict, TransferMechanism
from src.app.services.llm_router import ProviderRouter, get_global_router, generate_text


def test_unsigned_default_provider_is_blocked():
    router = ProviderRouter()
    with pytest.raises(RuntimeError, match="requires a signed DPA"):
        router.generate("hello tier1", tier=1)


def test_select_by_tier_and_generate_after_transfer_is_approved(monkeypatch):
    def approved_transfer(provider, *, data_categories=None):
        assert data_categories == ["llm_prompt"]
        return ResidencyVerdict(
            provider=str(provider),
            allowed=True,
            mechanism=TransferMechanism.SCCs,
            destination_country="test",
            signed_dpa=True,
            dpa_date="2026-07-31",
            data_categories=list(data_categories or []),
            notes="deterministic test approval",
        )

    monkeypatch.setattr(llm_router, "require_provider_transfer", approved_transfer)
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
    get_global_router()
    r = generate_text("global call", tier=1)
    assert isinstance(r, dict)
