import os
from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from src.app.services.dmarc_ingest import get_summary

router = APIRouter(prefix="/api/v1/admin/dmarc", tags=["admin","security"])


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
def admin_summary(threshold_fail_rate: float = 0.2):
    s = get_summary(days=30)
    # Calculate a naive fail rate across top domains
    total_reports = 0
    total_fails = 0
    for dom, reports, fails in s.get("top_domains", []):
        total_reports += int(reports or 0)
        total_fails += int(fails or 0)
    rate = (float(total_fails) / float(total_reports)) if total_reports > 0 else 0.0
    if rate >= float(threshold_fail_rate):
        _emit_splunk({"component": "dmarc_summary", "severity": "warning", "fail_rate": rate, "total_reports": total_reports, "total_fails": total_fails})
    return ORJSONResponse({"summary": s, "fail_rate": rate})
