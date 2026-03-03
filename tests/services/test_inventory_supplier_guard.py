from src.app.services.inventory_supplier_guard import (
    compute_supplier_trust_score,
    evaluate_auto_po_policy,
    evaluate_dual_source_confirmation,
)


def test_supplier_trust_score_low_band():
    out = compute_supplier_trust_score(
        signature_validity=0.2,
        historical_defect_rate=0.8,
        lead_time_variance=0.7,
        invoice_mismatch_rate=0.6,
    )
    assert out["band"] == "low"
    assert float(out["supplier_trust_score"]) < 0.6


def test_dual_source_confirmation_requires_two_sources():
    ok = evaluate_dual_source_confirmation({"po_invoice": True, "carrier_asn": False, "erp_ack": True})
    assert ok["ok"] is True
    bad = evaluate_dual_source_confirmation({"po_invoice": True, "carrier_asn": False, "erp_ack": False})
    assert bad["ok"] is False
    assert "carrier_asn" in (bad.get("missing") or [])


def test_auto_po_policy_escalate_on_high_risk():
    out = evaluate_auto_po_policy(amount=20000, supplier_risk=0.9, anomaly_score=0.8)
    assert out["decision"] == "escalate"
    assert out["risk_score"] >= 0.75

