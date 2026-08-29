from __future__ import annotations

import json
import uuid
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER
from src.app.services.fairness import demographic_parity
from src.app.models.compliance_registry import insert_artifact


router = APIRouter(prefix="/api/v1/admin/fairness", tags=["admin", "fairness"])


@router.post("/audit")
def run_fairness_audit(payload: Dict[str, Any], role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))) -> Dict:
    """Compute a simple demographic parity audit and store the result in the compliance registry.

    Expected payload:
    {
      "y_true": [0,1, ...],
      "y_pred": [0,1, ...],
      "sensitive": [0,1, ...],  # binary sensitive attribute
      "threshold": 0.1  # allowable parity difference, optional (default 0.1)
    }
    """
    try:
        y_true: List[int] = [int(x) for x in (payload.get("y_true") or [])]
        y_pred: List[int] = [int(x) for x in (payload.get("y_pred") or [])]
        sensitive: List[int] = [int(x) for x in (payload.get("sensitive") or [])]
        threshold: float = float(payload.get("threshold") or 0.1)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_payload")

    if not (y_true and y_pred and sensitive):
        raise HTTPException(status_code=400, detail="missing_arrays")
    if not (len(y_true) == len(y_pred) == len(sensitive)):
        raise HTTPException(status_code=400, detail="length_mismatch")

    metrics = demographic_parity(y_true, y_pred, sensitive)
    if metrics.get("error"):
        raise HTTPException(status_code=400, detail=str(metrics.get("error")))

    diff = metrics.get("demographic_parity_diff")
    if diff is None:
        status = "warn"
    else:
        status = "pass" if float(diff) <= float(threshold) else "warn"

    audit_id = str(uuid.uuid4())
    details = {
        "type": "fairness_audit",
        "metric": "demographic_parity",
        "threshold": threshold,
        "metrics": metrics,
        "sizes": {"n": len(y_true)},
    }

    res = insert_artifact(
        id=audit_id,
        artifact_type="fairness_audit",
        vendor="internal",
        scan_id=None,
        status=status,
        details=json.dumps(details, ensure_ascii=False),
    )
    if not res.get("inserted"):
        raise HTTPException(status_code=500, detail=res.get("error") or "insert_failed")

    return {"audit_id": audit_id, "status": status, "metrics": metrics}
