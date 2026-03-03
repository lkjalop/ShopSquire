from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from src.app.connectors.email.oauth import get_m365_access_token
from src.app.security.email_validation import validate_email_auth


def fetch_message(
    *,
    mailbox: str,
    message_id: str,
    client: httpx.Client | None = None,
) -> Dict[str, Any]:
    tok = get_m365_access_token(client)
    http = client or httpx.Client(timeout=20)
    r = http.get(
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}",
        params={"$select": "id,internetMessageId,subject,from,replyTo,conversationId,bodyPreview,body"},
        headers={"authorization": f"Bearer {tok}"},
    )
    r.raise_for_status()
    return r.json()


def fetch_attachments_meta(
    *,
    mailbox: str,
    message_id: str,
    client: httpx.Client | None = None,
) -> List[Dict[str, Any]]:
    tok = get_m365_access_token(client)
    http = client or httpx.Client(timeout=20)
    r = http.get(
        f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{message_id}/attachments",
        params={"$select": "name,contentType,size"},
        headers={"authorization": f"Bearer {tok}"},
    )
    r.raise_for_status()
    data = r.json()
    vals = data.get("value") if isinstance(data.get("value"), list) else []
    out: List[Dict[str, Any]] = []
    for a in vals or []:
        if not isinstance(a, dict):
            continue
        out.append(
            {
                "name": a.get("name"),
                "content_type": a.get("contentType"),
                "size_bytes": int(a.get("size") or 0),
            }
        )
    return out


def normalize_message(
    *,
    msg: Dict[str, Any],
    attachments: List[Dict[str, Any]] | None = None,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    subject = str(msg.get("subject") or "")
    from_addr = ""
    try:
        frm = msg.get("from") or {}
        addr = ((frm.get("emailAddress") or {}) if isinstance(frm, dict) else {})
        from_addr = str(addr.get("address") or "")
        name = str(addr.get("name") or "")
        if name and from_addr:
            from_addr = f"{name} <{from_addr}>"
    except Exception:
        pass
    reply_to = None
    try:
        rt = msg.get("replyTo") if isinstance(msg.get("replyTo"), list) else []
        if rt:
            addr = (rt[0].get("emailAddress") or {}) if isinstance(rt[0], dict) else {}
            reply_to = str(addr.get("address") or "") or None
    except Exception:
        reply_to = None

    message_id = msg.get("internetMessageId") or msg.get("id")
    conversation_id = msg.get("conversationId")

    body = str(msg.get("bodyPreview") or "")
    try:
        # Prefer plain text when present and safe size.
        b = msg.get("body") if isinstance(msg.get("body"), dict) else None
        if b and str(b.get("contentType") or "").lower() == "text":
            body = str(b.get("content") or body)
    except Exception:
        pass
    max_body = int(os.getenv("EMAIL_BODY_MAX_CHARS", "20000") or 20000)
    if len(body) > max_body:
        body = body[:max_body]

    # DMARC/SPF/DKIM + ARC/BIMI if caller provides auth headers (Graph varies by tenant/config).
    dmarc_fail = False
    auth: Dict[str, Any] = {}
    try:
        auth = validate_email_auth(
            {
                "Authentication-Results": str(msg.get("authenticationResults") or ""),
                "ARC-Authentication-Results": str(msg.get("arcAuthenticationResults") or ""),
                "ARC-Seal": str(msg.get("arcSeal") or ""),
                "ARC-Message-Signature": str(msg.get("arcMessageSignature") or ""),
                "BIMI-Location": str(msg.get("bimiLocation") or ""),
                "BIMI-Indicator": str(msg.get("bimiIndicator") or ""),
            }
        )
        dmarc_fail = auth.get("dmarc_pass") is False
    except Exception:
        dmarc_fail = False

    return {
        "provider": "m365",
        "tenant_id": tenant_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "from_addr": from_addr,
        "reply_to": reply_to,
        "subject": subject,
        "body": body,
        "attachments": attachments or [],
        "dmarc_fail": bool(dmarc_fail),
        "spf_result": auth.get("spf_result"),
        "dkim_result": auth.get("dkim_result"),
        "dmarc_result": auth.get("dmarc_result"),
        "arc_present": bool(auth.get("arc_present")),
        "arc_cv": auth.get("arc_cv"),
        "arc_chain_valid": auth.get("arc_chain_valid"),
        "bimi_present": bool(auth.get("bimi_present")),
        "bimi_result": auth.get("bimi_result"),
        "bimi_location": auth.get("bimi_location"),
    }
