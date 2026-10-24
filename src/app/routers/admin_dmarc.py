import os
from fastapi import APIRouter, Depends, Query
from fastapi.responses import ORJSONResponse

from src.app.services.dmarc_ingest import get_summary
from src.app.security.auth import require_role, ROLE_OWNER, ROLE_DEVELOPER

router = APIRouter(prefix="/api/v1/admin/dmarc", tags=["admin","security"],
                   dependencies=[Depends(require_role([ROLE_OWNER, ROLE_DEVELOPER]))])


def _emit_splunk(event: dict) -> None:
    url = os.getenv("SPLUNK_HEC_URL")
    token = os.getenv("SPLUNK_HEC_TOKEN")
    if not url or not token:
        return
    try:
        import requests

        body = {
            "time": int(__import__("time").time()),
            "sourcetype": "shopsquire:security",
            "source": "dmarc-dashboard",
            "event": event,
        }
        requests.post(url, headers={"Authorization": f"Splunk {token}"}, json=body, timeout=5)
    except Exception:
        pass


@router.get("/summary")
def admin_summary(days: int = Query(30, ge=1, le=365)):
    # Dashboard reads have no alerting side effects or caller-owned thresholds.
    s = get_summary(days=days)
    return ORJSONResponse({"summary": s, "fail_rate": s.get('fail_rate')})
