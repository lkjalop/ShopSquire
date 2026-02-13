from __future__ import annotations

import re
from typing import Any, Dict, Optional


class ComplaintNLP:
    """Pattern-based complaint classifier for refunds, payments, shipments, recalls.

    Returns intent, confidence, extracted entities (order_id, payment_id, tracking_number).
    """

    def classify(self, text: str) -> Dict[str, Any]:
        t = (text or "").lower()
        intents = {
            "refund_request": sum(1 for w in ["refund", "return", "money back"] if w in t),
            "payment_failure": sum(1 for w in ["payment failed", "declined", "charge failed", "card error"] if w in t),
            "shipment_verification": sum(1 for w in ["tracking", "shipped", "delivery", "not received", "lost"] if w in t),
            "recall_notice": sum(1 for w in ["recall", "safety notice", "hazard"] if w in t),
            "fraud_alert": sum(1 for w in ["scam", "fraud", "fake", "phishing"] if w in t),
        }
        intent = max(intents.items(), key=lambda x: x[1])[0]
        total = max(sum(intents.values()), 1)
        confidence = round(intents[intent] / total, 3)

        entities: Dict[str, Any] = {}
        # Order/Payment/Tracking extraction (simple regex)
        m_order = re.search(r"order\s*#?([A-Za-z0-9\-]{6,})", t)
        if m_order:
            entities["order_id"] = m_order.group(1)
        m_pay = re.search(r"payment\s*id\s*[:#]?\s*([A-Za-z0-9_\-]{6,})", t)
        if m_pay:
            entities["payment_id"] = m_pay.group(1)
        m_track = re.search(r"(tracking|waybill)\s*#?\s*([A-Za-z0-9]{8,})", t)
        if m_track:
            entities["tracking_number"] = m_track.group(2)

        # Amount detection
        m_amt = re.search(r"\$\s*(\d+(?:\.\d{2})?)", t)
        if m_amt:
            entities["amount"] = m_amt.group(1)

        return {"intent": intent, "confidence": confidence, "entities": entities}
