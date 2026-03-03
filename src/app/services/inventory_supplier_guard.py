from __future__ import annotations

from typing import Any, Dict


def compute_supplier_trust_score(
    *,
    signature_validity: float,
    historical_defect_rate: float,
    lead_time_variance: float,
    invoice_mismatch_rate: float,
) -> Dict[str, Any]:
    sig = max(0.0, min(1.0, float(signature_validity or 0.0)))
    defect = max(0.0, min(1.0, float(historical_defect_rate or 0.0)))
    variance = max(0.0, min(1.0, float(lead_time_variance or 0.0)))
    mismatch = max(0.0, min(1.0, float(invoice_mismatch_rate or 0.0)))
    score = (
        0.42 * sig
        + 0.22 * (1.0 - defect)
        + 0.18 * (1.0 - variance)
        + 0.18 * (1.0 - mismatch)
    )
    score = max(0.0, min(1.0, score))
    band = "high" if score >= 0.8 else ("medium" if score >= 0.6 else "low")
    return {
        "supplier_trust_score": round(score, 4),
        "band": band,
        "components": {
            "signature_validity": round(sig, 4),
            "historical_defect_rate": round(defect, 4),
            "lead_time_variance": round(variance, 4),
            "invoice_mismatch_rate": round(mismatch, 4),
        },
    }


def evaluate_dual_source_confirmation(confirmations: Dict[str, Any] | None) -> Dict[str, Any]:
    c = confirmations or {}
    po_invoice = bool(c.get("po_invoice"))
    carrier_asn = bool(c.get("carrier_asn"))
    erp_ack = bool(c.get("erp_ack"))
    n = int(po_invoice) + int(carrier_asn) + int(erp_ack)
    ok = n >= 2
    missing = []
    if not po_invoice:
        missing.append("po_invoice")
    if not carrier_asn:
        missing.append("carrier_asn")
    if not erp_ack:
        missing.append("erp_ack")
    return {"ok": ok, "count": n, "missing": missing}


def evaluate_auto_po_policy(*, amount: float, supplier_risk: float, anomaly_score: float) -> Dict[str, Any]:
    amt = float(amount or 0.0)
    sr = max(0.0, min(1.0, float(supplier_risk or 0.0)))
    an = max(0.0, min(1.0, float(anomaly_score or 0.0)))
    # Higher means riskier.
    risk = (0.45 * sr) + (0.35 * an) + (0.20 * min(1.0, amt / 15000.0))
    if risk >= 0.75:
        return {"decision": "escalate", "risk_score": round(risk, 4), "reason_codes": ["supplier_risk_high", "anomaly_high"]}
    if risk >= 0.45:
        return {"decision": "challenge", "risk_score": round(risk, 4), "reason_codes": ["secondary_approval_required"]}
    return {"decision": "allow", "risk_score": round(risk, 4), "reason_codes": ["within_policy"]}

