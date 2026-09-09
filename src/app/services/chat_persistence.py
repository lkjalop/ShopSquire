from __future__ import annotations

import uuid
import os
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from src.app.services.memory import Memory

import base64
from typing import Dict, List
from src.app.services.chat_turn_projection import _extract_budget_bounds, _extract_brand_mentions


def _store_chat_message(
    db,
    *,
    uid: str,
    role: str,
    content: str,
    trace_id: str | None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
) -> str | None:
    from src.app.services.chat_persistence import store_chat_message

    return store_chat_message(
        db,
        uid=uid,
        role=role,
        content=content,
        trace_id=trace_id,
        session_id=session_id,
        tenant_id=tenant_id,
        session_epoch=session_epoch,
    )


def _stash_image_blob_for_recommend(mem: Memory, uid: str, image_hash: str, image_bytes: bytes) -> None:
    if not uid or not image_hash or not image_bytes:
        return
    max_bytes = int(os.getenv("CHAT_IMAGE_BLOB_CACHE_MAX_BYTES", "262144") or 262144)
    if len(image_bytes) > max_bytes:
        return
    kv = mem.get_kv(uid) or {}
    blob_cache = kv.get("image_blob_cache") if isinstance(kv.get("image_blob_cache"), dict) else {}
    blob_cache[str(image_hash)] = base64.b64encode(image_bytes).decode("ascii")
    # Keep only latest 2 blobs to bound session size.
    keys = list(blob_cache.keys())
    if len(keys) > 2:
        for k in keys[:-2]:
            blob_cache.pop(k, None)
    kv["image_blob_cache"] = blob_cache
    mem.set_kv(uid, kv)


def _persist_chat_structured_state(
    *,
    redis,
    uid: str,
    query: str,
    products: List[Dict[str, Any]] | None,
    trace_id: str | None,
    assistant_message: str | None = None,
    recent_messages: List[Dict[str, Any]] | None = None,
    confirmed_slots: Dict[str, Any] | None = None,
    semantic_resolution: Dict[str, Any] | None = None,
    case_anchor: Dict[str, Any] | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
) -> None:
    from src.app.services.chat_persistence import persist_chat_structured_state

    return persist_chat_structured_state(
        redis=redis, uid=uid, query=query, products=products, trace_id=trace_id,
        budget=_extract_budget_bounds(query), brands=_extract_brand_mentions(query),
        assistant_message=assistant_message, recent_messages=recent_messages,
        confirmed_slots=confirmed_slots, semantic_resolution=semantic_resolution,
        case_anchor=case_anchor, tenant_id=tenant_id, session_epoch=session_epoch,
    )



@dataclass(frozen=True)
class ChatResultPersistenceReceipt:
    assistant_message: str
    structured_state: str
    errors: tuple[str, ...] = ()


