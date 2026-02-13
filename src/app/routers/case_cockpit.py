from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER
from sqlalchemy import text as _text
from src.app.services.db_read_routing import read_session
from src.app.services.dependency_resilience import call_with_resilience

router = APIRouter(prefix="/api/v1/admin/cases", tags=["admin_cases"])


@router.get("/{case_id}/cockpit")
def case_cockpit(case_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER]))):
    """Return a unified case cockpit summary: evidence, human review, CV, decision logs."""
    summary: Dict[str, Any] = {"case_id": case_id, "evidence": [], "human_review": [], "cv": [], "decisions": []}
    try:
        with read_session(read_class="dashboard") as db:
            ev = call_with_resilience(
                "db.cockpit.evidence",
                lambda: db.execute(_text("SELECT id, created_at FROM evidence_bundles WHERE case_id = :cid ORDER BY created_at DESC"), {"cid": case_id}).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            hr = call_with_resilience(
                "db.cockpit.human_review",
                lambda: db.execute(_text("SELECT id, status, reviewer_id, created_at, updated_at FROM human_review_tasks WHERE case_id = :cid ORDER BY created_at DESC"), {"cid": case_id}).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            cv = call_with_resilience(
                "db.cockpit.cv",
                lambda: db.execute(_text("SELECT id, damage_type, severity, confidence, serial_number, created_at FROM cv_analyses WHERE case_id = :cid ORDER BY created_at DESC"), {"cid": case_id}).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            # Decision logs aren't directly linked to case_id in all flows; include recent decisions and filter by input_data mentioning case_id
            decs = call_with_resilience(
                "db.cockpit.decisions",
                lambda: db.execute(_text("SELECT id, agent_name, valid_from, proposed_action, approval_required, execution_status FROM decision_logs ORDER BY valid_from DESC LIMIT 50")).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            summary["evidence"] = ev
            summary["human_review"] = hr
            summary["cv"] = cv
            # Filter decisions that mention the case_id in proposed_action or input_data (best-effort)
            filtered = []
            for d in decs:
                try:
                    import json
                    pa = d.get("proposed_action")
                    obj = json.loads(pa) if isinstance(pa, str) else (pa or {})
                    if case_id and (str(obj).find(case_id) != -1):
                        filtered.append(d)
                except Exception:
                    pass
            summary["decisions"] = filtered
    except Exception:
        raise HTTPException(status_code=500, detail="error building cockpit")
    return summary


@router.get("/{case_id}/tags")
def case_tags(case_id: str, role: str = Depends(require_role([ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER]))):
    """Derive evidence tags from CV and policy for filtering."""
    tags = []
    try:
        with read_session(read_class="timeline") as db:
            cv = call_with_resilience(
                "db.cockpit.tags.cv",
                lambda: db.execute(_text("SELECT damage_type, severity, serial_number FROM cv_analyses WHERE case_id = :cid ORDER BY created_at DESC LIMIT 1"), {"cid": case_id}).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            if cv:
                row = cv[0]
                if row.get("serial_number"):
                    tags.append("serial_present")
                if (row.get("damage_type") or "") == "unknown":
                    tags.append("damage_unknown")
            hr = call_with_resilience(
                "db.cockpit.tags.hr",
                lambda: db.execute(_text("SELECT status FROM human_review_tasks WHERE case_id = :cid ORDER BY created_at DESC LIMIT 1"), {"cid": case_id}).mappings().all(),
                timeout_s=3.0,
                retries=1,
            )
            if hr and (hr[0].get("status") or "") == "pending":
                tags.append("approval_required")
    except Exception:
        pass
    return {"case_id": case_id, "tags": tags}
