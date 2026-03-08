from __future__ import annotations

import json
import re
import time
import uuid
import base64
import hashlib
import os
from threading import RLock
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import text as sql_text

from src.app.security.auth import require_role, ROLE_DEVELOPER, ROLE_MERCHANT, ROLE_OWNER
from src.app.deps import get_redis
from src.app.models.db import get_db
from src.app.services.memory import Memory
from src.app.services.llm_provider import select_ollama_model, ollama_generate, is_complex_query, score_query_complexity
from src.app.services.search_events import log_search_event
from src.app.security.model_theft import enforce_model_theft_rate_limit, enforce_model_theft_policy_gate
from src.app.services.image_intent_router import classify_image_intent
from src.app.services.decision_log import log_trace_event


router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_CHAT_REPLAY_LOCAL: Dict[str, float] = {}
_CHAT_REPLAY_LOCK = RLock()


def _normalize_recent_messages(raw: Any, *, limit: int = 16) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    rows = raw if isinstance(raw, list) else []
    for item in rows:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant", "system"} or not content:
            continue
        out.append({"role": role[:10], "content": content[:500]})
    return out[-max(1, int(limit or 1)) :]


def _extract_confirmed_slots(*, query: str, response: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    budget = _extract_budget_bounds(query)
    if budget.get("budget_min") is not None:
        out["budget_min"] = budget.get("budget_min")
    if budget.get("budget_max") is not None:
        out["budget_max"] = budget.get("budget_max")
    brands = _extract_brand_mentions(query)
    if brands:
        out["brands"] = brands[:6]

    data = response if isinstance(response, dict) else {}
    applied = data.get("nqe_selection_applied") if isinstance(data.get("nqe_selection_applied"), dict) else {}
    used = data.get("constraints_used") if isinstance(data.get("constraints_used"), dict) else {}
    for key in ("budget_min", "budget_max", "use_case", "gpu_preference", "availability", "condition", "buyer_persona", "issue_type"):
        v = applied.get(key)
        if v is None:
            v = used.get(key)
        if v is not None:
            out[key] = v
    for key in ("brands", "specs", "brand_excludes", "use_case_tags"):
        vv = applied.get(key)
        if vv is None:
            vv = used.get(key)
        if isinstance(vv, list) and vv:
            out[key] = vv[:12]
    if isinstance(data.get("product_identity"), dict):
        ident = data.get("product_identity") or {}
        if ident.get("constraints"):
            out["image_identity"] = ident.get("constraints")
    return out


def _chat_replay_mark_once(redis, *, replay_key: str, ttl_seconds: int) -> bool:
    ttl = max(1, int(ttl_seconds or 1))
    redis_key = f"chat:replay:{replay_key}"
    try:
        # NX+EX ensures only the first request in the replay window is accepted.
        ok = redis.set(redis_key, "1", ex=ttl, nx=True)
        return bool(ok)
    except Exception:
        now = time.time()
        with _CHAT_REPLAY_LOCK:
            exp = float(_CHAT_REPLAY_LOCAL.get(replay_key) or 0.0)
            if exp > now:
                return False
            _CHAT_REPLAY_LOCAL[replay_key] = now + ttl
            stale = [k for k, v in _CHAT_REPLAY_LOCAL.items() if float(v or 0.0) <= now]
            for k in stale[:128]:
                _CHAT_REPLAY_LOCAL.pop(k, None)
        return True


def _ensure_chat_messages_table(db) -> None:
    dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name or "").lower()
    if "sqlite" in dialect:
        db.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                  id TEXT PRIMARY KEY,
                  uid TEXT NOT NULL,
                  session_id TEXT,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  trace_id TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    else:
        db.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS chat_messages (
                  id TEXT PRIMARY KEY,
                  uid TEXT NOT NULL,
                  session_id TEXT NULL,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  trace_id TEXT NULL,
                  created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
        )
    db.commit()