def persist_chat_result(
    db: Any,
    *,
    redis: Any,
    uid: str,
    query: str,
    products: list[dict[str, Any]] | None,
    trace_id: str | None,
    assistant_message: str,
    budget: dict[str, int | None],
    brands: list[str],
    session_id: str | None = None,
    tenant_id: str | None = None,
    session_epoch: str | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    confirmed_slots: dict[str, Any] | None = None,
    semantic_resolution: dict[str, Any] | None = None,
    case_anchor: dict[str, Any] | None = None,
    turn_read_model: dict[str, Any] | None = None,
) -> ChatResultPersistenceReceipt:
    """Persist a completed assistant result through independent optional stores."""
    errors: list[str] = []
    message_status = "skipped_empty"
    structured_status = "not_attempted"
    try:
        message_id = store_chat_message(
            db,
            uid=uid,
            role="assistant",
            content=assistant_message,
            trace_id=trace_id,
            session_id=session_id,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
        message_status = "persisted" if message_id else "skipped_empty"
    except Exception as exc:
        message_status = "failed"
        errors.append(f"assistant_message:{type(exc).__name__}")
    try:
        persist_chat_structured_state(
            redis=redis,
            uid=uid,
            query=query,
            products=products,
            trace_id=trace_id,
            budget=budget,
            brands=brands,
            assistant_message=assistant_message,
            recent_messages=recent_messages,
            confirmed_slots=confirmed_slots,
            semantic_resolution=semantic_resolution,
            case_anchor=case_anchor,
            turn_read_model=turn_read_model,
            tenant_id=tenant_id,
            session_epoch=session_epoch,
        )
        structured_status = "persisted"
    except Exception as exc:
        structured_status = "failed"
        errors.append(f"structured_state:{type(exc).__name__}")
    return ChatResultPersistenceReceipt(
        assistant_message=message_status,
        structured_state=structured_status,
        errors=tuple(errors),
    )


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


def _recent_messages(rows: Any, *, limit: int = 16) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip().lower()
        content = str(row.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            normalized.append({"role": role, "content": content[:500]})
    return normalized[-max(1, int(limit)):]


def persist_chat_structured_state(
    *, redis: Any, uid: str, query: str, products: list[dict[str, Any]] | None,
    trace_id: str | None, budget: dict[str, int | None], brands: list[str],
    assistant_message: str | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    confirmed_slots: dict[str, Any] | None = None,
    semantic_resolution: dict[str, Any] | None = None,
    case_anchor: dict[str, Any] | None = None,
    turn_read_model: dict[str, Any] | None = None,
    tenant_id: str | None = None, session_epoch: str | None = None,
) -> None:
    """Persist bounded conversational state without recommendation dispatch authority."""
    mem = Memory(redis, tenant_id=tenant_id, session_epoch=session_epoch)
    prior = mem.get_structured_state(uid) or {}
    skus = [str((row or {}).get("sku") or "") for row in (products or []) if isinstance(row, dict)]
    skus = [sku for sku in skus if sku][:12]
    out = dict(prior)
    out.update({
        "last_chat_query": str(query or "")[:500], "last_chat_trace_id": trace_id,
        "last_chat_ts": int(time.time()),
        "cache_only": True,
        "durable_authority": "postgres_case_revision",
    })
    merged = dict(out.get("confirmed_slots") or {})
    if budget.get("budget_min") is not None:
        merged["budget_min"] = budget["budget_min"]
    if budget.get("budget_max") is not None:
        merged["budget_max"] = budget["budget_max"]
    if brands:
        merged["brands"] = brands[:6]
    for key, value in (confirmed_slots or {}).items():
        if value is not None and not (isinstance(value, list) and not value):
            merged[str(key)] = value
    excluded = {str(value).strip().lower() for value in merged.get("brand_excludes", [])
                if str(value).strip()}
    if excluded and isinstance(merged.get("brands"), list):
        kept = [value for value in merged["brands"] if str(value).strip().lower() not in excluded]
        if kept:
            merged["brands"] = kept
        else:
            merged.pop("brands", None)
    if merged:
        out["confirmed_slots"] = merged
        for key in ("budget_min", "budget_max"):
            if merged.get(key) is not None:
                out[key] = merged[key]
        if merged.get("brands"):
            out["brands"] = list(merged["brands"])[:6]
    recent = _recent_messages(recent_messages or out.get("recent_messages"))
    recent.append({"role": "user", "content": str(query or "")[:500]})
    if str(assistant_message or "").strip():
        recent.append({"role": "assistant", "content": str(assistant_message)[:500]})
    out["recent_messages"] = _recent_messages(recent)
    if skus:
        out["last_shortlist_skus"] = skus
        out["last_valid_shortlist_skus"] = skus
    if isinstance(semantic_resolution, dict):
        if semantic_resolution.get("catalog_authority") == "blocked":
            out["semantic_resolution"] = dict(semantic_resolution)
        elif semantic_resolution.get("catalog_authority") == "permitted":
            out.pop("semantic_resolution", None)
    if isinstance(case_anchor, dict) and str(case_anchor.get("case_id") or "").strip():
        out["case_anchor"] = dict(case_anchor)
    if isinstance(turn_read_model, dict):
        # A convenience copy for reconnect rendering only. It never grants
        # authority; its case id + revision point back to PostgreSQL truth.
        out["turn_read_model_cache"] = dict(turn_read_model)
    mem.set_structured_state(uid, out)
    bank = mem.get_product_memory_bank(uid) or {}
    history = list(bank.get("chat_turns") or [])
    history.append({
        "ts": int(time.time()), "trace_id": trace_id, "query": str(query or "")[:300],
        "shortlist_skus": skus, "budget_min": out.get("budget_min"),
        "budget_max": out.get("budget_max"),
    })
    bank["chat_turns"] = history[-20:]
    if skus:
        bank["last_shortlist_skus"] = skus
    bank["last_trace_id"] = trace_id
    mem.set_product_memory_bank(uid, bank)


__all__ = [
    "ChatResultPersistenceReceipt",
    "persist_chat_result",
    "persist_chat_structured_state",
    "store_chat_message",
]
