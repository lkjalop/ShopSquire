from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from src.app.services.faq_bank import FAQ_BANK


def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]


def _intent(query: str) -> str:
    q = (query or "").lower()
    if any(k in q for k in ("return", "refund", "warranty", "exchange", "damaged", "broken")):
        return "returns_warranty"
    if any(k in q for k in ("shipping", "track", "delivery", "shipment")):
        return "shipping"
    if any(k in q for k in ("payment", "card", "paypal", "wallet", "chargeback")):
        return "payments"
    if any(k in q for k in ("dashboard", "approval rate", "autonomy", "margin", "sales trend")):
        return "admin_analytics"
    return "general"


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return float(len(sa & sb)) / float(max(1, len(sa | sb)))


def semantic_match_faq(query: str, *, role: str = "buyer") -> Tuple[Dict[str, Any] | None, float, str]:
    q_tokens = _tokenize(query)
    q_intent = _intent(query)
    best: Dict[str, Any] | None = None
    best_score = 0.0
    for item in FAQ_BANK:
        q_text = str(item.get("q") or "")
        tags = [str(x) for x in (item.get("tags") or [])]
        cand_tokens = _tokenize(q_text) + _tokenize(" ".join(tags))
        score = _jaccard(q_tokens, cand_tokens)
        if q_intent in ("returns_warranty", "shipping", "payments"):
            if q_intent == "returns_warranty" and any(t in tags for t in ("return", "refund", "warranty", "damaged")):
                score += 0.15
            if q_intent == "shipping" and any(t in tags for t in ("shipping", "tracking", "delivery")):
                score += 0.15
            if q_intent == "payments" and any(t in tags for t in ("payment", "refund", "tax")):
                score += 0.15
        if score > best_score:
            best_score = score
            best = item
    if best is None:
        if role in ("admin", "owner", "developer") and q_intent == "admin_analytics":
            return (
                {
                    "q": "How is the business performing?",
                    "a": "Use Executive Pulse and NL-to-BI query agent in Admin BI for trends, anomalies, causal chips, and decision replay by policy version.",
                    "tags": ["admin", "analytics"],
                },
                0.35,
                q_intent,
            )
        return None, 0.0, q_intent
    answer = str(best.get("a") or "")
    if q_intent == "returns_warranty" and ("return" not in answer.lower() and "warranty" not in answer.lower()):
        answer = f"{answer} For returns/warranty claims, submit a return request with photos and order evidence."
    if role in ("admin", "owner", "developer"):
        if q_intent == "admin_analytics":
            answer = (
                "Use Executive Pulse and NL-to-BI query agent in Admin BI for trends, "
                "anomalies, causal chips, and decision replay by policy version."
            )
        else:
            answer = f"{answer} Admin note: audit this via Decision Replay and security trend pack before policy changes."
    out = {"q": best.get("q"), "a": answer, "tags": best.get("tags") or []}
    return out, min(1.0, best_score), q_intent
