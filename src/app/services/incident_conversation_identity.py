"""Server-owned identity and event projections for human escalation chat.

The browser may choose a transport, but it must never choose who a staff member is.
This module keeps that security boundary independent from the large incident router.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any


_STAFF_DEFAULTS = {
    "merchant": ("ShopSquire Support", "Product specialist"),
    "owner": ("ShopSquire Support Lead", "Support lead"),
    "developer": ("ShopSquire Technical Support", "Technical specialist"),
    "staff": ("ShopSquire Support", "Product specialist"),
}


def server_actor_identity(role: str, *, subject: str | None = None) -> dict[str, Any]:
    normalized = str(role or "system").strip().lower()
    if normalized == "buyer":
        return {
            "actor_id": "buyer",
            "actor_type": "buyer",
            "display_name": "You",
            "title": "Buyer",
            "avatar_url": None,
            "identity_source": "incident_token",
        }
    if normalized in _STAFF_DEFAULTS:
        default_name, default_title = _STAFF_DEFAULTS[normalized]
        env_prefix = f"INCIDENT_STAFF_{normalized.upper()}"
        display_name = str(os.getenv(f"{env_prefix}_DISPLAY_NAME", default_name) or default_name).strip()
        title = str(os.getenv(f"{env_prefix}_TITLE", default_title) or default_title).strip()
        avatar_url = str(os.getenv(f"{env_prefix}_AVATAR_URL", "") or "").strip() or None
        safe_subject = "".join(ch for ch in str(subject or "") if ch.isalnum() or ch in "-_.")[:80]
        return {
            "actor_id": f"staff:{safe_subject or normalized}",
            "actor_type": "human_staff",
            "display_name": display_name,
            "title": title,
            "avatar_url": avatar_url,
            "identity_source": "authenticated_server_role",
        }
    return {
        "actor_id": normalized or "system",
        "actor_type": "system",
        "display_name": "ShopSquire",
        "title": "System",
        "avatar_url": None,
        "identity_source": "server",
    }


def build_conversation_event(
    *,
    incident_id: str,
    role: str,
    message: str,
    event_type: str = "message",
    meta: dict[str, Any] | None = None,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    resolved_actor = actor or server_actor_identity(role)
    event_id = f"ice-{uuid.uuid4().hex}"
    return {
        "id": event_id,
        "event_id": event_id,
        "incident_id": incident_id,
        "role": role,
        "message": message,
        "event_type": event_type,
        "actor": resolved_actor,
        "meta": {**(meta or {}), "actor_identity": resolved_actor},
        "ts": now_ms,
        "time": time.strftime("%H:%M", time.localtime(now_ms / 1000)),
        "delivery_status": "delivered",
    }
