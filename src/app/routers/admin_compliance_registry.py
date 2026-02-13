from __future__ import annotations

import os
import json
import uuid
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.models.compliance_registry import ensure_compliance_registry_table, insert_artifact, list_artifacts


router = APIRouter(prefix="/api/v1/admin/compliance", tags=["admin", "compliance"])


@router.on_event("startup")
def _ensure_table_on_startup():
    try:
        ensure_compliance_registry_table()
    except Exception:
        pass


@router.post("/artifacts")
def upload_artifact(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Upload a compliance artifact (e.g., Trivy scan JSON summary).

    Payload may be either raw vendor output or a normalized dict:
    {
      artifact_type: 'container_scan',
      vendor: 'trivy',
      scan_id: 'sha256:...',
      status: 'pass'|'fail'|'warn',
      details: { ... }
    }
    """
    artifact_type = str(payload.get("artifact_type") or "container_scan")
    vendor = str(payload.get("vendor") or "unknown")
    scan_id = str(payload.get("scan_id") or "") or None
    status = str(payload.get("status") or "").lower() or None
    if not status:
        # derive status from Trivy-like results if present
        try:
            vulns = payload.get("Results") or payload.get("results") or []
            critical = 0
            high = 0
            for r in vulns:
                for v in (r.get("Vulnerabilities") or r.get("vulnerabilities") or []):
                    sev = (v.get("Severity") or v.get("severity") or "").upper()
                    if sev == "CRITICAL":
                        critical += 1
                    elif sev == "HIGH":
                        high += 1
            status = "fail" if critical > 0 else ("warn" if high > 0 else "pass")
        except Exception:
            status = "pass"
    try:
        det = payload if isinstance(payload, dict) else {"raw": str(payload)}
        res = insert_artifact(
            id=str(uuid.uuid4()),
            artifact_type=artifact_type,
            vendor=vendor,
            scan_id=scan_id,
            status=status,
            details=json.dumps(det, ensure_ascii=False),
        )
        if not res.get("inserted"):
            raise HTTPException(status_code=500, detail=res.get("error") or "insert_failed")
        return {"uploaded": True, "id": res.get("id")}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/artifacts")
def list_latest(limit: int = 50, role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    items = list_artifacts(limit=limit)
    return {"results": items}