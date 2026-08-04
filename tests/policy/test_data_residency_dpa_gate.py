"""P1-2 — data-residency DPA enforcement. signed_dpa was previously only logged; now a cross-border
transfer carrying declared PII is BLOCKED until the DPA is signed. On-premise is exempt (no transfer)."""
from src.app.policy.data_residency import check_transfer


def test_pii_to_cloud_without_signed_dpa_is_blocked():
    # openai ships signed_dpa=False → a transfer that DECLARES PII categories must be blocked
    v = check_transfer("openai", data_categories=["name", "email", "order_history"])
    assert v.allowed is False
    assert "DPA" in (v.notes or "")


def test_non_pii_to_cloud_still_allowed():
    # no declared PII categories → not gated by the DPA rule (assumed non-PII prompt)
    v = check_transfer("openai", data_categories=[])
    assert v.allowed is True


def test_pii_on_premise_is_exempt():
    # local model transfers nothing off-box → no DPA needed even with PII declared
    v = check_transfer("ollama_local", data_categories=["name", "email"])
    assert v.allowed is True


def test_unknown_provider_blocked_by_default():
    v = check_transfer("some_random_saas", data_categories=["email"])
    assert v.allowed is False
