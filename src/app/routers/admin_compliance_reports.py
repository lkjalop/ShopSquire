from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends

from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from src.app.security.dlp_export import dlp_sanitize_export_value
from src.app.services.audit_chain import publish_daily_audit_chain_anchor, verify_audit_chain
from src.app.services.compliance_reporting import generate_evidence_report


router = APIRouter(prefix="/api/v1/admin/compliance/reports", tags=["admin-compliance-reports"])


@router.get("/evidence")
def evidence_report(days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    payload = generate_evidence_report(days=days)
    sanitized, _hits = dlp_sanitize_export_value(payload)
    return sanitized if isinstance(sanitized, dict) else {"report": sanitized}


@router.get("/audit-chain/verify")
def verify_chain(limit: int = 1000, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return verify_audit_chain(limit=limit)


@router.post("/audit-chain/anchor/daily")
def publish_daily_chain_anchor(role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return publish_daily_audit_chain_anchor()
