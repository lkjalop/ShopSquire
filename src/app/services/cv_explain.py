from __future__ import annotations

from typing import Any, Dict, List, Optional


def explain_cv(
    *,
    tier2_summary: Optional[Dict[str, Any]] = None,
    evidence_tags: Optional[List[str]] = None,
    verdict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic explanation for CV outputs (no LLM).

    Produces stable, UI-friendly fields:
      - summary: short human-readable line
      - why: list of reasons (strings)
      - next_steps: list of recommended actions (strings)
      - risk_band: low|medium|high (best-effort)
    """
    tier2_summary = tier2_summary or {}
    evidence_tags = [str(t) for t in (evidence_tags or []) if t]
    verdict = verdict or {}

    why: List[str] = []
    next_steps: List[str] = []
    risk_band = "low"

    manipulation = tier2_summary.get("manipulation_score")
    try:
        if manipulation is not None and float(manipulation) >= 0.6:
            why.append("Image manipulation signals detected.")
            next_steps.append("Request a live-capture photo with a nonce.")
            risk_band = "high"
    except Exception:
        pass

    if "image_blurry" in evidence_tags:
        why.append("Photo quality appears low (blurry).")
        next_steps.append("Request clearer photos (good lighting, multiple angles).")
        risk_band = "medium" if risk_band == "low" else risk_band

    if "serial_mismatch" in evidence_tags:
        why.append("Serial number text suggests a mismatch or needs verification.")
        next_steps.append("Ask for a close-up serial photo and purchase proof.")
        risk_band = "high"

    if "invoice_mismatch" in evidence_tags:
        why.append("Document/label text suggests invoice/receipt mismatch risk.")
        next_steps.append("Verify order/invoice details against the order record.")
        risk_band = "medium" if risk_band == "low" else risk_band

    # Fold in verdict policy output when present
    try:
        v = verdict.get("verdict")
        if v == "deny":
            risk_band = "high"
        elif v == "request_more_data":
            risk_band = "medium" if risk_band == "low" else risk_band
    except Exception:
        pass

    try:
        reasons = verdict.get("reasons") or []
        if isinstance(reasons, list):
            for r in reasons[:6]:
                if isinstance(r, str) and r and r not in why:
                    why.append(r)
    except Exception:
        pass

    try:
        required = verdict.get("required_actions") or []
        if isinstance(required, list):
            for a in required[:6]:
                if isinstance(a, str) and a:
                    # Map internal action ids to friendlier text.
                    if a == "nonce_live_capture":
                        if "Request a live-capture photo with a nonce." not in next_steps:
                            next_steps.append("Request a live-capture photo with a nonce.")
                    elif a == "manual_review":
                        next_steps.append("Queue for human review.")
                    else:
                        next_steps.append(a)
    except Exception:
        pass

    # De-dup while preserving order
    why = list(dict.fromkeys(why))
    next_steps = list(dict.fromkeys(next_steps))

    if not why:
        why = ["No high-risk visual signals detected."]
    if not next_steps:
        next_steps = ["Proceed with standard verification steps."]

    summary = " ".join(why[:2]).strip()
    if not summary:
        summary = "CV analysis completed."

    return {"summary": summary, "why": why, "next_steps": next_steps, "risk_band": risk_band}

