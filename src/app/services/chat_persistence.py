from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session


def store_chat_message(
    db: Any,
    *,
    uid: str,
    role: str,
    content: str,
    trace_id: str | None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
) -> str | None:
    """Persist optional chat evidence without poisoning the request transaction."""
    if not str(content or "").strip():
        return None
    from src.app.platform.tenant_context import current_tenant_id

    message_id = str(uuid.uuid4())
    bounded_uid = str(uid or "anonymous")[:128]
    bounded_session_id = str(session_id or "")[:128] or None
    params = {
        "id": message_id,
        "tenant_id": str(tenant_id or current_tenant_id() or "default")[:128],
        "uid": bounded_uid,
        "session_id": bounded_session_id,
        "session_epoch": str(session_epoch or bounded_session_id or bounded_uid)[:128],
        "role": str(role or "assistant")[:32],
        "content": str(content or "")[:8000],
        "trace_id": str(trace_id or "")[:128] or None,
    }
    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
    if bind is None:
        raise RuntimeError("chat_message_store_requires_database_bind")
    with Session(bind=bind, future=True) as message_db:
        message_db.execute(
            sql_text(
                """
                INSERT INTO chat_messages
                    (id, tenant_id, uid, session_id, session_epoch, role, content, trace_id)
                VALUES
                    (:id, :tenant_id, :uid, :session_id, :session_epoch, :role, :content, :trace_id)
                """
            ),
            params,
        )
        message_db.commit()
    return message_id
