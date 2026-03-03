from __future__ import annotations

import json
import re
import time
import uuid
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


def _persist_chat_structured_state(
    *,
    redis,
    uid: str,
    query: str,
    products: List[Dict[str, Any]] | None,
    trace_id: str | None,
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
    if budget.get("budget_min") is not None:
        out["budget_min"] = budget.get("budget_min")
    if budget.get("budget_max") is not None:
        out["budget_max"] = budget.get("budget_max")
    if brands:
        out["brands"] = brands[:6]
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
            uid = str((payload or {}).get("uid") or "demo-user")
            _store_chat_message(db, uid=uid, role="user", content=q, trace_id=None)
            _store_chat_message(db, uid=uid, role="assistant", content=str(out.get("assistant_message") or ""), trace_id=None)
            _persist_chat_structured_state(redis=redis, uid=uid, query=q, products=[], trace_id=None)
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

    policy_ok, policy_reason = enforce_model_theft_policy_gate(
        query=q,
        uid=str((payload or {}).get("uid") or ""),
        source_ip=(request.client.host if request and request.client else None),
        api_key_id=(request.headers.get("x-api-key") if request else None),
    )
    if not policy_ok:
        raise HTTPException(status_code=429, detail={"message": "model_theft_policy_gate", "reason": policy_reason})
    allowed_model_use, model_use_reason = enforce_model_theft_rate_limit(
        redis_client=redis,
        uid=str((payload or {}).get("uid") or ""),
        source_ip=(request.client.host if request and request.client else None),
        api_key_id=(request.headers.get("x-api-key") if request else None),
        query=q,
    )
    if not allowed_model_use:
        raise HTTPException(status_code=429, detail={"message": "model_theft_guard", "reason": model_use_reason})

    # Call internal recommend endpoint to leverage agentic pipeline
    base = str(request.base_url).rstrip("/")
    url = f"{base}/api/v1/recommend/suggest"
    params = {"uid": (payload.get("uid") or "demo-user"), "query": q}
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
    except Exception:
        pass
    next_questions = data.get("next_questions") or []
    if not next_questions and not products:
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
        "voice_used": bool(voice_transcript),
    }
    try:
        uid = str((payload or {}).get("uid") or "demo-user")
        session_id = str((payload or {}).get("session_id") or "")[:128] or None
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
