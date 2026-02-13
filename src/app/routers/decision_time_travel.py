from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from sqlalchemy import text as _text
from src.app.models.db import db_session

router = APIRouter(prefix="/api/v1/admin/decisions", tags=["admin_decisions"])


@router.get("/asof")
def decision_as_of(decision_id: str = Query(...), timestamp: str = Query(...)):
    """Return decision state as-of a timestamp using bitemporal columns."""
    try:
        with db_session() as db:
            row = db.execute(
                _text(
                    """
                    SELECT id, agent_name, input_data, retrieved_context, proposed_action, policy_version, approval_required, execution_status
                    FROM decision_logs
                    WHERE id = :id AND valid_from <= :ts AND (valid_to IS NULL OR valid_to = 'infinity' OR valid_to >= :ts)
                    ORDER BY valid_from DESC
                    LIMIT 1
                    """
                ),
                {"id": decision_id, "ts": timestamp},
            ).mappings().all()
            if not row:
                raise HTTPException(status_code=404, detail="no state found")
            return row[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="error querying decision state")
