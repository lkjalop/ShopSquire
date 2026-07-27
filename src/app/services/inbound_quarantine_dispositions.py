"""Audited terminal dispositions for quarantined inbound supplier email."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

ALLOWED_ACTIONS = {"keep_quarantined", "discard", "open_fresh_rfq"}


def record_disposition(
    db,
    *,
    tenant_id: str,
    inbox_id: str,
    action: str,
    actor_id: str,
    note: Optional[str] = None,
    fresh_case_id: Optional[str] = None,
) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ValueError("invalid_quarantine_disposition")
    row = db.execute(
        text(
            "SELECT status, fulfillment_case_id FROM inbound_email_inbox "
            "WHERE id=:id AND tenant_id=:tenant"
        ),
        {"id": inbox_id, "tenant": tenant_id},
    ).fetchone()
    if not row:
        raise ValueError("inbound_email_not_found")
    if str(row[0]) not in {"quarantined", "case_quarantined"}:
        raise ValueError("inbound_email_not_quarantined")
    disposition_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    db.execute(
        text(
            "INSERT INTO inbound_email_quarantine_disposition "
            "(id, tenant_id, inbox_id, action, actor_id, note, fresh_case_id, created_at) "
            "VALUES (:id,:tenant,:inbox,:action,:actor,:note,:fresh_case,:created_at)"
        ),
        {
            "id": disposition_id,
            "tenant": tenant_id,
            "inbox": inbox_id,
            "action": action,
            "actor": actor_id,
            "note": str(note or "")[:2000] or None,
            "fresh_case": fresh_case_id,
            "created_at": now,
        },
    )
    db.execute(
        text(
            "UPDATE inbound_email_inbox SET status=:status, updated_at=:updated "
            "WHERE id=:id AND tenant_id=:tenant"
        ),
        {
            "status": f"disposed_{action}",
            "updated": now,
            "id": inbox_id,
            "tenant": tenant_id,
        },
    )
    return {
        "id": disposition_id,
        "inbox_id": inbox_id,
        "action": action,
        "fresh_case_id": fresh_case_id,
        "created_at": now.isoformat(),
    }
