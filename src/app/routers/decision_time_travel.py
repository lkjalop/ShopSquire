from fastapi import APIRouter, Depends, HTTPException, Query
from src.app.security.auth import ROLE_OWNER, ROLE_DEVELOPER, require_role
from src.app.services.decision_replay import decisions_as_of

router = APIRouter(prefix="/api/v1/admin/decisions", tags=["admin_decisions"])


@router.get("/asof")
def decision_as_of(
    decision_id: str = Query(...), timestamp: str = Query(...),
    known_at: str | None = Query(None),
    role: str = Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER])),
):
    """Tenant-scoped valid-time snapshot, as known at the specified knowledge time.

    With one timestamp both axes use that instant; knowledge time is never
    silently substituted with today's state.
    """
    try:
        rows = decisions_as_of(timestamp=timestamp, known_at=known_at,
                               decision_id=decision_id, limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="no state found")
        return rows[0]
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_decision_history_timestamp") from None
    except Exception:
        raise HTTPException(status_code=500, detail="error querying decision state")
