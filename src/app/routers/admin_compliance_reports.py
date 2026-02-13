from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Depends

from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role
from src.app.services.audit_chain import verify_audit_chain
from src.app.services.compliance_reporting import generate_evidence_report


router = APIRouter(prefix="/api/v1/admin/compliance/reports", tags=["admin-compliance-reports"])


@router.get("/evidence")
def evidence_report(days: int = 30, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return generate_evidence_report(days=days)


@router.get("/audit-chain/verify")
def verify_chain(limit: int = 1000, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    return verify_audit_chain(limit=limit)
