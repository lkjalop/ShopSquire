from fastapi import APIRouter, HTTPException, Query
from src.app.services.decision_replay import decisions_as_of

router = APIRouter(prefix="/api/v1/admin/decisions", tags=["admin_decisions"])


@router.get("/asof")
def decision_as_of(decision_id: str = Query(...), timestamp: str = Query(...)):
    """Return decision state as-of a timestamp using bitemporal columns."""
    try:
        rows = decisions_as_of(timestamp=timestamp, decision_id=decision_id, limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="no state found")
        return rows[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="error querying decision state")
