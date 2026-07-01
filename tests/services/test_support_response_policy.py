"""Support-phrasing policy (M5 support lane) — objection theme → response angle. Agnostic, pure."""
from __future__ import annotations

from src.app.services import support_response_policy as srp
from src.app.services.market_analysis import MarketFinding


def test_price_objection_shifts_to_value():
    r = srp.objection_response("that's too expensive for my budget")
    assert r.objection_theme == srp.OBJECTION_PRICE and r.response_angle == srp.ANGLE_VALUE  # deck slide-7 rule


def test_theme_cues_map_to_angles():
    assert srp.objection_response("is it fast enough to handle rendering?").response_angle == srp.ANGLE_CAPABILITY
    assert srp.objection_response("what's the warranty and return policy?").response_angle == srp.ANGLE_ASSURANCE
    assert srp.objection_response("when will it ship, is it in stock?").response_angle == srp.ANGLE_AVAILABILITY
    assert srp.objection_response("just looking around").response_angle == srp.ANGLE_NEUTRAL


def test_known_theme_token_passthrough():
    assert srp.classify_objection("price") == srp.OBJECTION_PRICE
    assert srp.classify_objection(None) == srp.OBJECTION_UNKNOWN


def test_classify_from_finding_evidence_theme():
    f = {"finding_type": "objection_cluster", "summary": "blocked", "evidence": {"theme": "trust"}, "severity": "warn"}
    assert srp.classify_objection(f) == srp.OBJECTION_TRUST


def test_dominant_objection_picks_strongest():
    findings = [
        MarketFinding("objection_cluster", None, "warn", 0.6, "buyers say it's too pricey", {}, "recent"),
        MarketFinding("objection_cluster", None, "critical", 0.8, "worried about warranty and returns", {}, "recent"),
        MarketFinding("demand_shift", None, "critical", 0.9, "unrelated", {"direction": "spike"}, "recent"),
    ]
    assert srp.dominant_objection(findings) == srp.OBJECTION_TRUST     # critical trust outweighs warn price
    assert srp.dominant_objection([]) == srp.OBJECTION_UNKNOWN


def test_as_dict_shape():
    d = srp.objection_response("too expensive").as_dict()
    assert set(d) == {"objection_theme", "response_angle", "guidance", "rationale"}
    assert d["response_angle"] == srp.ANGLE_VALUE and d["guidance"]
