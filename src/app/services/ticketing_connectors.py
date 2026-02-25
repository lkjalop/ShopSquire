from __future__ import annotations

from typing import Optional
import json
import requests
from src.app.services.secrets_manager import get_secret
from src.app.security.safe_requests import safe_post


def _sanitize_summary(summary: str) -> str:
    s = summary or ""
    if len(s) > 240:
        s = s[:240] + "…"
    return s


def create_jira_issue(summary: str, description: str, severity: str) -> Optional[str]:
    """Env-gated Jira issue creation (returns external id or None)."""
    base = get_secret("JIRA_BASE_URL")
    project = get_secret("JIRA_PROJECT_KEY")
    token = get_secret("JIRA_API_TOKEN")
    user = get_secret("JIRA_USER") or get_secret("JIRA_EMAIL")
    if not (base and project and token and user):
        return None
    try:
        url = base.rstrip("/") + "/rest/api/3/issue"
        headers = {"Content-Type": "application/json"}
        auth = (user, token)
        payload = {
            "fields": {
                "project": {"key": project},
                "summary": _sanitize_summary(summary),
                "description": (description or "")[:2000],
                "issuetype": {"name": "Task"},
                "priority": {"name": "High" if severity in ("high", "critical") else "Medium"},
            }
        }
        resp = safe_post(url, headers=headers, auth=auth, data=json.dumps(payload), timeout=8)
        if resp.ok:
            jid = resp.json().get("key")
            return str(jid) if jid else None
        return None
    except Exception:
        return None


def create_servicenow_incident(summary: str, description: str, severity: str) -> Optional[str]:
    """Env-gated ServiceNow incident creation (returns external id or None)."""
    base = get_secret("SN_INSTANCE_URL")
    user = get_secret("SN_USERNAME")
    pwd = get_secret("SN_PASSWORD")
    token = get_secret("SN_TOKEN")
    table = get_secret("SN_TABLE", "incident")
    if not base:
        return None
    try:
        url = base.rstrip("/") + f"/api/now/table/{table}"
        headers = {"Content-Type": "application/json"}
        auth = None
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif user and pwd:
            auth = (user, pwd)
        else:
            return None
        payload = {
            "short_description": _sanitize_summary(summary),
            "description": (description or "")[:2000],
            "severity": 1 if severity == "critical" else (2 if severity == "high" else 3),
        }
        resp = safe_post(url, headers=headers, auth=auth, data=json.dumps(payload), timeout=8)
        if resp.ok:
            rid = resp.json().get("result", {}).get("sys_id")
            return str(rid) if rid else None
        return None
    except Exception:
        return None
