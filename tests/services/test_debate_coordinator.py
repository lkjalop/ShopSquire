from src.app.services.debate_coordinator import run_structured_debate


def test_debate_supplier_change_escalates_risky_allow():
    out = run_structured_debate(
        scenario="supplier_change",
        proposal={"action": "allow"},
        evidence={"bank_account_changed": True, "domain_age_days": 2},
    )
    judge = out.get("judge") or {}
    assert judge.get("decision") in {"escalate", "revise"}
    assert judge.get("recommended_action") == "review"


def test_debate_impossible_travel_template_adds_mfa_mitigation():
    out = run_structured_debate(
        scenario="impossible_travel",
        proposal={"action": "allow"},
        evidence={"velocity_kmh": 1200, "asn_risk": 0.92},
    )
    challenger = out.get("challenger") or {}
    judge = out.get("judge") or {}
    assert "impossible_travel_velocity" in (challenger.get("risks") or [])
    assert "step_up_mfa" in (challenger.get("mitigations") or [])
    assert judge.get("decision") in {"escalate", "revise"}
