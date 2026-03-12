from src.app.services.copywriting import maybe_apply_copywriting


def test_copywriting_disabled_by_default():
    out = maybe_apply_copywriting(
        assistant_message="Found 2 matching laptops.",
        turn_intent="SEARCH",
        surface="storefront",
        requested_enabled=None,
        profile_id="premium",
        inline_profile=None,
        brand_name="Acme",
    )
    assert out["assistant_message"] == "Found 2 matching laptops."
    assert bool((out.get("meta") or {}).get("applied")) is False
    assert (out.get("meta") or {}).get("reason") == "disabled"


def test_copywriting_applies_request_level_profile():
    out = maybe_apply_copywriting(
        assistant_message="Found 2 matching laptops",
        turn_intent="SEARCH",
        surface="storefront",
        requested_enabled=True,
        profile_id="premium",
        inline_profile=None,
        brand_name="Acme",
    )
    msg = out["assistant_message"]
    meta = out.get("meta") or {}
    assert "Acme:" in msg
    assert "Curated for quality." in msg
    assert bool(meta.get("applied")) is True
    assert meta.get("cpu_cost") == "low"
    assert str(meta.get("mode") or "").startswith("deterministic_rules")


def test_copywriting_skips_support_intent_by_default():
    out = maybe_apply_copywriting(
        assistant_message="Please upload your receipt for warranty validation.",
        turn_intent="SUPPORT_CLAIM",
        surface="storefront",
        requested_enabled=True,
        profile_id="balanced",
        inline_profile=None,
        brand_name=None,
    )
    assert out["assistant_message"] == "Please upload your receipt for warranty validation."
    assert bool((out.get("meta") or {}).get("applied")) is False
    assert (out.get("meta") or {}).get("reason") == "support_intent_skipped"

