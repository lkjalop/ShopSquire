"""Durable outbound-message/thread correlation for inbound supplier replies."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import bindparam, text

_ANGLE_ID = re.compile(r"<[^<>]{1,510}>")


def record_outbound_reference(
    db,
    *,
    tenant_id: str,
    provider: str,
    provider_message_id: str,
    case_id: str,
    thread_id: Optional[str] = None,
) -> None:
    provider_ref = str(provider_message_id or "").strip()
    if not provider_ref:
        return
    db.execute(
        text(
            "INSERT INTO outbound_email_correlation "
            "(id, tenant_id, provider, provider_message_id, provider_thread_id, "
            "fulfillment_case_id, created_at) "
            "VALUES (:id,:tenant,:provider,:message,:thread,:case_id,:created_at) "
            "ON CONFLICT (tenant_id, provider, provider_message_id) DO NOTHING"
        ),
        {
            "id": str(uuid.uuid4()),
            "tenant": tenant_id,
            "provider": str(provider or "supplier_transport").lower(),
            "message": provider_ref[:512],
            "thread": str(thread_id or "")[:512] or None,
            "case_id": case_id,
            "created_at": datetime.now(timezone.utc),
        },
    )


def _candidate_references(email: Dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in ("in_reply_to", "references", "thread_id"):
        raw = str(email.get(field) or "").strip()
        if not raw:
            continue
        values.extend(_ANGLE_ID.findall(raw))
        values.extend(raw.split())
        values.append(raw)
    return list(dict.fromkeys(value[:512] for value in values if value))


def resolve_case_from_thread(
    db,
    *,
    tenant_id: str,
    provider: str,
    email: Dict[str, Any],
) -> Optional[str]:
    refs = _candidate_references(email)
    if not refs:
        return None
    rows = db.execute(
        text(
            "SELECT DISTINCT fulfillment_case_id FROM outbound_email_correlation "
            "WHERE tenant_id=:tenant AND "
            "(provider=:provider OR provider='supplier_transport') AND "
            "(provider_message_id IN :message_refs OR provider_thread_id IN :thread_refs)"
        ).bindparams(
            bindparam("message_refs", expanding=True),
            bindparam("thread_refs", expanding=True),
        ),
        {
            "tenant": tenant_id,
            "provider": str(provider or "").lower(),
            "message_refs": refs,
            "thread_refs": refs,
        },
    ).fetchall()
    cases = {str(row[0]) for row in rows if row and row[0]}
    return next(iter(cases)) if len(cases) == 1 else None
