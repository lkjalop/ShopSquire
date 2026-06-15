from src.app.services.claim_grounding import ground_claim


def test_claim_supported_when_cv_confirms():
    r = ground_claim(
        "the screen is cracked",
        cv_evidence={"damage_type": "physical", "confidence": 0.85},
        receipt_evidence={"verified": True},
    )
    assert r.verdict == "supported"
    assert r.grounded is True
    assert r.residual_action is None


def test_claim_needs_evidence_when_no_cv():
    r = ground_claim("the screen is cracked")
    assert r.verdict == "needs_evidence"
    assert r.grounded is False
    assert r.residual_action["action"] == "request_evidence"


def test_claim_contradicted_rejects_under_policy_with_customer_evidence_path():
    # Customer says physical crack; CV sees only cosmetic scuff → conflict.
    # Bounded autonomous outcome: reject under policy + offer the CUSTOMER an
    # evidence path (NOT an employee runtime review gate).
    r = ground_claim(
        "my screen is completely cracked and shattered",
        cv_evidence={"damage_type": "cosmetic", "confidence": 0.8},
    )
    assert r.verdict == "contradicted"
    assert r.conflict is True
    assert r.residual_action["action"] == "reject_under_policy"
    assert r.residual_action["customer_evidence_path"] == "request_customer_evidence"
    # the doctrinal point: no employee runtime gate
    assert r.residual_action["action"] != "route_human_review"


def test_cv_finds_damage_customer_didnt_describe():
    r = ground_claim(
        "I want to return this",  # no damage words
        cv_evidence={"damage_type": "physical", "confidence": 0.7},
    )
    assert r.verdict == "supported"
    assert r.claim_type == "physical"


def test_empty_claim_is_safe():
    r = ground_claim("")
    assert r.verdict == "needs_evidence"
    assert r.to_dict()["confidence_label"] == "unverified"
