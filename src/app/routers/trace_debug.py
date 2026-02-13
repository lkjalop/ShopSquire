from fastapi import APIRouter, Depends
from typing import Any, Dict

from src.app.security.auth import require_role, ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER
from src.app.security.observer import analyze_payload
from src.app.services.risk_quantification import quantify

router = APIRouter(prefix="/api/v1/trace", tags=["decision-trace"])


@router.post("/debug")
def trace_debug(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))):
    """Return security observer analysis for a payload without executing heavy CV."""
    return analyze_payload(payload or {})


def _control_tags(analysis: Dict[str, Any]) -> list[str]:
    tags: list[str] = []
    owasp = analysis.get("owasp_llm_top10") or []
    mitre = analysis.get("mitre_atlas") or []
    if isinstance(owasp, list) and owasp:
        tags.append("ISO42001:7.4")
        tags.append("EU_AI_ACT:Art.14")
    if isinstance(mitre, list) and mitre:
        tags.append("ISO27001:A.8.16")
        tags.append("NIST_AI_RMF:MANAGE-3")
    stride = analysis.get("stride_score")
    if isinstance(stride, dict) and stride:
        tags.append("ISO27001:A.8.15")
    return sorted(set(tags))


@router.post("/debug/enriched")
def trace_debug_enriched(
    payload: Dict[str, Any], role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER]))
):
    """Return observer analysis plus deterministic risk/control annotations for GRC reporting."""
    data = analyze_payload(payload or {})
    analysis = data.get("analysis") if isinstance(data, dict) else {}
    if not isinstance(analysis, dict):
        analysis = {}
    risk = quantify(
        security={
            "risk_adj": data.get("risk_adj", 0),
            "signals": analysis.get("signals") or [],
        },
        policy_gates=analysis.get("policy"),
        monetary_exposure=float(payload.get("amount_cents", 0) or 0) / 100.0 if isinstance(payload, dict) else None,
    )
    return {
        "trace": data,
        "risk": risk,
        "controls": _control_tags(analysis),
        "references": {
            "playbook": "docs/Security_Detection_Playbook.md",
            "scanner": "scripts/security/fingerprint_scan.py",
        },
    }
