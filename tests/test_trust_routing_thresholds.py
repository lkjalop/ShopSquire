import json

from src.app.services.trust_routing import route_from_trust


def _read_flags() -> dict:
    with open("config/feature_flags.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _write_flags(flags: dict) -> None:
    with open("config/feature_flags.json", "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def test_trust_routing_uses_configured_tiers_and_amount_threshold():
    flags = _read_flags()
    flags["TRUST_THRESHOLDS"] = {
        "high_trust_min": 0.9,
        "medium_trust_min": 0.7,
        "guarded_trust_min": 0.4,
        "max_amount_usd_high": 500.0,
        "max_amount_usd_medium": 200.0,
        "max_amount_usd_guarded": 50.0,
        "max_amount_usd_low": 0.0,
        "supervisor_review_amount_usd_min": 10.0,
    }
    _write_flags(flags)

    dec = route_from_trust(trust_score=0.85, amount_usd=5.0, risk_band=None)
    assert dec.tier == "medium"
    assert dec.route in ("standard_queue", "auto_process", "security_review", "supervisor_review")

    dec2 = route_from_trust(trust_score=0.85, amount_usd=25.0, risk_band=None)
    assert dec2.route == "supervisor_review"
    assert "high_amount" in (dec2.reasons or [])

