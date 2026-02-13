from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any, Dict

import httpx

from src.app.deps import get_redis
from src.app.observability.metrics import record_email_security_connector_failure
from src.app.security.email_security import evaluate_email_security


def _pop(queue: str) -> Dict[str, Any] | None:
    r = get_redis()
    if r.__class__.__name__ == "DummyRedis":
        raise RuntimeError("redis_required")
    raw = None
    try:
        raw = r.rpop(queue)
    except Exception:
        raw = None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def run_gmail_loop() -> None:
    from src.app.connectors.email.gmail import fetch_message, list_message_ids, normalize_message

    user_id = os.getenv("GMAIL_USER_ID", "me")
    sleep_s = float(os.getenv("EMAIL_CONNECTOR_POLL_SLEEP_SEC", "1") or 1)

    http = httpx.Client(timeout=25)
    while True:
        item = _pop("q:email:gmail")
        if not item:
            time.sleep(sleep_s)
            continue
        tenant_id = item.get("tenant_id")
        msg_id = item.get("message_id")
        email_addr = item.get("emailAddress")
        # If message_id is provided, fetch exactly that message.
        if msg_id:
            try:
                msg = fetch_message(user_id=user_id, message_id=str(msg_id), client=http)
                email = normalize_message(msg=msg, tenant_id=tenant_id)
                evaluate_email_security(email, tenant_id=tenant_id)
            except Exception:
                record_email_security_connector_failure(tenant_id, "gmail", "fetch_error")
            continue
        # Otherwise, on notification-only mode, list a small recent window and evaluate.
        # Cursor stored by emailAddress to avoid reprocessing endlessly.
        if not email_addr:
            continue
        try:
            r = get_redis()
            cursor_key = f"cursor:gmail:last_seen:{tenant_id or 'default'}:{email_addr}"
            last = int(r.get(cursor_key) or 0) if r.__class__.__name__ != "DummyRedis" else 0
        except Exception:
            last = 0
        try:
            # Gmail query: last 1 day in inbox. (Refine later via historyId.)
            ids = list_message_ids(user_id=user_id, q="newer_than:1d", max_results=10, client=http)
            max_seen = last
            for mid in ids:
                msg = fetch_message(user_id=user_id, message_id=str(mid), client=http)
                try:
                    internal = int(msg.get("internalDate") or 0)
                except Exception:
                    internal = 0
                if internal and internal <= last:
                    continue
                email = normalize_message(msg=msg, tenant_id=tenant_id)
                evaluate_email_security(email, tenant_id=tenant_id)
                if internal and internal > max_seen:
                    max_seen = internal
            try:
                if max_seen and max_seen != last:
                    r = get_redis()
                    if r.__class__.__name__ != "DummyRedis":
                        r.setex(cursor_key, 7 * 86400, str(max_seen))
            except Exception:
                pass
        except Exception:
            record_email_security_connector_failure(tenant_id, "gmail", "list_fetch_error")


def run_m365_loop() -> None:
    from src.app.connectors.email.m365 import fetch_message, fetch_attachments_meta, normalize_message

    mailbox = os.getenv("M365_MAILBOX")
    if not mailbox:
        raise RuntimeError("M365_MAILBOX_required")
    sleep_s = float(os.getenv("EMAIL_CONNECTOR_POLL_SLEEP_SEC", "1") or 1)

    http = httpx.Client(timeout=25)
    while True:
        item = _pop("q:email:m365")
        if not item:
            time.sleep(sleep_s)
            continue
        tenant_id = item.get("tenant_id")
        msg_id = item.get("message_id")
        if not msg_id:
            continue
        try:
            msg = fetch_message(mailbox=mailbox, message_id=str(msg_id), client=http)
            atts = fetch_attachments_meta(mailbox=mailbox, message_id=str(msg_id), client=http)
            email = normalize_message(msg=msg, attachments=atts, tenant_id=tenant_id)
            evaluate_email_security(email, tenant_id=tenant_id)
        except Exception:
            record_email_security_connector_failure(tenant_id, "m365", "fetch_error")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gmail", "m365"], required=True)
    args = ap.parse_args()

    if args.provider == "gmail":
        run_gmail_loop()
    else:
        run_m365_loop()


if __name__ == "__main__":
    main()