def _store_chat_message(db, *, uid: str, role: str, content: str, trace_id: str | None, session_id: str | None = None) -> None:
    if not str(content or "").strip():
        return
    _ensure_chat_messages_table(db)
    db.execute(
        sql_text(
            """
            INSERT INTO chat_messages (id, uid, session_id, role, content, trace_id)
            VALUES (:id, :uid, :session_id, :role, :content, :trace_id)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "uid": str(uid or "demo-user"),
            "session_id": str(session_id or "")[:128] or None,
            "role": str(role or "assistant")[:32],
            "content": str(content or "")[:8000],
            "trace_id": str(trace_id or "")[:128] or None,
        },
    )
    db.commit()


def _extract_budget_bounds(query: str) -> Dict[str, int | None]:
    q = str(query or "").lower()
    # Parse explicit budget expressions into a stable structured shape.
    m_between = re.search(r"\bbetween\s*\$?([\d,]+)\s*(?:and|to|-)\s*\$?([\d,]+)\b", q)
    if m_between:
        lo = int(str(m_between.group(1)).replace(",", ""))
        hi = int(str(m_between.group(2)).replace(",", ""))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    m_under = re.search(r"\b(?:under|below|max(?:imum)?|up to)\s*\$?([\d,]+)\b", q)
    if m_under:
        return {"budget_min": None, "budget_max": int(str(m_under.group(1)).replace(",", ""))}
    m_over = re.search(r"\b(?:over|above|min(?:imum)?|at least)\s*\$?([\d,]+)\b", q)
    if m_over:
        return {"budget_min": int(str(m_over.group(1)).replace(",", "")), "budget_max": None}
    return {"budget_min": None, "budget_max": None}


def _classify_turn_intent(query: str) -> str:
    q = str(query or "").strip().lower()
    if not q:
        return "SEARCH"
    if any(
        tok in q
        for tok in (
            "warranty",
            "return",
            "refund",
            "broken",
            "damaged",
            "crack",
            "repair",
            "replacement",
            "blue screen",
            "bsod",
            "stop code",
            "support",
        )
    ):
        return "SUPPORT_CLAIM"
    if (
        " vs " in q
        or "compare" in q
        or "difference" in q
        or "show both" in q
        or "which is better" in q
    ):
        return "COMPARE"
    if (
        q.startswith("why ")
        or " why " in q
        or "explain" in q
        or "reason" in q
        or "if not why" in q
        or "overkill" in q
        or "should i" in q
    ):
        return "EXPLAIN"
    if (
        "under $" in q
        or "between $" in q
        or "budget" in q
        or "price range" in q
        or "widen" in q
        or "increase" in q
        or "decrease" in q
        or "only " in q
        or " with " in q
        or "without " in q
    ):
        return "FILTER"
    return "SEARCH"


def _is_budget_question(item: Dict[str, Any]) -> bool:
    text = str((item or {}).get("text") or "").lower()
    qid = str((item or {}).get("id") or "").lower()
    return any(
        tok in text or tok in qid
        for tok in ("budget", "price range", "price", "widen_budget", "budget_range", "increase_match_space")
    )


def _build_right_panel_contract(
    *,
    products: List[Dict[str, Any]],
    turn_intent: str,
    budget_viability: Dict[str, Any] | None,
    use_case_analysis: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if str(turn_intent or "").upper() == "SUPPORT_CLAIM":
        return {
            "mode": "support",
            "show_tiers": False,
            "summary": "Support mode active: troubleshooting, warranty, and escalation guidance.",
        }

    items: List[Dict[str, Any]] = [p for p in (products or []) if isinstance(p, dict)]
    if not items:
        return {"mode": "shopping", "show_tiers": False}

    prices = []
    for p in items:
        try:
            prices.append(float(p.get("price") or 0.0))
        except Exception:
            continue
    prices = [x for x in prices if x > 0]
    prices.sort()
    median_price = prices[len(prices) // 2] if prices else 0.0

    lower = []
    higher = []
    for p in items:
        try:
            px = float(p.get("price") or 0.0)
        except Exception:
            px = 0.0
        if px <= median_price:
            lower.append(p)
        else:
            higher.append(p)
    lower = lower[:4]
    higher = higher[:4]
    status = str((budget_viability or {}).get("status") or "unknown").lower()
    show_tiers = status in {"low", "high"} or bool(use_case_analysis and len(items) >= 4)
    return {
        "mode": "shopping",
        "show_tiers": bool(show_tiers),
        "budget_status": status,
        "lower_tier": {
            "title": "Budget-fit options",
            "items": lower or items[:4],
            "explanation": "Prioritizes value, battery life, and practical everyday performance.",
        },
        "higher_tier": {
            "title": "Performance-fit options",
            "items": higher or items[:4],
            "explanation": "Prioritizes higher CPU/GPU headroom for heavier workloads.",
        },
    }


def _extract_brand_mentions(query: str) -> List[str]:
    q = str(query or "").lower()
    known = ("apple", "macbook", "dell", "lenovo", "asus", "hp", "acer", "msi", "microsoft", "surface", "samsung")
    out: List[str] = []
    for b in known:
        if b in q:
            mapped = "apple" if b == "macbook" else ("microsoft" if b == "surface" else b)
            if mapped not in out:
                out.append(mapped)
    return out


def _extract_image_cv_signals(image_obj: Dict[str, Any] | None) -> Dict[str, Any]:
    img = image_obj if isinstance(image_obj, dict) else {}
    sec = img.get("security") if isinstance(img.get("security"), dict) else {}
    sec_signals = {}
    if isinstance(sec.get("signals"), dict):
        sec_signals.update(sec.get("signals") or {})
    if isinstance(sec.get("cv_signals"), dict):
        sec_signals.update(sec.get("cv_signals") or {})
    if isinstance(sec, dict):
        for k, v in sec.items():
            if isinstance(v, bool):
                sec_signals[k] = v
    reasons = []
    if isinstance(img.get("reasons"), list):
        reasons.extend(str(x) for x in (img.get("reasons") or []))
    if isinstance(sec.get("reasons"), list):
        reasons.extend(str(x) for x in (sec.get("reasons") or []))
    qr_detected = bool(
        sec_signals.get("qr_code_detected")
        or sec_signals.get("qr_detected")
        or sec_signals.get("qr_url_present")
        or sec_signals.get("qr_url_suspicious")
        or ("qr_code_detected" in reasons)
    )
    qr_external = bool(
        sec_signals.get("qr_external_url_detected")
        or sec_signals.get("qr_external_url")
        or sec_signals.get("qr_url_present")
        or sec_signals.get("qr_url_suspicious")
        or ("qr_external_url_detected" in reasons)
    )
    qr_injection = bool(
        sec_signals.get("qr_prompt_injection")
        or sec_signals.get("prompt_injection_text_suspected")
        or ("qr_prompt_injection" in reasons)
    )
    manipulation = bool(
        sec_signals.get("manipulation_detected")
        or sec_signals.get("adversarial_detected")
        or sec_signals.get("steg_suspicious")
        or sec_signals.get("duplicate_image_detected")
        or ("manipulation_detected" in reasons)
    )
    return {
        "qr_code_detected": qr_detected,
        "qr_prompt_injection": qr_injection,
        "qr_external_url_detected": qr_external,
        "ocr_prompt_injection": bool(sec_signals.get("ocr_prompt_injection")),
        "manipulation_detected": manipulation,
        "adversarial_score": float(sec_signals.get("adversarial_score") or 0.0),
    }


def _decode_image_b64(image_obj: Dict[str, Any] | None) -> bytes:
    img = image_obj if isinstance(image_obj, dict) else {}
    raw = (
        img.get("image_b64")
        or img.get("bytes_b64")
        or img.get("b64")
        or img.get("data_url")
    )
    if not isinstance(raw, str) or not raw.strip():
        return b""
    s = raw.strip()
    if s.startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    try:
        return base64.b64decode(s.encode("utf-8"), validate=False)
    except Exception:
        return b""


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
) -> None:
    mem = Memory(redis)
    prior = mem.get_structured_state(uid) or {}
    budget = _extract_budget_bounds(query)
    brands = _extract_brand_mentions(query)
    skus = [str((p or {}).get("sku") or "") for p in (products or []) if isinstance(p, dict)]
    skus = [s for s in skus if s][:12]

    out = dict(prior)
    out["last_chat_query"] = str(query or "")[:500]
    out["last_chat_trace_id"] = trace_id
    out["last_chat_ts"] = int(time.time())

    merged_slots = out.get("confirmed_slots") if isinstance(out.get("confirmed_slots"), dict) else {}
    merged_slots = dict(merged_slots)
    if budget.get("budget_min") is not None:
        merged_slots["budget_min"] = budget.get("budget_min")
    if budget.get("budget_max") is not None:
        merged_slots["budget_max"] = budget.get("budget_max")
    if brands:
        merged_slots["brands"] = brands[:6]
    if isinstance(confirmed_slots, dict):
        for key, value in confirmed_slots.items():
            if value is None:
                continue
            if isinstance(value, list) and not value:
                continue
            merged_slots[str(key)] = value
    if merged_slots:
        out["confirmed_slots"] = merged_slots
        if merged_slots.get("budget_min") is not None:
            out["budget_min"] = merged_slots.get("budget_min")
        if merged_slots.get("budget_max") is not None:
            out["budget_max"] = merged_slots.get("budget_max")
        if isinstance(merged_slots.get("brands"), list) and merged_slots.get("brands"):
            out["brands"] = list(merged_slots.get("brands"))[:6]

    base_recent = recent_messages if isinstance(recent_messages, list) and recent_messages else out.get("recent_messages")
    recent = _normalize_recent_messages(base_recent, limit=16)
    recent.append({"role": "user", "content": str(query or "")[:500]})
    if str(assistant_message or "").strip():
        recent.append({"role": "assistant", "content": str(assistant_message or "")[:500]})
    out["recent_messages"] = _normalize_recent_messages(recent, limit=16)
    if skus:
        out["last_shortlist_skus"] = skus
        out["last_valid_shortlist_skus"] = skus

    mem.set_structured_state(uid, out)

    bank = mem.get_product_memory_bank(uid) or {}
    hist = list(bank.get("chat_turns") or [])
    hist.append(
        {
            "ts": int(time.time()),
            "trace_id": trace_id,
            "query": str(query or "")[:300],
            "shortlist_skus": skus,
            "budget_min": out.get("budget_min"),
            "budget_max": out.get("budget_max"),
        }
    )
    bank["chat_turns"] = hist[-20:]
    if skus:
        bank["last_shortlist_skus"] = skus
    bank["last_trace_id"] = trace_id
    mem.set_product_memory_bank(uid, bank)


@router.post("/query")
async def chat_query(
    request: Request,
    payload: Dict,
    redis=Depends(get_redis),
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Chat query wrapper that delegates to recommendation endpoint and
    returns a canonical UI-friendly shape.

    Accepts two payload formats:
    Legacy:  { query, uid, image_labels?, image_ocr_text?, image_hash?, image_intent? }
    New:     { query, uid, images?: [{labels, ocr_text, hash, damage_score, confidence}],
               image_intent?, voice_transcript?, voice_confidence?, recent_messages? }
    """
    q = (payload or {}).get("query") or ""

    # -----------------------------------------------------------------------
    # Merge voice transcript into query when present
    # -----------------------------------------------------------------------
    voice_transcript = (payload or {}).get("voice_transcript")
    voice_confidence = (payload or {}).get("voice_confidence")
    if isinstance(voice_transcript, str) and voice_transcript.strip() and not q.strip():
        q = voice_transcript.strip()

    # -----------------------------------------------------------------------
    # Normalize multimodal image payload (new array format → legacy flat)
    # -----------------------------------------------------------------------
    images_array: List[Dict[str, Any]] = (payload or {}).get("images") or []
    image_labels_in = (payload or {}).get("image_labels")
    image_ocr_text_in = (payload or {}).get("image_ocr_text")
    image_hash_in = (payload or {}).get("image_hash")
    image_intent_in = (payload or {}).get("image_intent")
    image_cv_signals_in: Dict[str, Any] = {}
    damage_score_in: float = 0.0
    is_product_photo_in: bool = False
    image_blob_bytes: bytes = b""

    if images_array and isinstance(images_array, list):
        # Merge first image's data into flat fields for backward compat
        first = images_array[0] if images_array else {}
        if isinstance(first, dict):
            if not image_labels_in:
                image_labels_in = first.get("labels")
            if not image_ocr_text_in:
                image_ocr_text_in = first.get("ocr_text")
            if not image_hash_in:
                image_hash_in = first.get("image_hash") or first.get("hash")
            damage_score_in = float(first.get("damage_score") or 0.0)
            is_product_photo_in = bool(first.get("is_product_photo"))
            image_cv_signals_in = _extract_image_cv_signals(first)
            image_blob_bytes = _decode_image_b64(first)
            if not image_hash_in and image_blob_bytes:
                image_hash_in = hashlib.sha256(image_blob_bytes).hexdigest()[:32]
    elif isinstance((payload or {}).get("image_b64"), str):
        image_blob_bytes = _decode_image_b64({"image_b64": (payload or {}).get("image_b64")})
        if not image_hash_in and image_blob_bytes:
            image_hash_in = hashlib.sha256(image_blob_bytes).hexdigest()[:32]

    has_image = bool(image_labels_in or images_array)
    if images_array and isinstance(images_array, list):
        # Merge CV/security signals across all uploaded images so a QR hit on
        # any frame is forwarded to the recommendation/security pipeline.
        merged = dict(image_cv_signals_in or {})
        for img in images_array:
            sig = _extract_image_cv_signals(img if isinstance(img, dict) else {})
            merged["qr_code_detected"] = bool(merged.get("qr_code_detected") or sig.get("qr_code_detected"))
            merged["qr_prompt_injection"] = bool(merged.get("qr_prompt_injection") or sig.get("qr_prompt_injection"))
            merged["qr_external_url_detected"] = bool(
                merged.get("qr_external_url_detected") or sig.get("qr_external_url_detected")
            )
            merged["ocr_prompt_injection"] = bool(merged.get("ocr_prompt_injection") or sig.get("ocr_prompt_injection"))
            merged["manipulation_detected"] = bool(merged.get("manipulation_detected") or sig.get("manipulation_detected"))
            merged["adversarial_score"] = max(
                float(merged.get("adversarial_score") or 0.0),
                float(sig.get("adversarial_score") or 0.0),
            )
        image_cv_signals_in = merged

    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")

    uid = str((payload or {}).get("uid") or "demo-user")
    session_id = str((payload or {}).get("session_id") or "")[:128] or None
    source_ip = request.client.host if request and request.client else ""
    turn_intent = _classify_turn_intent(q)

    # Reload confirmed slots at turn start to keep context continuity explicit.
    try:
        _prior_ss = Memory(redis).get_structured_state(uid) or {}
        _confirmed_in = _prior_ss.get("confirmed_slots") if isinstance(_prior_ss.get("confirmed_slots"), dict) else {}
        if _confirmed_in:
            payload["confirmed_slots"] = _confirmed_in
    except Exception:
        pass

    # Replay protection: reject immediate duplicates from retries/replays.
    try:
        replay_nonce = str(
            (payload or {}).get("nonce")
            or (payload or {}).get("message_id")
            or request.headers.get("x-chat-nonce")
            or request.headers.get("idempotency-key")
            or ""
        ).strip()[:128]
        replay_shape = {
            "nqe_selection": (payload or {}).get("nqe_selection"),
            "image_hash": (payload or {}).get("image_hash"),
            "images": [
                str((x or {}).get("image_hash") or (x or {}).get("hash") or "")[:64]
                for x in ((payload or {}).get("images") or [])[:3]
                if isinstance(x, dict)
            ],
            "has_voice": bool((payload or {}).get("voice_transcript")),
        }
        replay_material = "|".join(
            [
                uid,
                str(session_id or ""),
                str(source_ip or ""),
                str(q or "").strip().lower()[:500],
                replay_nonce
                or hashlib.sha256(
                    json.dumps(replay_shape, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
            ]
        )
        replay_key = hashlib.sha256(replay_material.encode("utf-8")).hexdigest()
        replay_ttl = int(os.getenv("CHAT_REPLAY_TTL_SECONDS", "20") or 20)
        require_nonce = str(os.getenv("CHAT_REPLAY_REQUIRE_NONCE", "0")).strip().lower() in ("1", "true", "yes", "on")
        if require_nonce and not replay_nonce:
            raise HTTPException(status_code=428, detail={"message": "nonce_required"})
        if replay_nonce:
            replay_ttl = max(replay_ttl, 120)
        if not _chat_replay_mark_once(redis, replay_key=replay_key, ttl_seconds=replay_ttl):
            raise HTTPException(
                status_code=409,
                detail={"message": "chat_replay_detected", "retry_after_seconds": replay_ttl},
            )
    except HTTPException:
        raise
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Cross-modal security: scan merged text (user query + voice + OCR + labels + QR)
    # -----------------------------------------------------------------------
    try:
        merged_text_parts = [q]
        if isinstance(voice_transcript, str) and voice_transcript.strip():
            merged_text_parts.append(voice_transcript[:500])
        if isinstance(image_ocr_text_in, str):
            merged_text_parts.append(image_ocr_text_in[:500])
        if isinstance(image_labels_in, list):
            merged_text_parts.append(" ".join(str(x) for x in image_labels_in[:12]))
        elif isinstance(image_labels_in, str):
            merged_text_parts.append(image_labels_in[:200])
        # Extract QR-decoded text from image security results
        for img in (images_array or []):
            if isinstance(img, dict):
                sec = img.get("security") or {}
                if isinstance(sec, dict):
                    qr_texts = sec.get("qr_data") or sec.get("signals", {}).get("qr_data")
                    if isinstance(qr_texts, str) and qr_texts.strip():
                        merged_text_parts.append(qr_texts[:200])
                    elif isinstance(qr_texts, list):
                        merged_text_parts.extend(str(t)[:200] for t in qr_texts[:4])
        merged_text = " ".join(merged_text_parts)

        from src.app.security.observer import analyze_payload
        _sec_payload: Dict[str, Any] = {"query": merged_text, "source": "chat_multimodal"}
        if image_cv_signals_in:
            _sec_payload["cv_signals"] = image_cv_signals_in
        sec_result = analyze_payload(_sec_payload)
        if isinstance(sec_result, dict):
            sev = str(sec_result.get("severity") or "").lower()
            if sev in ("critical", "high"):
                log_trace_event(
                    trace_id=None, event_type="cross_modal_security_block",
                    source_type="agent", source_id="Security_Observer_Agent",
                    target_type="chat", target_id=None,
                    payload={"severity": sev, "signals": sec_result.get("signals")},
                )
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Image intent routing (when images present and intent not pre-resolved)
    # -----------------------------------------------------------------------
    intent_routing_result: Optional[Dict[str, Any]] = None
    if has_image and (not image_intent_in or image_intent_in == "auto"):
        try:
            recent_msgs = (payload or {}).get("recent_messages") or []
            labels_for_router: List[str] = []
            if isinstance(image_labels_in, list):
                labels_for_router = [str(x) for x in image_labels_in[:12]]
            elif isinstance(image_labels_in, str):
                labels_for_router = [s.strip() for s in image_labels_in.split(",")][:12]

            intent_routing_result = classify_image_intent(
                image_labels=labels_for_router,
                image_ocr_text=str(image_ocr_text_in or "")[:500],
                damage_score=damage_score_in,
                is_product_photo=is_product_photo_in,
                user_query=q,
                recent_messages=recent_msgs if isinstance(recent_msgs, list) else [],
            )
            image_intent_in = intent_routing_result.get("intent") or "disambiguate"
        except Exception:
            image_intent_in = "disambiguate"

    # If intent is disambiguate, return disambiguation response without calling recommend
    if image_intent_in == "disambiguate" and has_image:
        out = {
            "products": [],
            "view_mode": "cards",
            "confidence": None,
            "decision_trace_id": None,
            "assistant_message": (
                "I see the photo! What would you like to do?\n\n"
                "\u2022 Type **\"find similar\"** to search for products like this\n"
                "\u2022 Type **\"report issue\"** to start a return or complaint\n"
                "\u2022 Or describe what you need and I'll figure it out"
            ),
            "disambiguation": True,
            "needs_disambiguation": True,
            "intent_routing": intent_routing_result,
            "next_questions": [
                {"id": "visual_search", "text": "Find similar products", "goal": "visual_search"},
                {"id": "cv_triage", "text": "Report an issue / return", "goal": "cv_triage"},
                {"id": "describe", "text": "Let me describe what I need", "goal": "freeform"},
            ],
            "llm_model": None,
            "model_tier": None,
            "complexity": score_query_complexity(q, context={"has_image": True}),
        }
        try:
            _store_chat_message(db, uid=uid, role="user", content=q, trace_id=None)
            _store_chat_message(db, uid=uid, role="assistant", content=str(out.get("assistant_message") or ""), trace_id=None)
            _persist_chat_structured_state(
                redis=redis,
                uid=uid,
                query=q,
                products=[],
                trace_id=None,
                assistant_message=str(out.get("assistant_message") or ""),
                recent_messages=(payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else None,
                confirmed_slots=_extract_confirmed_slots(query=q, response=None),
            )
        except Exception:
            pass
        return out

    # -----------------------------------------------------------------------
    # Complexity scoring for trace enrichment
    # -----------------------------------------------------------------------
    complexity_result = score_query_complexity(q, context={
        "has_image": has_image,
        "conversation_turn": int((payload or {}).get("conversation_turn") or 0),
    })
    try:
        uid_for_cache = str((payload or {}).get("uid") or "demo-user")
        if uid_for_cache and isinstance(image_hash_in, str) and image_hash_in.strip() and image_blob_bytes:
            mem = Memory(redis)
            _stash_image_blob_for_recommend(mem, uid_for_cache, image_hash_in.strip()[:128], image_blob_bytes)
    except Exception:
        pass

    policy_ok, policy_reason = enforce_model_theft_policy_gate(
        query=q,
        uid=uid,
        source_ip=(request.client.host if request and request.client else None),
        api_key_id=(request.headers.get("x-api-key") if request else None),
    )
    if not policy_ok:
        raise HTTPException(status_code=429, detail={"message": "model_theft_policy_gate", "reason": policy_reason})
    allowed_model_use, model_use_reason = enforce_model_theft_rate_limit(
        redis_client=redis,
        uid=uid,
        source_ip=(request.client.host if request and request.client else None),
        api_key_id=(request.headers.get("x-api-key") if request else None),
        query=q,
    )
    if not allowed_model_use:
        raise HTTPException(status_code=429, detail={"message": "model_theft_guard", "reason": model_use_reason})

    # -----------------------------------------------------------------------
    # Persist recent conversation messages so the recommend pipeline can
    # reference them for context continuity (avoids "context rot").
    # -----------------------------------------------------------------------
    try:
        _uid_msg = uid
        _recent_msgs_raw = (payload or {}).get("recent_messages") or []
        if isinstance(_recent_msgs_raw, list) and _recent_msgs_raw:
            _mem_state = Memory(redis)
            _ss = _mem_state.get_structured_state(_uid_msg) or {}
            _ss["recent_messages"] = _normalize_recent_messages(_recent_msgs_raw, limit=12)
            _mem_state.set_structured_state(_uid_msg, _ss)
    except Exception:
        pass

    # Call internal recommend endpoint to leverage agentic pipeline
    base = str(request.base_url).rstrip("/")
    url = f"{base}/api/v1/recommend/suggest"
    params = {"uid": uid, "query": q}
    nqe_selection = (payload or {}).get("nqe_selection") or {}
    if isinstance(nqe_selection, dict):
        qid = str(nqe_selection.get("question_id") or "").strip()
        oid = str(nqe_selection.get("option_id") or "").strip()
        olbl = str(nqe_selection.get("option_label") or "").strip()
        oval = str(nqe_selection.get("option_value") or "").strip()
        if qid and oid:
            params["nqe_question_id"] = qid
            params["nqe_option_id"] = oid
            if olbl:
                params["nqe_option_label"] = olbl[:120]
            if oval:
                params["nqe_option_value"] = oval[:120]
    try:
        labels_list: List[str] = []
        if isinstance(image_labels_in, list):
            labels_list = [str(x).strip() for x in image_labels_in if str(x).strip()]
        elif isinstance(image_labels_in, str):
            labels_list = [s.strip() for s in image_labels_in.split(",") if s.strip()]
        if labels_list:
            params["image_labels"] = ",".join(labels_list[:12])
        if isinstance(image_ocr_text_in, str) and image_ocr_text_in.strip():
            params["image_ocr_text"] = image_ocr_text_in.strip()[:500]
        if isinstance(image_hash_in, str) and image_hash_in.strip():
            params["image_hash"] = image_hash_in.strip()[:128]
        if isinstance(image_intent_in, str) and image_intent_in.strip():
            params["image_intent"] = image_intent_in.strip()[:32]
        if image_cv_signals_in:
            params["image_cv_signals"] = json.dumps(image_cv_signals_in, separators=(",", ":"))[:1000]
    except Exception:
        pass
    try:
        headers = {}
        try:
            # Forward caller auth to internal request; fallback to local key for dev
            fwd_key = (request.headers.get("x-api-key") if request and hasattr(request, "headers") else None) or "local-merchant-key"
            headers["x-api-key"] = fwd_key
        except Exception:
            headers["x-api-key"] = "local-merchant-key"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, params=params, headers=headers)
            data = {}
            try:
                data = r.json()
            except Exception:
                data = {}
            if r.status_code == 403 and isinstance(data, dict):
                # Safety/policy blocks are a normal outcome; surface them as a friendly chat response.
                blocked = data.get("detail") if isinstance(data.get("detail"), dict) else data
                decision_trace_id = (
                    blocked.get("trace_id")
                    or blocked.get("decision_trace_id")
                    or blocked.get("decision_id")
                    or blocked.get("approval_id")
                )
                msg = blocked.get("message") or "This request was blocked due to safety checks. A human will review it."
                followups = [
                    {"id": "remove_sensitive", "text": "Can you rephrase without any personal info, order numbers, or long digit strings?", "goal": "safety_rephrase"},
                    {"id": "use_budget_words", "text": "If you meant a price range, try: 'budget between $900 and $1300'.", "goal": "clarify_details"},
                ]
                out = {
                    "products": [],
                    "view_mode": "cards",
                    "confidence": None,
                    "decision_trace_id": decision_trace_id,
                    "trace_id": decision_trace_id,
                    "assistant_message": msg,
                    "next_questions": followups,
                    "llm_model": blocked.get("llm_model"),
                    "model_tier": blocked.get("model_tier") or blocked.get("tier"),
                    "blocked": True,
                    "blocked_detail": blocked,
                }
                try:
                    uid = str((payload or {}).get("uid") or "demo-user")
                    _store_chat_message(db, uid=uid, role="user", content=q, trace_id=decision_trace_id)
                    _store_chat_message(
                        db,
                        uid=uid,
                        role="assistant",
                        content=str(out.get("assistant_message") or ""),
                        trace_id=decision_trace_id,
                    )
                    _persist_chat_structured_state(
                        redis=redis,
                        uid=uid,
                        query=q,
                        products=[],
                        trace_id=decision_trace_id,
                    )
                except Exception:
                    pass
                return out
            r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"recommend_unavailable: {e}")

    # Map results into canonical product shape
    results = data.get("results") or []
    products: List[Dict] = []
    for item in results:
        price = item.get("price")
        if price is None:
            try:
                price_cents = item.get("price_cents")
                if price_cents is not None:
                    price = float(price_cents) / 100.0
            except Exception:
                price = None
        specs = item.get("specs") or {}
        features: List[str] = []
        try:
            if isinstance(specs, dict):
                cpu = specs.get("cpu")
                if cpu:
                    features.append(str(cpu))
                ram = specs.get("ram_gb")
                if ram:
                    features.append(f"{ram}GB RAM")
                storage = specs.get("storage")
                if storage:
                    features.append(str(storage))
                display = specs.get("display")
                if display:
                    features.append(str(display))
                wifi = specs.get("wifi")
                if wifi:
                    features.append(str(wifi))
        except Exception:
            features = []
        # Deterministic "why" badges for UI: prefer positive factors from recommend.
        why: List[str] = []
        try:
            fac = item.get("factors") or {}
            if isinstance(fac, dict):
                pos = fac.get("positive") or []
                if isinstance(pos, list):
                    why = [str(x) for x in pos if isinstance(x, (str, int, float))][:4]
        except Exception:
            why = []
        products.append({
            "sku": item.get("sku"),
            "name": item.get("name"),
            "price": price,
            "features": features or (item.get("features") or []),
            "image_url": item.get("image_url"),
            "why": why,
            "score_norm": item.get("score_norm"),
        })

    # Auto view mode heuristic (simple client-like logic)
    ql = q.lower()
    compare_keywords = ("compare", "vs", "difference", "better", "which")
    if any(k in ql for k in compare_keywords):
        view_mode = "compare" if len(products) <= 5 else "grid"
    elif len(products) > 5:
        view_mode = "grid"
    else:
        view_mode = "cards"

    decision_trace_id = data.get("decision_trace_id") or data.get("decision_id") or data.get("trace_id")
    assistant_message = data.get("assistant_message") or data.get("message")

    # Emit new trace events for the Multimodal / Complexity / Memory tabs
    try:
        if complexity_result:
            log_trace_event(
                trace_id=decision_trace_id, event_type="tier_complexity_score",
                source_type="agent", source_id="Complexity_Scorer",
                target_type="chat", target_id=None,
                payload={
                    "score": complexity_result.get("score"),
                    "tier": complexity_result.get("tier"),
                    "model": complexity_result.get("model"),
                    "signals": complexity_result.get("signals", {}),
                    "explanations": complexity_result.get("explanations", []),
                },
            )
        if intent_routing_result:
            log_trace_event(
                trace_id=decision_trace_id, event_type="image_intent_routing",
                source_type="agent", source_id="ImageIntentRouter",
                target_type="chat", target_id=None,
                payload={
                    "intent": intent_routing_result.get("intent"),
                    "confidence": intent_routing_result.get("confidence"),
                    "reason": intent_routing_result.get("reason"),
                    "signals": intent_routing_result.get("signals", {}),
                    "scores": intent_routing_result.get("scores", {}),
                },
            )
        if has_image:
            log_trace_event(
                trace_id=decision_trace_id, event_type="multimodal_fusion",
                source_type="agent", source_id="Chat_Multimodal",
                target_type="chat", target_id=None,
                payload={
                    "image_count": len(images_array) if images_array else (1 if has_image else 0),
                    "voice_used": bool(voice_transcript),
                    "labels": (image_labels_in[:12] if isinstance(image_labels_in, list) else []),
                    "ocr_text": str(image_ocr_text_in or "")[:200],
                },
            )
            log_trace_event(
                trace_id=decision_trace_id, event_type="image_security_scan",
                source_type="agent", source_id="Image_Security_Sidecar",
                target_type="chat", target_id=None,
                payload={
                    "qr_detected": bool(image_cv_signals_in.get("qr_code_detected")),
                    "qr_prompt_injection": bool(image_cv_signals_in.get("qr_prompt_injection")),
                    "qr_external_url_detected": bool(image_cv_signals_in.get("qr_external_url_detected")),
                    "adversarial_score": float(image_cv_signals_in.get("adversarial_score") or 0.0),
                    "reupload_needed": bool(
                        image_cv_signals_in.get("qr_code_detected")
                        or image_cv_signals_in.get("qr_prompt_injection")
                        or image_cv_signals_in.get("qr_external_url_detected")
                        or image_cv_signals_in.get("manipulation_detected")
                    ),
                },
            )
            if image_cv_signals_in:
                sec_signals = {
                    "qr_code_detected": bool(image_cv_signals_in.get("qr_code_detected")),
                    "qr_prompt_injection": bool(image_cv_signals_in.get("qr_prompt_injection")),
                    "qr_external_url_detected": bool(image_cv_signals_in.get("qr_external_url_detected")),
                    "ocr_prompt_injection": bool(image_cv_signals_in.get("ocr_prompt_injection")),
                    "manipulation_detected": bool(image_cv_signals_in.get("manipulation_detected")),
                    "damage_detected": bool(image_cv_signals_in.get("damage_detected")),
                }
                sec_sev = "info"
                if sec_signals["qr_prompt_injection"] or sec_signals["qr_external_url_detected"]:
                    sec_sev = "high"
                elif sec_signals["qr_code_detected"] or sec_signals["ocr_prompt_injection"] or sec_signals["manipulation_detected"]:
                    sec_sev = "warn"
                log_trace_event(
                    trace_id=decision_trace_id,
                    event_type="security_scan",
                    source_type="agent",
                    source_id="Security_Observer_Agent",
                    target_type="chat",
                    target_id=None,
                    payload={
                        "severity": sec_sev,
                        "route": "review" if sec_sev in ("high", "warn") else "allow",
                        "details": {"signals": sec_signals},
                        "signals": sec_signals,
                        "summary": "Image-sidecar security signal normalization",
                    },
                )
    except Exception:
        pass
    next_questions = data.get("next_questions") or []
    if turn_intent in ("EXPLAIN", "SUPPORT_CLAIM"):
        next_questions = [x for x in next_questions if isinstance(x, dict) and not _is_budget_question(x)]
    if not next_questions and not products and turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM"):
        # Fallback follow-ups when no candidates are found but backend did not emit NQE prompts.
        next_questions = [
            {"id": "widen_budget", "text": "Can we widen your budget range by $200-$400?", "goal": "increase_match_space"},
            {"id": "relax_brand", "text": "Are you open to brands beyond Apple/Windows-first picks?", "goal": "increase_match_space"},
            {"id": "priority_tradeoff", "text": "Prioritize gaming FPS or rendering/export speed first?", "goal": "resolve_tradeoff"},
        ]
    if not assistant_message and not products and next_questions:
        prompts = [f"- {q.get('text')}" for q in next_questions if isinstance(q, dict) and q.get("text")]
        assistant_message = "I could not find a confident in-catalog match yet. Try one of these refinements:\n" + "\n".join(prompts)
    confidence = None
    try:
        # Use top normalized score as confidence proxy if present
        if results and isinstance(results[0].get("score_norm"), (int, float)):
            confidence = float(results[0]["score_norm"]) / 100.0
    except Exception:
        confidence = None

    # Persist search event for chat route (UI-friendly shape)
    try:
        log_search_event(
            uid=str(payload.get("uid") or "demo-user"),
            query=q,
            filters=None,
            result_skus=[p.get("sku") for p in products],
            view_mode=view_mode,
            trace_id=decision_trace_id,
            session_id=None,
        )
    except Exception:
        pass

    budget_viability = data.get("budget_viability") if isinstance(data.get("budget_viability"), dict) else {"status": "unknown"}
    use_case_analysis = data.get("use_case_analysis") if isinstance(data.get("use_case_analysis"), dict) else None
    panel_intent = "SUPPORT_CLAIM" if bool(image_cv_signals_in.get("damage_detected")) else turn_intent
    _backend_right_panel = data.get("right_panel") if isinstance(data.get("right_panel"), dict) else None
    out = {
        "products": products,
        "view_mode": view_mode,
        "confidence": confidence,
        "decision_trace_id": decision_trace_id,
        "trace_id": decision_trace_id,
        "assistant_message": assistant_message,
        "next_questions": next_questions,
        "needs_disambiguation": bool(data.get("needs_disambiguation") or (not products and next_questions)),
        "nqe_selection_applied": data.get("nqe_selection_applied") or {},
        "llm_model": data.get("llm_model"),
        "model_tier": data.get("model_tier"),
        "complexity": complexity_result,
        "intent_routing": intent_routing_result,
        "turn_intent": turn_intent,
        "voice_used": bool(voice_transcript),
        "budget_viability": budget_viability,
        "use_case_analysis": use_case_analysis,
        "buyer_persona": data.get("buyer_persona"),
        "right_panel": _backend_right_panel or _build_right_panel_contract(
            products=products,
            turn_intent=panel_intent,
            budget_viability=budget_viability,
            use_case_analysis=use_case_analysis,
        ),
    }
    try:
        _store_chat_message(db, uid=uid, role="user", content=q, trace_id=decision_trace_id, session_id=session_id)
        _store_chat_message(
            db,
            uid=uid,
            role="assistant",
            content=str(out.get("assistant_message") or ""),
            trace_id=decision_trace_id,
            session_id=session_id,
        )
        _persist_chat_structured_state(
            redis=redis,
            uid=uid,
            query=q,
            products=products,
            trace_id=decision_trace_id,
            assistant_message=str(out.get("assistant_message") or ""),
            recent_messages=(payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else None,
            confirmed_slots=_extract_confirmed_slots(query=q, response=data if isinstance(data, dict) else None),
        )
    except Exception:
        pass
    return out


@router.get("/history")
def chat_history(
    request: Request,
    uid: str,
    limit: int = Query(50, ge=1, le=500),
    before: Optional[str] = None,
    db=Depends(get_db),
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    _ = role
    _ensure_chat_messages_table(db)
    params: Dict[str, Any] = {"uid": uid, "lim": int(limit)}
    where = "WHERE uid = :uid"
    if before:
        where += " AND created_at < :before"
        params["before"] = str(before)
    rows = db.execute(
        sql_text(
            f"""
            SELECT id, uid, session_id, role, content, trace_id, created_at
            FROM chat_messages
            {where}
            ORDER BY created_at DESC
            LIMIT :lim
            """
        ),
        params,
    ).mappings().all()
    items = [dict(r) for r in rows]
    items.reverse()
    return {"uid": uid, "count": len(items), "items": items}


@router.post("/ollama_test")
async def ollama_test(
    payload: Dict,
    role: str = Depends(require_role([ROLE_MERCHANT, ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict:
    """Route queries to small vs big Ollama models based on complexity and return a short summary.

    Input: { query: string }
    Output: { model: string, complex: bool, total_duration_ms: number, response: string }
    """
    q = (payload or {}).get("query") or ""
    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")
    model = select_ollama_model(q)
    try:
        result = await ollama_generate(model, f"Summarize the user's intent in one sentence and list top 2 attributes to consider.\nUser Query: {q}")
        return {
            "model": model,
            "complex": is_complex_query(q),
            "total_duration_ms": result.get("total_duration_ms"),
            "response": result.get("response"),
        }
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"ollama_unavailable: {e}")
