from __future__ import annotations

from src.app.services.risk import quantify_exposure


def test_quantify_exposure_basic():
    res = quantify_exposure(price_cents=15000, likelihood=0.3, dread_modifier=0.2, stride_modifier=0.1, control_maturity=0.5)
    assert isinstance(res, dict)
    # required keys
    for k in ("price_cents", "likelihood", "impact", "risk", "exposure_cents", "risk_band", "modifiers", "components"):
        assert k in res
    assert res["price_cents"] == 15000
    assert 0.0 <= res["likelihood"] <= 1.0
    assert 0.0 <= res["impact"] <= 1.0
    assert 0.0 <= res["risk"] <= 1.0
    assert isinstance(res["exposure_cents"], int)
    assert res["risk_band"] in {"low", "medium", "high"}


def test_quantify_exposure_zero_price():
    res = quantify_exposure(price_cents=0, likelihood=0.9)
    assert res["exposure_cents"] == 0
    # With zero price, exposure is zero even if abstract risk>0
    assert res["risk"] >= 0.0
