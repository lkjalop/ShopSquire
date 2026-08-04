from __future__ import annotations

"""Claim grounding — the assert-to-evidence primitive applied to return/warranty
claims (the SECOND surface of the grounding ladder; products are the first).

A customer CLAIM ("the screen is cracked") is self-reported and low-trust. We
ground it against EVIDENCE (CV damage analysis, receipt/serial, order record)
using the SAME reliability-weighted vote + conflict detection as the product
ladder. We then assert the claim only to the level the evidence supports:

    supported       evidence confirms the claim     → can auto-progress
    needs_evidence  claim made, no evidence yet      → ask for a damage photo
    contradicted    evidence disagrees with claim    → reject under policy +
                                                       offer the CUSTOMER an evidence path

The `residual_action` is the bounded-autonomy boundary — exactly when/why a
human (or more customer input) is pulled in.

This reuses `grounding_ladder._resolve_field` (the weighted-vote core) with a
returns-domain reliability map, demonstrating the primitive generalises. It is a
pure function (no I/O) so it is fully unit-testable; wiring into the live returns
flow is the next step.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.grounding_ladder import _resolve_field, _label

# Evidence reliability for the returns domain (source → trust).
CLAIM_RELIABILITY = {
    "order_record": 0.95,   # the order exists / item matches — authoritative
    "receipt": 0.90,        # uploaded receipt / serial match
    "cv_damage": 0.85,      # CV / vision damage analysis of the photo
    "customer_claim": 0.40,  # self-reported words — lowest trust
}

# Damage taxonomy (mirrors cv_triage_basic.DAMAGE_KEYWORDS).
_DAMAGE_KW = {
    "physical": ["crack", "cracked", "broken", "shattered", "dent", "snapped", "hinge"],
    "cosmetic": ["scratch", "scuff", "mark", "stain", "discolor"],
    "functional": ["won't turn on", "wont turn on", "dead", "black screen", "no power", "bsod", "boot", "freeze"],
    "water": ["water", "liquid", "spill", "wet", "moisture"],
    "missing": ["missing", "not included", "empty box", "didn't receive", "did not receive"],
}


def _damage_types_from_text(text: str) -> set:
    """ALL damage types mentioned — a claim like 'water damage and won't turn on'
    legitimately spans two (water + functional), so CV confirming either is a match."""
    t = str(text or "").lower()
    return {dtype for dtype, kws in _DAMAGE_KW.items() if any(kw in t for kw in kws)}


@dataclass
class ClaimGroundingResult:
    claim_type: Optional[str] = None
    grounded: bool = False
    confidence: float = 0.0
    confidence_label: str = "unverified"
    conflict: bool = False
    verdict: str = "needs_evidence"  # supported | needs_evidence | contradicted
    residual_action: Optional[Dict[str, Any]] = None
    evidence_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_type": self.claim_type,
            "grounded": self.grounded,
            "confidence": round(float(self.confidence), 3),
            "confidence_label": self.confidence_label,
            "conflict": self.conflict,
            "verdict": self.verdict,
            "residual_action": self.residual_action,
            "evidence_sources": self.evidence_sources,
        }


def ground_claim(
    claim_text: str,
    *,
    cv_evidence: Optional[Dict[str, Any]] = None,
    receipt_evidence: Optional[Dict[str, Any]] = None,
) -> ClaimGroundingResult:
    """Ground a return/warranty claim against CV + receipt evidence.

    cv_evidence: {"damage_type": str, "confidence": float} from CV triage.
    receipt_evidence: {"verified": bool, "confidence": float}.
    """
    evidence: List[Dict[str, Any]] = []
    claim_types = _damage_types_from_text(claim_text)
    cv_dt = None
    if isinstance(cv_evidence, dict) and cv_evidence.get("damage_type"):
        cv_dt = str(cv_evidence["damage_type"]).lower()
        if cv_dt in ("unknown", "none", ""):
            cv_dt = None
    # The customer-claim representative aligns to CV when CV confirms one of the
    # mentioned types (so a multi-symptom claim isn't a false contradiction).
    claim_dt = cv_dt if (cv_dt and cv_dt in claim_types) else (sorted(claim_types)[0] if claim_types else None)
    if claim_dt:
        evidence.append({"field": "damage_type", "value": claim_dt, "source": "customer_claim", "confidence": 1.0})
    if cv_dt:
        evidence.append({
            "field": "damage_type", "value": cv_dt, "source": "cv_damage",
            "confidence": float(cv_evidence.get("confidence") or 0.6),
        })
    receipt_ok = bool(isinstance(receipt_evidence, dict) and receipt_evidence.get("verified"))

    claim_type, conflicts = _resolve_field(evidence, "damage_type", reliability=CLAIM_RELIABILITY)
    has_cv = cv_dt is not None
    # Contradiction = CV sees a damage type the customer did NOT mention at all
    # (over-/mis-claim). If CV confirms any mentioned type, that's support.
    explicit_contradiction = bool(cv_dt and claim_types and cv_dt not in claim_types)
    conflict = bool(any(c.get("field") == "damage_type" for c in conflicts) or explicit_contradiction)

    # ── Verdict + residual (the bounded-autonomy boundary) ──
    if conflict:
        verdict = "contradicted"
        grounded = False
        confidence = 0.35
        # Bounded-autonomy boundary (NOT an employee runtime gate, which the
        # autonomy doctrine treats as an anti-pattern): the engine rejects under
        # policy and hands the CUSTOMER an evidence path. Customer clarification is
        # allowed; a manual employee review queue is not. Maps to the engine's
        # reject_under_policy + request_customer_evidence terminals.
        residual = {
            "action": "reject_under_policy",
            "reason": "customer_claim_conflicts_with_cv_evidence",
            "message": "What you've described doesn't match the photo, so we can't auto-approve this return. "
                       "If that's a mistake, reply with a clear photo of the exact issue (and your order number) "
                       "and we'll re-check it automatically.",
            "customer_evidence_path": "request_customer_evidence",
        }
    elif has_cv and (not claim_types or cv_dt in claim_types):
        # CV confirms a mentioned damage type (or found damage the customer didn't
        # describe) → supported.
        verdict = "supported"
        grounded = True
        confidence = (0.9 if receipt_ok else 0.8) if claim_types else 0.75
        claim_type = cv_dt
        residual = None
    else:
        # A claim with no corroborating evidence → ask for proof before auto-progressing.
        verdict = "needs_evidence"
        grounded = False
        confidence = 0.45 if claim_dt else 0.2
        residual = {
            "action": "request_evidence",
            "reason": "claim_unconfirmed_by_evidence",
            "message": "To process this, please upload a clear photo of the damage"
                       + ("" if receipt_ok else " and your receipt or order number") + ".",
        }

    return ClaimGroundingResult(
        claim_type=claim_type,
        grounded=grounded,
        confidence=confidence,
        confidence_label=_label(confidence),
        conflict=conflict,
        verdict=verdict,
        residual_action=residual,
        evidence_sources=[e["source"] for e in evidence] + (["receipt"] if receipt_ok else []),
    )
