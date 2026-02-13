from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.app.connectors.email.oauth import get_gmail_access_token
from src.app.security.email_validation import validate_email_auth


def _b64url_decode(data: str) -> str:
    if not data:
        return ""
    try:
        # Gmail uses base64url without padding
        pad = "=" * (-len(data) % 4)
        raw = base64.urlsafe_b64decode((data + pad).encode("utf-8"))
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _headers_map(headers: List[Dict[str, Any]] | None) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in headers or []:
        try:
            k = str(h.get("name") or "").lower()
            v = str(h.get("value") or "")
            if k:
                out[k] = v
        except Exception:
            continue
    return out


def _extract_plain_text(payload: Dict[str, Any]) -> str:
    """Best-effort: find a text/plain part and return decoded body."""
    if not isinstance(payload, dict):
        return ""
    # Single-part
    try:
        mt = str(payload.get("mimeType") or "")
        if mt == "text/plain":
            data = ((payload.get("body") or {}) if isinstance(payload.get("body"), dict) else {}).get("data")
            return _b64url_decode(str(data or ""))
    except Exception:
        pass
    # Multi-part
    parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        mt = str(p.get("mimeType") or "")
        if mt == "text/plain":
            data = ((p.get("body") or {}) if isinstance(p.get("body"), dict) else {}).get("data")
            return _b64url_decode(str(data or ""))
        # recurse into nested multiparts
        if p.get("parts"):
            t = _extract_plain_text(p)
            if t:
                return t
    return ""


def _attachments_meta(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return out

    def walk(node: Dict[str, Any]):
        parts = node.get("parts") if isinstance(node.get("parts"), list) else []
        for p in parts or []:
            if not isinstance(p, dict):
                continue
            filename = str(p.get("filename") or "")
            if filename:
                body = p.get("body") if isinstance(p.get("body"), dict) else {}
                out.append(
                    {
                        "name": filename,
                        "content_type": p.get("mimeType"),
                        "size_bytes": int(body.get("size") or 0),
                    }
                )
            if p.get("parts"):
                walk(p)

    walk(payload)
    return out


def fetch_message(
    *,
    user_id: str,
    message_id: str,
    client: httpx.Client | None = None,
) -> Dict[str, Any]:
    tok = get_gmail_access_token(client)
    http = client or httpx.Client(timeout=20)
    r = http.get(
        f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages/{message_id}",
        params={"format": "full"},
        headers={"authorization": f"Bearer {tok}"},
    )
    r.raise_for_status()
    return r.json()

def list_message_ids(
    *,
    user_id: str,
    q: str | None = None,
    max_results: int = 10,
    client: httpx.Client | None = None,
) -> List[str]:
    tok = get_gmail_access_token(client)
    http = client or httpx.Client(timeout=20)
    params: Dict[str, Any] = {"maxResults": int(max_results or 10)}
    if q:
        params["q"] = q
    r = http.get(
        f"https://gmail.googleapis.com/gmail/v1/users/{user_id}/messages",
        params=params,
        headers={"authorization": f"Bearer {tok}"},
    )
    r.raise_for_status()
    data = r.json()
    msgs = data.get("messages") if isinstance(data.get("messages"), list) else []
    out: List[str] = []
    for m in msgs or []:
        if isinstance(m, dict) and m.get("id"):
            out.append(str(m["id"]))
    return out


def normalize_message(*, msg: Dict[str, Any], tenant_id: str | None = None) -> Dict[str, Any]:
    """Normalize a Gmail message JSON into canonical EmailEvent shape."""
    payload = msg.get("payload") if isinstance(msg.get("payload"), dict) else {}
    hdrs = _headers_map(payload.get("headers") if isinstance(payload.get("headers"), list) else [])

    subject = hdrs.get("subject") or ""
    from_addr = hdrs.get("from") or ""
    reply_to = hdrs.get("reply-to") or None
    message_id = hdrs.get("message-id") or msg.get("id") or None
    conversation_id = msg.get("threadId") or None

    body = _extract_plain_text(payload)
    max_body = int(os.getenv("EMAIL_BODY_MAX_CHARS", "20000") or 20000)
    if len(body) > max_body:
        body = body[:max_body]

    attachments = _attachments_meta(payload)

    # DMARC/SPF/DKIM from Authentication-Results when present
    auth = validate_email_auth({"Authentication-Results": hdrs.get("authentication-results") or ""})
    dmarc_fail = auth.get("dmarc_pass") is False

    return {
        "provider": "gmail",
        "tenant_id": tenant_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "from_addr": from_addr,
        "reply_to": reply_to,
        "subject": subject,
        "body": body,
        "attachments": attachments,
        "dmarc_fail": bool(dmarc_fail),
    }
