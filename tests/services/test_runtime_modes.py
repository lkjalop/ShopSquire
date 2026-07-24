from src.app.services.runtime_modes import runtime_mode_snapshot


def test_standard_profile_reports_modes_without_imposing_demo_contract(monkeypatch):
    monkeypatch.delenv("SHOPSQUIRE_RUNTIME_PROFILE", raising=False)
    monkeypatch.delenv("RECOMMEND_CART_SERVE", raising=False)

    result = runtime_mode_snapshot()

    assert result["profile"] == "standard"
    assert result["ready"] is True
    assert result["active"]["cart_mutation"] == "off"


def test_demo_profile_fails_when_cart_lane_is_not_enabled(monkeypatch):
    monkeypatch.setenv("SHOPSQUIRE_RUNTIME_PROFILE", "demo_v2")
    monkeypatch.setenv("RECOMMEND_CORE_MODE", "primary")
    monkeypatch.setenv("RECOMMEND_PROCUREMENT_ADVICE_MODE", "on")
    monkeypatch.delenv("RECOMMEND_CART_SERVE", raising=False)

    result = runtime_mode_snapshot()

    assert result["ready"] is False
    assert result["mismatches"] == [{
        "mode": "cart_mutation",
        "expected": "on",
        "actual": "off",
    }]


def test_demo_profile_is_ready_only_with_declared_v2_modes(monkeypatch):
    monkeypatch.setenv("SHOPSQUIRE_RUNTIME_PROFILE", "demo_v2")
    monkeypatch.setenv("RECOMMEND_CORE_MODE", "primary")
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "1")
    monkeypatch.setenv("RECOMMEND_PROCUREMENT_ADVICE_MODE", "on")

    result = runtime_mode_snapshot()

    assert result["ready"] is True
    assert result["mismatches"] == []
