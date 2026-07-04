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
from urllib.parse import urlparse

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
from src.app.services.copywriting import maybe_apply_copywriting
from src.app.services.answer_quality import apply_answer_quality
from src.app.services.response_normalizer import ResponseNormalizer
from src.app.services.price_conversion import cents_to_dollars, dollars_to_cents
from src.app.security.dread_scorer import compute_dread
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.security.qr_legitimacy import derive_qr_legitimacy_details

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_CHAT_REPLAY_LOCAL: Dict[str, float] = {}
_CHAT_REPLAY_LOCK = RLock()


def _resolve_uid(payload: Dict[str, Any] | None, request: Request | None = None) -> str:
    raw = str((payload or {}).get("uid") or "").strip()
    if raw and raw.lower() != "demo-user":
        return raw[:128]
    session_id = str((payload or {}).get("session_id") or "").strip()
    if session_id:
        return f"anon:{session_id[:96]}"
    if request and request.client and request.client.host:
        safe_host = re.sub(r"[^a-zA-Z0-9:._-]", "", str(request.client.host))
        if safe_host:
            return f"anon:{safe_host[:96]}"
    return f"anon:{uuid.uuid4().hex[:16]}"


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
            "uid": str(uid or "anonymous")[:128],
            "session_id": str(session_id or "")[:128] or None,
            "role": str(role or "assistant")[:32],
            "content": str(content or "")[:8000],
            "trace_id": str(trace_id or "")[:128] or None,
        },
    )
    db.commit()


def _extract_budget_bounds(query: str) -> Dict[str, int | None]:
    """Parse a budget from natural phrasings into {budget_min, budget_max}. Handles ranges (between/from/
    bare 'X to Y'/'$X-$Y'), ceilings (under/below/up to), floors (over/at least), PER-UNIT budgets
    ('$1900 each', 'per laptop'), and fuzzy amounts ('budget about 1900', 'spend ~$2000', a lone '$1900').
    Amounts require 3+ digits so quantities like '15 laptops' are never read as a price."""
    q = str(query or "").lower()

    def _n(s: str) -> int:
        return int(str(s).replace(",", ""))

    # 1) explicit range — between/from X to/and/- Y, "$X-$Y", or a bare "X to Y" (both 3-5 digit)
    m = (re.search(r"\b(?:between|from)\s*\$?([\d,]{3,7})\s*(?:and|to|\-|–)\s*\$?([\d,]{3,7})", q)
         or re.search(r"\$\s*([\d,]{3,6})\s*(?:to|\-|–)\s*\$?\s*([\d,]{3,6})", q)
         or re.search(r"\b(\d{3,5})\s*(?:to|\-|–)\s*(\d{3,5})\b", q))
    if m:
        lo, hi = _n(m.group(1)), _n(m.group(2))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    # 2) ceiling
    m = re.search(r"\b(?:under|below|max(?:imum)?|up to|no more than|less than)\s*\$?([\d,]{3,7})\b", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 3) floor
    m = re.search(r"\b(?:over|above|min(?:imum)?|at least|more than)\s*\$?([\d,]{3,7})\b", q)
    if m:
        return {"budget_min": _n(m.group(1)), "budget_max": None}
    # 4) per-unit ceiling — "1900 each", "$1,800 per laptop/unit/device/seat/pc/person"
    m = re.search(r"\$?([\d,]{3,7})\s*(?:each\b|a ?piece\b|apiece\b|per\s+(?:unit|laptop|device|machine|seat|pc|person|user))", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 5) budget/spend/afford amount (optionally fuzzy) — "budget is about 1900", "can spend 2000"
    m = re.search(r"(?:budget|spend|afford\w*)\b[^\d$]{0,18}\$?([\d,]{3,7})", q)
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    # 6) fuzzy/lone money amount — "about $1900", "around 2000", or a lone "$1900" not part of a range
    m = (re.search(r"(?:about|around|approx\w*|roughly|~)\s*\$?\s*([\d,]{3,7})", q)
         or re.search(r"\$\s*([\d,]{3,6})\b(?!\s*(?:to|\-|–))", q))
    if m:
        return {"budget_min": None, "budget_max": _n(m.group(1))}
    return {"budget_min": None, "budget_max": None}


def _is_budget_query_text(query: str | None) -> bool:
    q = str(query or "").strip().lower()
    if not q:
        return False
    if any(
        tok in q
        for tok in (
            "budget",
            "under",
            "below",
            "up to",
            "between",
            "only have",
            "is that enough",
            "is this enough",
            "for high school",
            "for school",
            "for university",
            "for work",
            "for gaming",
        )
    ):
        return True
    bounds = _extract_budget_bounds(q)
    return bounds.get("budget_min") is not None or bounds.get("budget_max") is not None or bool(
        re.search(r"\$\s*\d{3,5}\b", q)
    )


def _classify_turn_intent(query: str) -> str:
    q = str(query or "").strip().lower()
    if not q:
        return "SEARCH"
    # CLAIM-CHECKED support detection (shared predicate with recommend.py's classifier): only a genuine
    # post-purchase claim routes to the support lane. The old bare keyword list here hijacked pre-sales
    # policy questions ("what is your warranty policy?") into photo-triage with zero products.
    from src.app.services.answer_quality import is_support_claim
    if is_support_claim(q):
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


def _budget_range_from_slots(slots: Dict[str, Any] | None, query: str) -> Dict[str, int | None]:
    out = _extract_budget_bounds(query)
    s = slots if isinstance(slots, dict) else {}
    if out.get("budget_min") is None and s.get("budget_min") is not None:
        try:
            out["budget_min"] = int(float(s.get("budget_min")))
        except Exception:
            pass
    if out.get("budget_max") is None and s.get("budget_max") is not None:
        try:
            out["budget_max"] = int(float(s.get("budget_max")))
        except Exception:
            pass
    return out


def _compute_widened_budget(bounds: Dict[str, int | None], widen_delta: int) -> Dict[str, int]:
    bmin = bounds.get("budget_min")
    bmax = bounds.get("budget_max")
    delta = max(100, int(widen_delta or 200))
    if bmax is not None and bmin is not None:
        lo = int(bmax)
        hi = int(bmax + delta)
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    if bmax is not None:
        lo = int(bmax)
        hi = int(bmax + delta)
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    if bmin is not None:
        lo = int(bmin + delta)
        hi = int(bmin + (delta * 2))
        return {"budget_min": min(lo, hi), "budget_max": max(lo, hi)}
    # No prior budget: deterministic bootstrap window.
    return {"budget_min": 800, "budget_max": 1200}


def _brand_hint_from_text(text: str) -> str | None:
    t = str(text or "").lower()
    aliases = [
        ("apple", ("apple", "macbook", "mac")),
        ("lenovo", ("lenovo", "legion", "thinkpad", "yoga")),
        ("dell", ("dell", "xps", "inspiron", "latitude", "alienware")),
        ("hp", ("hp", "pavilion", "omen", "spectre", "envy", "elitebook")),
        ("asus", ("asus", "rog", "zenbook", "vivobook", "tuf")),
        ("msi", ("msi", "katana", "stealth", "raider")),
        ("acer", ("acer", "nitro", "predator", "swift")),
        ("microsoft", ("microsoft", "surface")),
    ]
    for canonical, toks in aliases:
        if any(tok in t for tok in toks):
            return canonical
    return None


def _image_anchor_hint(image_obj: Dict[str, Any], idx: int) -> Dict[str, Any]:
    labels = image_obj.get("labels") if isinstance(image_obj.get("labels"), list) else []
    ocr_text = str(image_obj.get("ocr_text") or "")
    joined = " ".join([str(x) for x in labels[:20]]) + " " + ocr_text
    brand = _brand_hint_from_text(joined)
    low = joined.lower()
    use_case_hint = "general"
    if any(tok in low for tok in ("esports", "gaming", "rtx", "geforce", "fps", "legion", "rog", "tuf")):
        use_case_hint = "gaming"
    elif any(tok in low for tok in ("office", "business", "work", "excel", "powerpoint")):
        use_case_hint = "office"
    elif any(tok in low for tok in ("creator", "premiere", "davinci", "render", "editing")):
        use_case_hint = "content_creator"
    elif any(tok in low for tok in ("student", "school", "college", "university", "study")):
        use_case_hint = "student"
    return {
        "anchor_id": str(image_obj.get("image_hash") or f"img_{idx+1}"),
        "title": f"Image {idx+1}",
        "brand_hint": brand,
        "use_case_hint": use_case_hint,
        "ocr_excerpt": ocr_text[:120] if ocr_text else "",
        "image_hash": str(image_obj.get("image_hash") or ""),
    }


def _persona_rank_weights(use_case_key: str | None, buyer_persona: str | None) -> Dict[str, float]:
    key = str(use_case_key or buyer_persona or "").lower()
    # Keep this deterministic and lightweight: no model call, just profile weights.
    if key in {"gaming", "gamer"}:
        return {"budget_fit": 0.30, "brand_match": 0.10, "performance": 0.50, "portability": 0.10}
    if key in {"ai_ml_workstation", "data_science_student", "engineering_student", "ai", "data_science"}:
        return {"budget_fit": 0.25, "brand_match": 0.10, "performance": 0.55, "portability": 0.10}
    if key in {"office_general", "office", "business", "corporate"}:
        return {"budget_fit": 0.35, "brand_match": 0.10, "performance": 0.20, "portability": 0.35}
    if key in {"content_creator", "content_creation", "creator", "design_student"}:
        return {"budget_fit": 0.25, "brand_match": 0.10, "performance": 0.45, "portability": 0.20}
    # students/high-school/general defaults
    return {"budget_fit": 0.45, "brand_match": 0.15, "performance": 0.20, "portability": 0.20}


def _performance_signal(product: Dict[str, Any]) -> float:
    text = (
        str(product.get("name") or "")
        + " "
        + " ".join([str(x) for x in (product.get("features") or [])])
    ).lower()
    score = 0.0
    if any(t in text for t in ("rtx", "geforce", "radeon", "gpu", "vram")):
        score += 1.0
    if any(t in text for t in ("i7", "i9", "ryzen 7", "ryzen 9", "ultra 7", "ultra 9")):
        score += 0.6
    if any(t in text for t in ("32gb", "24gb", "16gb ram")):
        score += 0.5
    return min(score, 2.0) / 2.0


def _portability_signal(product: Dict[str, Any]) -> float:
    text = (
        str(product.get("name") or "")
        + " "
        + " ".join([str(x) for x in (product.get("features") or [])])
    ).lower()
    score = 0.0
    if any(t in text for t in ('13"', '14"', "13.", "14.", "thin", "light")):
        score += 0.7
    if "macbook air" in text:
        score += 0.5
    return min(score, 1.0)


def _budget_fit_signal(price: float, budget: Dict[str, int | None]) -> float:
    bmin = budget.get("budget_min")
    bmax = budget.get("budget_max")
    if price <= 0:
        return 0.0
    if bmin is not None and bmax is not None and bmin <= price <= bmax:
        return 1.0
    if bmax is not None and price <= bmax:
        return 0.8
    if bmax is not None and price > bmax:
        over = max(1.0, float(price - bmax))
        return max(0.0, 1.0 - (over / max(float(bmax), 1.0)))
    if bmin is not None and price >= bmin:
        return 0.8
    return 0.5


def _score_anchor_candidate(
    product: Dict[str, Any],
    *,
    anchor: Dict[str, Any],
    budget: Dict[str, int | None],
    weights: Dict[str, float],
) -> float:
    try:
        price = float(product.get("price") or 0.0)
    except Exception:
        price = 0.0
    name = str(product.get("name") or "").lower()
    brand = str(anchor.get("brand_hint") or "").lower()
    brand_match = 1.0 if (brand and brand in name) else 0.0
    budget_fit = _budget_fit_signal(price, budget)
    perf = _performance_signal(product)
    portable = _portability_signal(product)
    return (
        (weights.get("budget_fit", 0.0) * budget_fit)
        + (weights.get("brand_match", 0.0) * brand_match)
        + (weights.get("performance", 0.0) * perf)
        + (weights.get("portability", 0.0) * portable)
    )


def _build_anchor_sections(
    *,
    images: List[Dict[str, Any]] | None,
    products: List[Dict[str, Any]],
    query: str,
    budget: Dict[str, int | None],
    use_case_key: str | None,
    buyer_persona: str | None,
) -> List[Dict[str, Any]]:
    imgs = [x for x in (images or []) if isinstance(x, dict)]
    if not imgs:
        return []
    sections: List[Dict[str, Any]] = []
    weights = _persona_rank_weights(use_case_key, buyer_persona)
    for idx, img in enumerate(imgs):
        # Off-domain image (e.g. produce) → do NOT fabricate a "Best 3 matches for this image" product
        # group; the separate off-domain banner explains it. Agnostic relevance check (profile tokens).
        try:
            from src.app.services.cv_triage_basic import classify_image_relevance
            _labels = img.get("labels") if isinstance(img.get("labels"), list) else []
            _cr = img.get("catalog_relevance") if isinstance(img.get("catalog_relevance"), dict) else {}
            # skip the "matches for this image" group when EITHER the relevance classifier says off_topic OR
            # an explicit off-domain flag is set (the classifier needs good CV labels; the flag is the backstop
            # so a mislabelled off-domain image can't still claim "Best 3 matches for this image" — screenshot 007).
            _off = (classify_image_relevance(_labels, str(img.get("ocr_text") or "")) == "off_topic"
                    or bool(img.get("off_domain")) or bool(_cr.get("off_domain"))
                    or str(img.get("image_relevance") or "").strip().lower() == "off_topic")
            if _off:
                continue
        except Exception:
            pass
        anchor = _image_anchor_hint(img, idx)
        scored: List[tuple[float, Dict[str, Any]]] = []
        for p in products:
            if not isinstance(p, dict):
                continue
            scored.append((_score_anchor_candidate(p, anchor=anchor, budget=budget, weights=weights), p))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [row[1] for row in scored[:3]]
        brand_hint = str(anchor.get("brand_hint") or "").lower()
        if brand_hint:
            def _is_apple_row(row: Dict[str, Any]) -> bool:
                txt = f"{str(row.get('name') or '')} {str(row.get('sku') or '')}".lower()
                return ("apple" in txt) or ("macbook" in txt) or txt.startswith("mb")

            if brand_hint == "apple":
                apple_rows = [row[1] for row in scored if _is_apple_row(row[1])]
                if apple_rows:
                    top = apple_rows[:3]
            elif brand_hint in {"lenovo", "dell", "hp", "asus", "acer", "msi", "microsoft", "samsung"}:
                windows_rows = [row[1] for row in scored if not _is_apple_row(row[1])]
                if windows_rows:
                    top = windows_rows[:3]
        if not top:
            continue
        bmin = budget.get("budget_min")
        bmax = budget.get("budget_max")
        budget_phrase = (
            f"${bmin:,}-${bmax:,}" if bmin is not None and bmax is not None
            else (f"under ${bmax:,}" if bmax is not None else (f"over ${bmin:,}" if bmin is not None else "your budget"))
        )
        uc = str(use_case_key or buyer_persona or anchor.get("use_case_hint") or "general").replace("_", " ")
        summary = (
            f"Closest catalog picks for your image + text, in {budget_phrase}. "
            f"Prioritized for {uc} on brand/form-factor and price fit."
        )
        sections.append(
            {
                "anchor_id": anchor.get("anchor_id"),
                "title": f"{anchor.get('title')} {'(' + str(anchor.get('brand_hint')) + ')' if anchor.get('brand_hint') else ''}".strip(),
                "source_image_hash": anchor.get("image_hash"),
                "anchor_hint": {
                    "brand": anchor.get("brand_hint"),
                    "use_case": anchor.get("use_case_hint"),
                    "ocr_excerpt": anchor.get("ocr_excerpt"),
                },
                "top_products": top,
                "summary": summary,
                "match_basis": ["budget_fit", "query_intent", "image_brand_hint", "persona_profile"],
            }
        )
    return sections


def _build_right_panel_contract(
    *,
    products: List[Dict[str, Any]],
    turn_intent: str,
    budget_viability: Dict[str, Any] | None,
    use_case_analysis: Dict[str, Any] | None,
    anchor_sections: List[Dict[str, Any]] | None = None,
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
        "anchor_sections": anchor_sections or [],
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
    if isinstance(img.get("cv_signals"), dict):
        sec_signals.update(img.get("cv_signals") or {})
    if isinstance(sec.get("signals"), dict):
        sec_signals.update(sec.get("signals") or {})
    if isinstance(sec.get("cv_signals"), dict):
        sec_signals.update(sec.get("cv_signals") or {})
    if isinstance(sec, dict):
        for k, v in sec.items():
            if isinstance(v, bool):
                sec_signals[k] = v
    # Accept direct top-level signals from triage payloads too.
    for k in (
        "qr_code_detected",
        "qr_prompt_injection",
        "qr_external_url_detected",
        "ocr_prompt_injection",
        "manipulation_detected",
        "damage_detected",
        "steg_suspicious",
        "encoded_payload_detected",
        "polyglot_suspected",
        "payment_social_engineering",
        "pci_card_exposed",
        "crypto_payment_uri",
        "ransomware_indicator",
        "homoglyph_injection",
        "invisible_text_suspected",
        "ocr_low_confidence_uncertain",
    ):
        if isinstance(img.get(k), bool):
            sec_signals[k] = bool(img.get(k))
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
    ocr_txt = str(img.get("ocr_text") or "")
    qr_data = img.get("qr_data")
    qr_data_present = bool((isinstance(qr_data, str) and qr_data.strip()) or (isinstance(qr_data, list) and len(qr_data) > 0))
    ocr_url_like = bool(re.search(r"(https?://|www\.|payid|wallet|crypto|btc|eth|scan\s+to\s+pay)", ocr_txt.lower()))
    return {
        "qr_code_detected": bool(qr_detected or qr_data_present),
        "qr_prompt_injection": qr_injection,
        "qr_external_url_detected": qr_external,
        "ocr_prompt_injection": bool(sec_signals.get("ocr_prompt_injection") or ocr_url_like),
        "manipulation_detected": manipulation,
        "adversarial_score": float(sec_signals.get("adversarial_score") or 0.0),
        "steg_suspicious": bool(sec_signals.get("steg_suspicious")),
        "ocr_low_confidence_uncertain": bool(sec_signals.get("ocr_low_confidence_uncertain")),
        "qr_payloads": sec_signals.get("qr_payloads") if isinstance(sec_signals.get("qr_payloads"), list) else [],
        "qr_payload_types": sec_signals.get("qr_payload_types") if isinstance(sec_signals.get("qr_payload_types"), list) else [],
        "qr_redirect_probe": sec_signals.get("qr_redirect_probe") if isinstance(sec_signals.get("qr_redirect_probe"), dict) else {},
    }


def _extract_image_product_identity(image_obj: Dict[str, Any] | None) -> Dict[str, Any]:
    img = image_obj if isinstance(image_obj, dict) else {}
    ident = img.get("product_identity")
    if isinstance(ident, dict):
        return dict(ident)
    sec = img.get("security") if isinstance(img.get("security"), dict) else {}
    ident = sec.get("product_identity")
    if isinstance(ident, dict):
        return dict(ident)
    return {}


def _derive_image_security_posture(sig: Dict[str, Any] | None) -> Dict[str, Any]:
    s = sig if isinstance(sig, dict) else {}
    qr_detected = bool(s.get("qr_code_detected"))
    qr_external = bool(s.get("qr_external_url_detected"))
    qr_injection = bool(s.get("qr_prompt_injection"))
    ocr_injection = bool(s.get("ocr_prompt_injection"))
    manipulation = bool(s.get("manipulation_detected"))
    steg = bool(s.get("steg_suspicious"))
    adversarial = float(s.get("adversarial_score") or 0.0)
    encoded = bool(s.get("encoded_payload_detected"))
    polyglot = bool(s.get("polyglot_suspected"))
    ocr_uncertain = bool(s.get("ocr_low_confidence_uncertain"))

    hard_lock = bool(
        polyglot
        or (
            qr_injection
            and (qr_external or ocr_injection)
            and (manipulation or steg or adversarial >= 0.75 or encoded)
        )
        or (qr_external and (manipulation or steg or adversarial >= 0.9))
    )
    needs_review = bool(
        hard_lock
        or qr_external
        or ocr_injection
        or steg
        or adversarial >= 0.5
        or encoded
        or ocr_uncertain
    )
    degraded = bool(
        qr_detected
        or qr_external
        or qr_injection
        or ocr_injection
        or manipulation
        or steg
        or adversarial >= 0.35
        or encoded
        or ocr_uncertain
    )
    if hard_lock:
        route = "lockdown"
        severity = "high"
        message = (
            "Image content looks unsafe (malicious QR/injection risk). "
            "Chat is temporarily locked for image-driven actions while we escalate to human review."
        )
    elif needs_review:
        route = "escalate"
        severity = "high"
        message = (
            "Image was flagged. I will continue with text-only recommendations and escalate security review in parallel."
        )
    elif degraded:
        route = "visual_sanitized"
        severity = "warn"
        message = (
            "Image looks untrusted. Continuing in text-only mode; reupload a clean product-only photo for precise visual matching."
        )
    else:
        route = "allow"
        severity = "info"
        message = ""
    return {
        "route": route,
        "severity": severity,
        "image_untrusted": bool(degraded),
        "image_degraded_mode": bool(degraded and not hard_lock),
        "needs_human_review": bool(needs_review),
        "chat_lockdown": bool(hard_lock),
        "warning_message": message,
    }


def _derive_attack_intent_and_repercussions(cv_signals: Dict[str, Any] | None) -> tuple[str, str]:
    """Map detected CV signals to a plain-English attacker intent + likely repercussions.

    Briefs the human SOC reviewer on *why* an upload was flagged and what could go
    wrong if the image-derived signals were trusted blindly.
    """
    s = cv_signals if isinstance(cv_signals, dict) else {}
    intents: List[str] = []
    repercussions: List[str] = []
    if s.get("qr_prompt_injection") or s.get("qr_external_url_detected") or s.get("qr_code_detected"):
        intents.append(
            "QR-borne indirect prompt injection / redirect to an external "
            "(possible credential-harvest or malware) URL"
        )
        repercussions.append(
            "agent goal hijack, shopper redirected to a malicious site, possible "
            "credential/account compromise"
        )
    if s.get("ocr_prompt_injection"):
        intents.append("text-in-image prompt injection to override system instructions")
        repercussions.append("policy bypass, unauthorised tool or action execution by the agent")
    if s.get("steg_suspicious"):
        intents.append("steganographic payload smuggling (covert data/command channel)")
        repercussions.append("covert data exfiltration or staged second-stage payload delivery")
    if float(s.get("adversarial_score") or 0.0) >= 0.5:
        intents.append("adversarial perturbation crafted to evade the CV classifiers")
        repercussions.append("model evasion, mislabelled product, downstream fraud")
    if s.get("manipulation_detected"):
        intents.append("image manipulation / forgery")
        repercussions.append("return or warranty fraud, fabricated evidence")
    if s.get("encoded_payload_detected") or s.get("polyglot_suspected"):
        intents.append("encoded / polyglot file payload (a file valid as two formats at once)")
        repercussions.append("parser confusion, sandbox escape, malware delivery")
    if not intents:
        intents.append("untrusted or anomalous image upload")
        repercussions.append("elevated review required before any image-derived signal can be trusted")
    return "; ".join(intents), "; ".join(repercussions)


def _summarize_recognized_product(labels: List[str] | None) -> Optional[str]:
    """Best-effort short human label for what the image shows, from SAFE visual labels.

    Lets us keep shopping context in the user-facing message even when the image
    was flagged — we still recognised the product, we just quarantined the
    malicious channel (QR/OCR/steg). Returns None when nothing is recognisable.
    """
    toks = [str(x).lower() for x in (labels or []) if str(x).strip()]
    if not toks:
        return None
    blob = " ".join(toks)
    _is_gaming = any(
        t in blob for t in ("gaming", "rog", "legion", "raider", "predator", "nitro", "alienware", "omen", "tuf")
    )
    if any(t in blob for t in ("laptop", "notebook", "macbook")):
        return "gaming laptop" if _is_gaming else "laptop"
    if any(t in blob for t in ("desktop", "tower", "workstation")) or "pc" in toks:
        return "gaming PC" if _is_gaming else "desktop PC"
    if any(t in blob for t in ("phone", "smartphone", "iphone")):
        return "phone"
    if any(t in blob for t in ("tablet", "ipad")):
        return "tablet"
    if any(t in blob for t in ("monitor", "display", "screen")):
        return "monitor"
    if any(t in blob for t in ("headphone", "headset", "earphone")):
        return "headset"
    return toks[0]


def _assess_image_compromise_breach(
    *,
    merged_text: str,
    cv_signals: Dict[str, Any] | None,
    source_ip: str | None,
    uid: str | None,
    image_hash: str | None,
    posture: Dict[str, Any],
    request: Any = None,
) -> Dict[str, Any]:
    """Run a synchronous breach assessment for a compromised image upload.

    Enriches the requester IP via ASN/GeoIP (known-bad-actor scoring), maps the
    attack to MITRE ATLAS / OWASP tags, and notifies humans by persisting a
    security event that auto-routes to an incident + WORM audit. Returns a
    structured summary for the chat response.

    NEVER blocks the recommendation — this is the warn-and-continue path.
    """
    from src.app.security.observer import analyze_payload, emit_security_event

    intent, repercussions = _derive_attack_intent_and_repercussions(cv_signals)
    sec_payload: Dict[str, Any] = {
        "query": str(merged_text or "")[:1000],
        "source": "chat_image_compromise",
    }
    if source_ip:
        sec_payload["ip"] = source_ip
    if uid:
        sec_payload["uid"] = uid
    if cv_signals:
        sec_payload["cv_signals"] = cv_signals

    severity = str(posture.get("severity") or "high")
    details: Dict[str, Any] = {}
    try:
        analysis = analyze_payload(sec_payload)
        if isinstance(analysis, dict):
            severity = str(analysis.get("severity") or severity)
            details = analysis.get("details") if isinstance(analysis.get("details"), dict) else {}
    except Exception:
        details = {}

    geo: Dict[str, Any] = {}
    signals: Dict[str, Any] = {}
    try:
        geo = ((details.get("network") or {}).get("geo")) or {}
        signals = details.get("signals") or {}
    except Exception:
        geo, signals = {}, {}

    # Known-bad-actor determination via ASN / GeoIP risk.
    bad_asn: set = set()
    try:
        from src.app.security.observer import _load_bad_asn
        bad_asn = set(_load_bad_asn())
    except Exception:
        bad_asn = set()
    is_bad_actor = bool(
        signals.get("ip_risk")
        or float(geo.get("risk") or 0.0) >= 0.7
        or geo.get("is_hosting")
        or geo.get("is_vpn")
        or (geo.get("asn") in bad_asn if geo.get("asn") is not None else False)
    )
    ip_assessment = {
        "ip_hash": ((details.get("network") or {}).get("ip_hash")),
        "asn": geo.get("asn"),
        "asn_org": geo.get("asn_org"),
        "country": geo.get("country"),
        "is_hosting": bool(geo.get("is_hosting")),
        "is_vpn": bool(geo.get("is_vpn")),
        "risk": float(geo.get("risk") or 0.0),
        "known_bad_actor": is_bad_actor,
        "geo_country_mismatch": bool(signals.get("geo_country_mismatch")),
    }

    # Notify humans: persist a security event that auto-routes to an incident + WORM.
    human_notified = False
    try:
        emit_security_event(
            path="/api/v1/chat/image-compromise",
            payload={
                **sec_payload,
                "attack_intent": intent,
                "repercussions": repercussions,
                "image_hash": str(image_hash or "")[:64],
                "ip_assessment": ip_assessment,
            },
            request=request,
        )
        human_notified = True
    except Exception:
        human_notified = False

    assessment = {
        "severity": severity,
        "attack_intent": intent,
        "potential_repercussions": repercussions,
        "ip_assessment": ip_assessment,
        "mitre_atlas": (details.get("mitre_atlas") or [])[:8],
        "owasp_llm_top10": (details.get("owasp_llm_top10") or [])[:8],
        "owasp_agentic_top10": (details.get("owasp_agentic_top10") or [])[:8],
        "human_notified": human_notified,
        "route": str(posture.get("route") or "escalate"),
    }
    try:
        log_trace_event(
            trace_id=None,
            event_type="image_compromise_breach_assessment",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="chat",
            target_id=uid,
            payload={
                "severity": severity,
                "attack_intent": intent,
                "known_bad_actor": is_bad_actor,
                "asn": geo.get("asn"),
                "country": geo.get("country"),
                "image_hash": str(image_hash or "")[:64],
            },
        )
    except Exception:
        pass
    return assessment


def _derive_qr_details(sig: Dict[str, Any] | None, posture: Dict[str, Any] | None = None) -> Dict[str, Any]:
    p = posture if isinstance(posture, dict) else {}
    route = str(p.get("route") or "allow")
    return derive_qr_legitimacy_details(sig, policy_route=route)


def _image_trust_channels(posture: Dict[str, Any] | None) -> Dict[str, bool]:
    route = str((posture or {}).get("route") or "allow")
    if route == "allow":
        return {"visual_embedding_trusted": True, "ocr_trusted": True, "qr_trusted": True}
    if route == "visual_sanitized":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    if route == "escalate":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    return {"visual_embedding_trusted": False, "ocr_trusted": False, "qr_trusted": False}


def _frameworks_for_image_security(*, signals: Dict[str, Any], severity: str) -> Dict[str, Any]:
    norm = {str(k): bool(v) for k, v in (signals or {}).items()}
    dread = compute_dread(signals={}, cv_signals=norm, severity=severity or "warn")
    corr = correlate_security_analysis(
        channel="image",
        severity=severity,
        tags=[],
        reasons=[],
        threat_correlation={"mitre_attack": [], "dread": dread},
        signals=norm,
        evidence={},
    )
    return {
        "mitre_atlas": corr.get("mitre_atlas") or [],
        "mitre_attack": corr.get("mitre_attack") or [],
        "owasp_llm_top10": corr.get("owasp_llm_top10") or [],
        "stride_categories": corr.get("stride_categories") or [],
        "pasta": corr.get("pasta") or {},
        "pasta_stage": corr.get("pasta_stage"),
        "dread": dread,
        "cvss": corr.get("cvss") or {},
        "compliance": corr.get("compliance") or {},
        "lev": corr.get("lev") or {},
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
    image_product_identity_in = (payload or {}).get("image_product_identity")
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
            if not image_product_identity_in:
                image_product_identity_in = _extract_image_product_identity(first)
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
            merged["steg_suspicious"] = bool(merged.get("steg_suspicious") or sig.get("steg_suspicious"))
            merged["adversarial_score"] = max(
                float(merged.get("adversarial_score") or 0.0),
                float(sig.get("adversarial_score") or 0.0),
            )
            qp_old = merged.get("qr_payloads") if isinstance(merged.get("qr_payloads"), list) else []
            qp_new = sig.get("qr_payloads") if isinstance(sig.get("qr_payloads"), list) else []
            if qp_new:
                merged["qr_payloads"] = (qp_old + qp_new)[:12]
            qpt_old = merged.get("qr_payload_types") if isinstance(merged.get("qr_payload_types"), list) else []
            qpt_new = sig.get("qr_payload_types") if isinstance(sig.get("qr_payload_types"), list) else []
            if qpt_new:
                merged["qr_payload_types"] = list(dict.fromkeys([str(x) for x in (qpt_old + qpt_new) if str(x).strip()]))[:12]
            if not merged.get("qr_redirect_probe") and isinstance(sig.get("qr_redirect_probe"), dict):
                merged["qr_redirect_probe"] = sig.get("qr_redirect_probe")
        image_cv_signals_in = merged
    image_security_posture = _derive_image_security_posture(image_cv_signals_in)
    breach_assessment: Optional[Dict[str, Any]] = None
    # How the (untrusted) image was handled downstream:
    #   "sanitized_visual" = kept safe product recognition, quarantined QR/OCR/steg
    #   "text_only_fallback" = pixels themselves suspect (adversarial/manipulated) → ask to clarify
    image_handling_mode: Optional[str] = None
    recognized_image_label: Optional[str] = None

    if not q.strip():
        raise HTTPException(status_code=400, detail="query_required")

    uid = _resolve_uid(payload, request)
    session_id = str((payload or {}).get("session_id") or "")[:128] or None
    source_ip = request.client.host if request and request.client else ""
    turn_intent = _classify_turn_intent(q)
    copywriting_requested = bool((payload or {}).get("copywriting_enabled") is True)
    copy_profile_id = str((payload or {}).get("copy_profile_id") or "").strip() or None
    copy_surface = str((payload or {}).get("copy_surface") or "storefront").strip() or "storefront"
    brand_name = str((payload or {}).get("brand_name") or "").strip() or None
    copy_profile_inline = (payload or {}).get("copy_profile")
    if not isinstance(copy_profile_inline, dict):
        copy_profile_inline = None

    # Reload confirmed slots at turn start to keep context continuity explicit.
    # Also capture the PRIOR turn's shortlist NOW (before this turn's recommend overwrites it) so the
    # multi-intent planner can bind "actually 15 instead" to the item the buyer was just shown when the
    # cart is empty (e.g. an add-to-cart 409'd on stock).
    _prior_turn_shortlist: List[str] = []
    try:
        _prior_ss = Memory(redis).get_structured_state(uid) or {}
        _confirmed_in = _prior_ss.get("confirmed_slots") if isinstance(_prior_ss.get("confirmed_slots"), dict) else {}
        if _confirmed_in:
            payload["confirmed_slots"] = _confirmed_in
        _ls = _prior_ss.get("last_shortlist_skus") or _prior_ss.get("last_valid_shortlist_skus")
        if isinstance(_ls, list):
            _prior_turn_shortlist = [str(s) for s in _ls if s][:5]
    except Exception:
        pass

    # Replay protection: reject immediate duplicates from retries/replays.
    try:
        # SKIP when invoked from the /chat/stream wrapper: chat_stream calls chat_query internally, so
        # marking here would make the frontend's stream→/chat/query FALLBACK look like a duplicate (the
        # 409 chat_replay_detected demo blocker). Only the terminal /chat/query enforces replay protection.
        _skip_replay = bool((payload or {}).get("_internal_skip_replay"))
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
        if require_nonce and not replay_nonce and not _skip_replay:
            raise HTTPException(status_code=428, detail={"message": "nonce_required"})
        if replay_nonce:
            replay_ttl = max(replay_ttl, 120)
        if not _skip_replay and not _chat_replay_mark_once(redis, replay_key=replay_key, ttl_seconds=replay_ttl):
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
        if source_ip:
            _sec_payload["ip"] = source_ip
        if uid:
            _sec_payload["uid"] = uid
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
                # Warn-and-continue: when an image is involved, run a full breach
                # assessment (IP/ASN/GeoIP + human escalation). Products still flow.
                if image_cv_signals_in and breach_assessment is None:
                    try:
                        breach_assessment = _assess_image_compromise_breach(
                            merged_text=merged_text,
                            cv_signals=image_cv_signals_in,
                            source_ip=source_ip,
                            uid=uid,
                            image_hash=image_hash_in,
                            posture=image_security_posture,
                            request=request,
                        )
                    except Exception:
                        breach_assessment = None
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
        uid_for_cache = _resolve_uid(payload, request)
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

    # Log escalation trace event for steg/suspicious images that need human review
    # (the lockdown path below has its own trace; this covers the escalate route)
    if bool(image_security_posture.get("needs_human_review")) and not bool(image_security_posture.get("chat_lockdown")):
        try:
            _esc_signals = {str(k): bool(v) for k, v in (image_cv_signals_in or {}).items() if isinstance(v, bool)}
            _esc_steg_score = float((image_cv_signals_in or {}).get("steg_score") or 0.0)
            log_trace_event(
                trace_id=None,
                event_type="image_security_escalation",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=uid,
                payload={
                    "route": str(image_security_posture.get("route") or "escalate"),
                    "severity": str(image_security_posture.get("severity") or "high"),
                    "signals": _esc_signals,
                    "steg_score": _esc_steg_score,
                    "image_hash": str(image_hash_in or "")[:64],
                    "query_preview": str(q or "")[:120],
                    "warning": str(image_security_posture.get("warning_message") or ""),
                },
            )
        except Exception:
            pass

    # Legacy hard-lock (deny products) is OFF by default. Policy is warn-and-continue:
    # a compromised image must NOT deny the shopping result — see the fall-through block
    # below. Set IMAGE_COMPROMISE_HARD_LOCK=1 only if you explicitly want the old deny.
    _image_hard_lock_enabled = str(os.getenv("IMAGE_COMPROMISE_HARD_LOCK", "0")).strip().lower() in ("1", "true", "yes", "on")
    if bool(image_security_posture.get("chat_lockdown")) and _image_hard_lock_enabled:
        decision_trace_id = str(uuid.uuid4())
        _sec_signals = {str(k): bool(v) for k, v in (image_cv_signals_in or {}).items() if isinstance(v, bool)}
        _qr = _derive_qr_details(image_cv_signals_in, image_security_posture)
        _trust = _image_trust_channels(image_security_posture)
        _fw = _frameworks_for_image_security(signals=_sec_signals, severity=str(image_security_posture.get("severity") or "high"))
        security_payload = {
            "severity": str(image_security_posture.get("severity") or "high"),
            "route": "lockdown",
            "policy_route": "lockdown",
            "signals": _sec_signals,
            "qr": _qr,
            "image_trust_channels": _trust,
            "qr_payload_types": image_cv_signals_in.get("qr_payload_types") if isinstance(image_cv_signals_in.get("qr_payload_types"), list) else [],
            "qr_payloads": (image_cv_signals_in.get("qr_payloads") or [])[:6] if isinstance(image_cv_signals_in.get("qr_payloads"), list) else [],
            "qr_redirect_probe": image_cv_signals_in.get("qr_redirect_probe") if isinstance(image_cv_signals_in.get("qr_redirect_probe"), dict) else {},
            "frameworks": _fw,
            "mitre_atlas": _fw.get("mitre_atlas") or [],
            "mitre_attack": _fw.get("mitre_attack") or [],
            "owasp_llm_top10": _fw.get("owasp_llm_top10") or [],
            "stride_categories": _fw.get("stride_categories") or [],
            "pasta": _fw.get("pasta") or {},
            "pasta_stage": _fw.get("pasta_stage"),
            "dread": _fw.get("dread") or {},
            "cvss": _fw.get("cvss") or {},
            "compliance": _fw.get("compliance") or {},
            "summary": "Chat lockdown due to malicious image security posture.",
        }
        try:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=None,
                payload=security_payload,
            )
        except Exception:
            pass
        out = {
            "products": [],
            "view_mode": "cards",
            "confidence": None,
            "decision_trace_id": decision_trace_id,
            "trace_id": decision_trace_id,
            "assistant_message": str(image_security_posture.get("warning_message") or "Chat locked for safety review."),
            "next_questions": [
                {"id": "continue_text_only", "text": "Continue without image (text-only recommendations)", "goal": "text_only_mode"},
                {"id": "reupload_clean", "text": "Reupload clean product-only image", "goal": "clean_reupload"},
                {"id": "human_escalation", "text": "Open human support now", "goal": "human_escalation"},
            ],
            "blocked": True,
            "image_untrusted": True,
            "image_degraded_mode": False,
            "chat_lockdown": True,
            "needs_human_review": True,
            "right_panel": {
                "mode": "shopping",
                "show_tiers": False,
                "image_untrusted": True,
                "image_degraded_mode": False,
                "security_route": "lockdown",
                "security_summary": str(image_security_posture.get("warning_message") or ""),
            },
        }
        try:
            _store_chat_message(db, uid=uid, role="user", content=q, trace_id=decision_trace_id, session_id=session_id)
            _store_chat_message(db, uid=uid, role="assistant", content=str(out.get("assistant_message") or ""), trace_id=decision_trace_id, session_id=session_id)
        except Exception:
            pass
        return out

    # ── Severe image threat → warn-and-continue (default policy) ──────────────
    # A malicious-image posture must NOT deny the shopping result. We run a full
    # breach assessment (IP/ASN/GeoIP + human escalation), strengthen the
    # user-facing warning, and fall through to text-only recommendations. The
    # downstream recommend call runs in text_only_fallback because the image is
    # marked untrusted (image_security_posture.image_untrusted).
    if bool(image_security_posture.get("chat_lockdown")) and not _image_hard_lock_enabled:
        if breach_assessment is None:
            try:
                breach_assessment = _assess_image_compromise_breach(
                    merged_text=str(q or ""),
                    cv_signals=image_cv_signals_in,
                    source_ip=source_ip,
                    uid=uid,
                    image_hash=image_hash_in,
                    posture=image_security_posture,
                    request=request,
                )
            except Exception:
                breach_assessment = None
        # Short, accurate badge summary for the right-panel (the detailed,
        # mode-aware user message is built later in the response surface). Override
        # the stale "Chat is temporarily locked…" copy from the posture since we
        # are NOT locking — we continue with the safe channels.
        image_security_posture["route"] = "escalate_continue"
        image_security_posture["warning_message"] = (
            "Suspicious image element detected and neutralised — recommendations "
            "continue; flagged for security review."
        )
        image_security_posture["image_untrusted"] = True
        try:
            log_trace_event(
                trace_id=None,
                event_type="image_compromise_warn_and_continue",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=uid,
                payload={
                    "severity": str(image_security_posture.get("severity") or "high"),
                    "route": "escalate_continue",
                    "human_notified": bool((breach_assessment or {}).get("human_notified")),
                },
            )
        except Exception:
            pass

    # Call internal recommend endpoint to leverage agentic pipeline
    base = str(request.base_url).rstrip("/")
    url = f"{base}/api/v1/recommend/suggest"
    params = {"uid": uid, "query": q}
    if turn_intent and turn_intent != "SEARCH":
        params["turn_intent"] = turn_intent
    nqe_selection = (payload or {}).get("nqe_selection") or {}
    confirmed_slots = (payload or {}).get("confirmed_slots") if isinstance((payload or {}).get("confirmed_slots"), dict) else {}
    if not confirmed_slots:
        try:
            recent_for_slots = (payload or {}).get("recent_messages") if isinstance((payload or {}).get("recent_messages"), list) else []
            for msg in reversed(recent_for_slots or []):
                if not isinstance(msg, dict) or str(msg.get("role") or "").lower() != "user":
                    continue
                slots = _extract_confirmed_slots(query=str(msg.get("content") or ""), response=None)
                if slots:
                    confirmed_slots = slots
                    break
        except Exception:
            confirmed_slots = {}
    if isinstance(nqe_selection, dict):
        try:
            oval = str(nqe_selection.get("option_value") or "").strip().lower()
            if oval.startswith("expand_budget:+"):
                delta = int(oval.split(":+", 1)[1])
                # The current query is usually the button label ("Widen more (+$400)").
                # Do not re-parse that label as a real budget cap; widen from confirmed
                # prior slots only, otherwise "$400" collapses a prior 1100-1400 range.
                base_budget = _budget_range_from_slots(confirmed_slots, "")
                widened = _compute_widened_budget(base_budget, delta)
                q = (
                    f"{q}. budget between ${int(widened['budget_min'])} and ${int(widened['budget_max'])} "
                    "(widened deterministically from prior budget)"
                )
                params["query"] = q
                params["budget_min"] = int(widened["budget_min"])
                params["budget_max"] = int(widened["budget_max"])
                params["budget_widen_mode"] = "deterministic_ladder"
                params["budget_widen_delta"] = int(delta)
        except Exception:
            pass
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
        security_risky_image = bool(image_security_posture.get("image_untrusted"))
        # Channel-separated trust (A-10 resilience): the attack vector is usually
        # in ONE channel (QR / OCR text / steg payload), independent of the visual
        # product recognition. We quarantine the malicious channel but keep the
        # safe visual signal so recommendations stay anchored to the real product.
        # The visual channel itself is only suspect when the *pixels* are attacked
        # (adversarial perturbation or manipulation/forgery).
        _sig = image_cv_signals_in or {}
        _qr_or_text_threat = bool(
            _sig.get("qr_code_detected")
            or _sig.get("qr_external_url_detected")
            or _sig.get("qr_prompt_injection")
            or _sig.get("ocr_prompt_injection")
            or _sig.get("steg_suspicious")
        )
        _adversarial = float(_sig.get("adversarial_score") or 0.0)
        _manip = bool(_sig.get("manipulation_detected"))
        # The visual product recognition is only untrustworthy when the *pixels*
        # are directly attacked: a strong adversarial perturbation (targets the
        # classifier), or manipulation with NO QR/OCR/steg overlay to explain it
        # (i.e. a likely forged photo). A QR pasted onto a real product photo does
        # NOT invalidate "this is a gaming laptop" — we keep that and quarantine
        # only the QR/OCR/steg channel.
        _visual_attacked = bool(_adversarial >= 0.7 or (_manip and not _qr_or_text_threat))
        _visual_trusted = not _visual_attacked

        labels_list: List[str] = []
        if isinstance(image_labels_in, list):
            labels_list = [str(x).strip() for x in image_labels_in if str(x).strip()]
        elif isinstance(image_labels_in, str):
            labels_list = [s.strip() for s in image_labels_in.split(",") if s.strip()]
        recognized_image_label = _summarize_recognized_product(labels_list)

        if not security_risky_image:
            # Full trust — pass every channel (unchanged behavior).
            if labels_list:
                params["image_labels"] = ",".join(labels_list[:12])
            if isinstance(image_ocr_text_in, str) and image_ocr_text_in.strip():
                params["image_ocr_text"] = image_ocr_text_in.strip()[:500]
            if isinstance(image_hash_in, str) and image_hash_in.strip():
                params["image_hash"] = image_hash_in.strip()[:128]
            if isinstance(image_intent_in, str) and image_intent_in.strip():
                params["image_intent"] = image_intent_in.strip()[:32]
        elif _visual_trusted and labels_list:
            # Untrusted upload BUT visual recognition is intact → keep the safe
            # product labels (recommend's image_feature_gate will apply the
            # "sanitized" verdict: anchor on category, strip brand/OCR). We
            # deliberately DO NOT forward OCR text (injection vector) or intent.
            params["image_labels"] = ",".join(labels_list[:12])
            if isinstance(image_hash_in, str) and image_hash_in.strip():
                params["image_hash"] = image_hash_in.strip()[:128]
            params["image_security_mode"] = "sanitized_visual"
            image_handling_mode = "sanitized_visual"
        else:
            # Pixels themselves are suspect (adversarial/manipulated) or nothing
            # was recognizable → text only, and we'll ask the user to clarify the
            # product so we don't lose the shopping context.
            params["image_security_mode"] = "text_only_fallback"
            image_handling_mode = "text_only_fallback"
        # Product identity is forwarded for both trusted and sanitized paths; the
        # recommend-side gate strips brand/identity under the "sanitized" verdict.
        if isinstance(image_product_identity_in, dict) and image_product_identity_in and image_handling_mode != "text_only_fallback":
            params["image_product_identity"] = json.dumps(image_product_identity_in, separators=(",", ":"))[:1000]
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
        # Bound the storefront upstream wait (was 120s — a silent hang). Narration is async, so recommend
        # returns fast; a hung upstream now fails in ~25s (→ 502, caught below) instead of blocking 2 min.
        try:
            _upstream_timeout = float(os.getenv("CHAT_UPSTREAM_TIMEOUT_SEC", "25") or 25)
        except (TypeError, ValueError):
            _upstream_timeout = 25.0
        async with httpx.AsyncClient(timeout=_upstream_timeout) as client:
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
                if _is_budget_query_text(q):
                    budget_hint = _budget_range_from_slots(confirmed_slots, q)
                    budget_phrase = None
                    if budget_hint.get("budget_min") is not None and budget_hint.get("budget_max") is not None:
                        budget_phrase = f"${int(budget_hint['budget_min']):,}-${int(budget_hint['budget_max']):,}"
                    elif budget_hint.get("budget_max") is not None:
                        budget_phrase = f"under ${int(budget_hint['budget_max']):,}"
                    elif budget_hint.get("budget_min") is not None:
                        budget_phrase = f"from ${int(budget_hint['budget_min']):,}"
                    msg = (
                        f"I treated this as a shopping budget request{f' for {budget_phrase}' if budget_phrase else ''}, "
                        "not sensitive data. I couldn't complete the recommendation on that pass, so try the same question once more or add the main use-case in one line."
                    )
                    followups = [
                        {"id": "retry_budget_search", "text": "Retry this as a budget shopping search", "goal": "retry_search"},
                        {"id": "clarify_use_case", "text": "Add the main use-case, for example 'for school' or 'for gaming'.", "goal": "clarify_details"},
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
                        "blocked": False,
                        "blocked_detail": blocked,
                        "image_untrusted": bool(image_security_posture.get("image_untrusted")),
                        "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
                        "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
                        "needs_human_review": False,
                        "security_route": str(image_security_posture.get("route") or "allow"),
                    }
                    try:
                        uid = _resolve_uid(payload, request)
                        _store_chat_message(db, uid=uid, role="user", content=q, trace_id=decision_trace_id)
                        _store_chat_message(
                            db,
                            uid=uid,
                            role="assistant",
                            content=str(out.get("assistant_message") or ""),
                            trace_id=decision_trace_id,
                        )
                    except Exception:
                        pass
                    return out
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
                    "image_untrusted": bool(image_security_posture.get("image_untrusted")),
                    "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
                    "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
                    "needs_human_review": bool(image_security_posture.get("needs_human_review")),
                    "security_route": str(image_security_posture.get("route") or "review"),
                }
                try:
                    uid = _resolve_uid(payload, request)
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
        import traceback as _tb
        _detail = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        logger.warning("chat.recommend_call_failed detail=%s tb=%s", _detail, _tb.format_exc()[-500:])
        raise HTTPException(status_code=502, detail=f"recommend_unavailable: {_detail}")

    # Map results into canonical product shape
    results = data.get("results") or []
    products: List[Dict] = []
    for item in results:
        price = item.get("price")
        price_cents = item.get("price_cents")
        if price is None:
            try:
                if price_cents is not None:
                    price = cents_to_dollars(price_cents)
            except Exception:
                price = None
        if price_cents is None and price is not None:
            try:
                price_cents = dollars_to_cents(price)
            except Exception:
                price_cents = None
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
        product_out = {
            "sku": item.get("sku"),
            "name": item.get("name"),
            "price": price,
            "price_cents": price_cents,
            "currency": item.get("currency") or "USD",
            "specs": specs,
            "features": features or (item.get("features") or []),
            "image_url": item.get("image_url"),
            "why": why,
            "score_norm": item.get("score_norm"),
            "score": item.get("score"),
            "factors": item.get("factors") or {},
            "why_not": item.get("why_not") or [],
            "stock": item.get("stock"),
            "stock_level": item.get("stock_level"),
            "stock_status": item.get("stock_status"),
            "stock_urgency": item.get("stock_urgency"),
            "cart_eligible": item.get("cart_eligible"),
            "confidence": item.get("confidence"),
        }
        for optional_key in ("id", "brand", "category", "reason_codes", "contrastive_why", "rank_delta", "rerank_delta"):
            if optional_key in item:
                product_out[optional_key] = item.get(optional_key)
        products.append(product_out)

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
    if bool(image_security_posture.get("image_untrusted")):
        warning = str(
            image_security_posture.get("warning_message")
            or "Image security warning detected. Continuing with text-only recommendations."
        )
        assistant_message = f"{warning}\n\n{assistant_message}" if assistant_message else warning

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
                        or image_cv_signals_in.get("ocr_low_confidence_uncertain")
                    ),
                },
            )
            sec_signals = {
                "qr_code_detected": bool(image_cv_signals_in.get("qr_code_detected")),
                "qr_prompt_injection": bool(image_cv_signals_in.get("qr_prompt_injection")),
                "qr_external_url_detected": bool(image_cv_signals_in.get("qr_external_url_detected")),
                "ocr_prompt_injection": bool(image_cv_signals_in.get("ocr_prompt_injection")),
                "ocr_low_confidence_uncertain": bool(image_cv_signals_in.get("ocr_low_confidence_uncertain")),
                "manipulation_detected": bool(image_cv_signals_in.get("manipulation_detected")),
                "damage_detected": bool(image_cv_signals_in.get("damage_detected")),
                "steg_suspicious": bool(image_cv_signals_in.get("steg_suspicious")),
            }
            sec_sev = str(image_security_posture.get("severity") or "info")
            qr_details = _derive_qr_details(image_cv_signals_in, image_security_posture)
            trust_channels = _image_trust_channels(image_security_posture)
            frameworks = _frameworks_for_image_security(signals=sec_signals, severity=sec_sev)
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="security_scan",
                source_type="agent",
                source_id="Security_Observer_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "severity": sec_sev,
                    "route": str(image_security_posture.get("route") or ("review" if sec_sev in ("high", "warn") else "allow")),
                    "policy_route": str(image_security_posture.get("route") or ("review" if sec_sev in ("high", "warn") else "allow")),
                    "qr": qr_details,
                    "image_trust_channels": trust_channels,
                    "frameworks": frameworks,
                    "mitre_atlas": frameworks.get("mitre_atlas") or [],
                    "mitre_attack": frameworks.get("mitre_attack") or [],
                    "owasp_llm_top10": frameworks.get("owasp_llm_top10") or [],
                    "stride_categories": frameworks.get("stride_categories") or [],
                    "pasta": frameworks.get("pasta") or {},
                    "pasta_stage": frameworks.get("pasta_stage"),
                    "dread": frameworks.get("dread") or {},
                    "cvss": frameworks.get("cvss") or {},
                    "compliance": frameworks.get("compliance") or {},
                    "details": {
                        "signals": sec_signals,
                        "qr_payload_types": image_cv_signals_in.get("qr_payload_types") if isinstance(image_cv_signals_in.get("qr_payload_types"), list) else [],
                        "qr_payloads": (image_cv_signals_in.get("qr_payloads") or [])[:6] if isinstance(image_cv_signals_in.get("qr_payloads"), list) else [],
                        "qr_redirect_probe": image_cv_signals_in.get("qr_redirect_probe") if isinstance(image_cv_signals_in.get("qr_redirect_probe"), dict) else {},
                        "qr": qr_details,
                        "image_trust_channels": trust_channels,
                    },
                    "signals": sec_signals,
                    "summary": "Image-sidecar security signal normalization with QR payload evidence",
                },
            )
    except Exception:
        pass
    next_questions = data.get("next_questions") or []
    # Grounding ladder: guarantee the SPECIFIC identity clarification ("Is this a
    # Razer?") leads when the ladder couldn't confirm the product — robust against
    # the NQE cap/transform ordering that can drop it on some paths.
    try:
        _gl_rq = (data.get("constraints_used") or {}).get("_identity_residual_question") if isinstance(data.get("constraints_used"), dict) else None
        if isinstance(_gl_rq, dict) and str(_gl_rq.get("text") or "").strip():
            _grid = str(_gl_rq.get("id") or "clarify_product_identity")
            next_questions = [_gl_rq] + [
                q for q in next_questions
                if isinstance(q, dict) and str(q.get("id") or "") not in ("ask_image_model", _grid)
            ]
    except Exception:
        pass
    if turn_intent in ("EXPLAIN", "SUPPORT_CLAIM"):
        next_questions = [x for x in next_questions if isinstance(x, dict) and not _is_budget_question(x)]
    if not next_questions and not products and turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM"):
        # Fallback follow-ups when no candidates are found but backend did not emit NQE prompts.
        next_questions = [
            {
                "id": "widen_budget",
                "text": "Can we widen your budget upward from your current range?",
                "goal": "increase_match_space",
                "options": [
                    {"id": "widen_small", "label": "Widen a little (+$200)", "value": "expand_budget:+200"},
                    {"id": "widen_medium", "label": "Widen more (+$400)", "value": "expand_budget:+400"},
                ],
            },
            {"id": "relax_brand", "text": "Are you open to brands beyond Apple/Windows-first picks?", "goal": "increase_match_space"},
            {"id": "priority_tradeoff", "text": "Prioritize gaming FPS or rendering/export speed first?", "goal": "resolve_tradeoff"},
        ]
    # Budget stated but NO in-budget match (nearest-above fallback shows OVER-budget products): still expose
    # the WIDEN option. The old trigger only fired when products was empty, so a budget query that fell back
    # to over-budget picks hid the widen chip (the brittle path GPT-5.5 flagged). Deterministic: budget set +
    # every shown product over it → prepend widen (unless already present). Never clobbers other questions.
    try:
        if turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM") and products:
            # budget from the QUERY (constraints_used is often empty in the chat response) → compare to the
            # shown product prices. If a ceiling was stated and EVERY shown product exceeds it, the buyer got
            # only over-budget picks → offer widen.
            from src.app.services.query_decomposer import decompose as _decompose_budget
            _bmax = _decompose_budget(str(q or "")).budget_max

            def _pp(pr: Dict[str, Any]) -> float:
                try:
                    return float(pr.get("price") or 0) or (float(pr.get("price_cents") or 0) / 100.0)
                except (TypeError, ValueError):
                    return 0.0
            _priced = [pr for pr in products if isinstance(pr, dict) and _pp(pr) > 0]
            _all_over = bool(_bmax and _priced and all(_pp(pr) > float(_bmax) for pr in _priced))
            _has_widen = any(isinstance(x, dict) and x.get("id") == "widen_budget" for x in next_questions)
            if _all_over and not _has_widen:
                next_questions = [{
                    "id": "widen_budget",
                    "text": "Nothing landed exactly in budget — widen it a little to see closer fits?",
                    "goal": "increase_match_space",
                    "options": [
                        {"id": "widen_small", "label": "Widen a little (+$200)", "value": "expand_budget:+200"},
                        {"id": "widen_medium", "label": "Widen more (+$400)", "value": "expand_budget:+400"},
                    ],
                }] + list(next_questions)
    except Exception:
        pass
    if not assistant_message and not products and next_questions:
        prompts = [f"- {q.get('text')}" for q in next_questions if isinstance(q, dict) and q.get("text")]
        assistant_message = "I could not find a confident in-catalog match yet. Try one of these refinements:\n" + "\n".join(prompts)

    aq_out = apply_answer_quality(
        query=q,
        assistant_message=assistant_message,
        turn_intent=turn_intent,
        products=products,
        image_cv_signals=image_cv_signals_in if isinstance(image_cv_signals_in, dict) else {},
        has_image=has_image,
        buyer_persona=data.get("buyer_persona"),
        brand_name=None,
    )
    assistant_message = aq_out.get("assistant_message")
    aq_intent = aq_out.get("intent_decomposed") if isinstance(aq_out.get("intent_decomposed"), dict) else {}
    aq_template = aq_out.get("template_selected") if isinstance(aq_out.get("template_selected"), dict) else {}
    aq_coverage = aq_out.get("answer_coverage_scored") if isinstance(aq_out.get("answer_coverage_scored"), dict) else {}
    try:
        if decision_trace_id:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="intent_decomposed",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_intent,
            )
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="template_selected",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_template,
            )
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="answer_coverage_scored",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload=aq_coverage,
            )
    except Exception:
        pass

    copy_out = maybe_apply_copywriting(
        assistant_message=assistant_message,
        turn_intent=turn_intent,
        surface=copy_surface,
        requested_enabled=copywriting_requested,
        profile_id=copy_profile_id,
        inline_profile=copy_profile_inline,
        brand_name=brand_name,
    )
    assistant_message = copy_out.get("assistant_message")
    # HONEST REFUSAL survives every compose path: suggest() may refuse an out-of-range quantity
    # (99999/0/negative) — the note must reach the buyer even when chat rebuilds the message
    # (answer-quality templates, copywriting, no-match compose all run after suggest's own narration).
    _refusal = str(data.get("refusal_note") or "").strip()
    if _refusal and _refusal not in str(assistant_message or ""):
        assistant_message = f"{_refusal}\n\n{assistant_message}" if assistant_message else _refusal
    copy_meta = copy_out.get("meta") if isinstance(copy_out.get("meta"), dict) else {}
    try:
        if decision_trace_id and (bool(copy_meta.get("applied")) or bool(copywriting_requested)):
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="copywriting",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "applied": bool(copy_meta.get("applied")),
                    "mode": copy_meta.get("mode"),
                    "profile_id": copy_meta.get("profile_id"),
                    "tone": copy_meta.get("tone"),
                    "surface": copy_meta.get("surface"),
                    "cpu_cost": copy_meta.get("cpu_cost"),
                    "latency_ms": copy_meta.get("latency_ms"),
                    "reason": copy_meta.get("reason"),
                },
            )
        if decision_trace_id and bool(copy_meta.get("policy_gate_triggered")):
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="copy_policy_gate",
                source_type="agent",
                source_id="Copywriting_Agent",
                target_type="chat",
                target_id=None,
                payload={
                    "action": "sanitize_claims",
                    "triggered": True,
                    "profile_id": copy_meta.get("profile_id"),
                },
            )
    except Exception:
        pass

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
            uid=_resolve_uid(payload, request),
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
    constraints_used = data.get("constraints_used") if isinstance(data.get("constraints_used"), dict) else {}
    use_case_key = (
        (use_case_analysis.get("use_case_key") if isinstance(use_case_analysis, dict) else None)
        or constraints_used.get("use_case")
    )
    effective_budget = _budget_range_from_slots(
        _extract_confirmed_slots(query=q, response=data if isinstance(data, dict) else {}),
        q,
    )
    anchor_sections = _build_anchor_sections(
        images=images_array if isinstance(images_array, list) else [],
        products=products,
        query=q,
        budget=effective_budget,
        use_case_key=str(use_case_key) if use_case_key else None,
        buyer_persona=str(data.get("buyer_persona") or "") or None,
    )
    panel_intent = "SUPPORT_CLAIM" if bool(image_cv_signals_in.get("damage_detected")) else turn_intent
    _backend_right_panel = data.get("right_panel") if isinstance(data.get("right_panel"), dict) else None
    if isinstance(_backend_right_panel, dict) and anchor_sections:
        _backend_right_panel = dict(_backend_right_panel)
        _backend_right_panel["anchor_sections"] = anchor_sections
    _right_panel_contract = _backend_right_panel or _build_right_panel_contract(
        products=products,
        turn_intent=panel_intent,
        budget_viability=budget_viability,
        use_case_analysis=use_case_analysis,
        anchor_sections=anchor_sections,
    )
    try:
        if isinstance(_right_panel_contract, dict):
            _right_panel_contract["image_untrusted"] = bool(image_security_posture.get("image_untrusted"))
            _right_panel_contract["image_degraded_mode"] = bool(image_security_posture.get("image_degraded_mode"))
            _right_panel_contract["security_route"] = str(image_security_posture.get("route") or "allow")
            if image_security_posture.get("warning_message"):
                _right_panel_contract["security_summary"] = str(image_security_posture.get("warning_message"))
    except Exception:
        pass
    try:
        if decision_trace_id:
            log_trace_event(
                trace_id=decision_trace_id,
                event_type="right_panel_anchor_sections",
                source_type="agent",
                source_id="Candidate_Retrieval_Agent",
                target_type="ui",
                target_id="right_panel",
                payload={
                    "count": len(anchor_sections),
                    "anchors": [
                        {
                            "anchor_id": str(s.get("anchor_id")),
                            "brand": ((s.get("anchor_hint") or {}).get("brand") if isinstance(s.get("anchor_hint"), dict) else None),
                            "top_skus": [str((p or {}).get("sku") or "") for p in (s.get("top_products") or [])[:3]],
                        }
                        for s in anchor_sections[:6]
                    ],
                    "products_summary": [
                        {
                            "sku": p.get("sku"),
                            "name": p.get("name"),
                            "score_norm": p.get("score_norm"),
                            "reasons": (p.get("why") or [])[:3],
                            "reason_codes": (p.get("reason_codes") or [])[:3],
                            "price": p.get("price"),
                        }
                        for p in (products or [])[:8]
                        if isinstance(p, dict)
                    ],
                    "right_panel_contract": _right_panel_contract,
                },
            )
    except Exception:
        pass

    # ── P0 multi-intent planner (flag-gated default-OFF) ─────────────────────────────────────────────
    # A mixed buyer turn — "actually make it 15, and what headsets + hard drives for $1200 for those" —
    # must (a) KEEP the chosen laptop, (b) change ITS quantity, and (c) source the new categories under the
    # SCOPED budget only. plan_live decomposes the turn against the live cart, fans out per new category, and
    # RE-CHECKS the assembled plan adversarially before we surface it. Additive: it attaches `multi_intent`
    # (with needs_confirmation so money/qty is confirmed, never guessed); it never mutates products here.
    multi_intent: Optional[Dict[str, Any]] = None
    try:
        _mi_on = str(os.getenv("MULTI_INTENT_PLANNER_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")
        if not _mi_on:
            try:
                from src.app.feature_flags import get_flags as _get_flags
                _mi_on = bool(_get_flags().get("MULTI_INTENT_PLANNER_ENABLED", False))
            except Exception:
                _mi_on = False
        if _mi_on and turn_intent not in ("EXPLAIN", "SUPPORT_CLAIM"):
            from src.app.services.multi_intent_live import plan_live
            multi_intent = plan_live(str(q or ""), str(uid), fallback_prior_skus=_prior_turn_shortlist or None)
    except Exception as _mi_exc:
        # Non-silent: attach the failure to the response instead of crashing the turn or hiding it.
        multi_intent = {"warnings": [f"multi_intent planner error: {str(_mi_exc)[:120]}"],
                        "needs_confirmation": True}

    out = {
        "products": products,
        "view_mode": view_mode,
        "confidence": confidence,
        "decision_trace_id": decision_trace_id,
        "trace_id": decision_trace_id,
        "assistant_message": assistant_message,
        "next_questions": next_questions,
        # P0 multi-intent plan (present only on a genuine mixed turn; None otherwise). Carries the scoped
        # new-line picks + adversarial verdict + needs_confirmation so the UI confirms qty/budget, not guesses.
        "multi_intent": multi_intent,
        "needs_disambiguation": bool(data.get("needs_disambiguation") or (not products and next_questions)),
        "nqe_selection_applied": data.get("nqe_selection_applied") or {},
        "confirmed_slots": _extract_confirmed_slots(query=q, response=data if isinstance(data, dict) else {}),
        "llm_model": data.get("llm_model"),
        "model_tier": data.get("model_tier"),
        "complexity": complexity_result,
        "intent_routing": intent_routing_result,
        "turn_intent": turn_intent,
        # Async narration handoff: when recommend ran in async/skip mode it returns the deterministic
        # grounded answer now + a job id for the richer LLM prose. Forward both so the storefront can
        # poll /api/v1/recommend/narration/{job_id} and replace the message in place (no blocking wait).
        "llm_summary_job_id": data.get("llm_summary_job_id"),
        "summary_pending": bool(data.get("summary_pending") or data.get("llm_summary_job_id")),
        "voice_used": bool(voice_transcript),
        "budget_viability": budget_viability,
        "use_case_analysis": use_case_analysis,
        "buyer_persona": data.get("buyer_persona"),
        # Phase-3 adaptive-storefront observability: forward the market-driven ranking adaptations (the
        # demand-aware sales-response nudge + experiment ranking nudge + storefront emphasis) so the frontend
        # and the Decision Trace can SHOW the governed adaptation ("why these moved", gate allow/deny). Each
        # is present only when its flag-gated lever ran; the products themselves are already re-ranked.
        # bulk-order intent: the parsed unit count so Add buttons land the conversation's qty, not 1.
        "requested_quantity": data.get("requested_quantity"),
        "sales_response_nudge": data.get("sales_response_nudge") if isinstance(data.get("sales_response_nudge"), dict) else None,
        "ranking_experiment": data.get("ranking_experiment") if isinstance(data.get("ranking_experiment"), dict) else None,
        "storefront_emphasis": data.get("storefront_emphasis") if isinstance(data.get("storefront_emphasis"), dict) else None,
        # Buyer-safe procurement projection from /recommend/suggest. The recommend
        # layer owns case creation/redaction; chat must preserve it so the storefront
        # can render the commitment gate instead of hiding a real shortfall.
        "availability": data.get("availability") if isinstance(data.get("availability"), dict) else None,
        "fulfillment_case": (
            data.get("fulfillment_case")
            if isinstance(data.get("fulfillment_case"), dict) and data.get("fulfillment_case", {}).get("case_id")
            else None
        ),
        # Buyer-facing bulk alternatives (partial/transfer/substitute/source/reduce) for an unmet bulk
        # request — pre-commitment, no order placed. Preserve so the right panel can offer real choices.
        "fulfillment_options": (
            data.get("fulfillment_options") if isinstance(data.get("fulfillment_options"), list) else None
        ),
        # multi-line mixed order → grouped sourcing cases (buyer-safe summary; supplier identity stays server-side)
        "order_group": (
            data.get("order_group") if isinstance(data.get("order_group"), dict) else None
        ),
        # FLUID-procurement preview (FULFILLMENT_DEFER_TO_CART): the sourcing split is PREVIEWED here
        # (no durable case); the durable case materializes at cart-confirmation. Buyer-safe (no supplier).
        "sourcing_intent": (
            data.get("sourcing_intent") if isinstance(data.get("sourcing_intent"), dict) else None
        ),
        "right_panel": _right_panel_contract,
        "copywriting": copy_meta,
        "image_untrusted": bool(image_security_posture.get("image_untrusted")),
        "image_degraded_mode": bool(image_security_posture.get("image_degraded_mode")),
        "chat_lockdown": bool(image_security_posture.get("chat_lockdown")),
        "needs_human_review": bool(image_security_posture.get("needs_human_review")),
        "security_route": str(image_security_posture.get("route") or "allow"),
    }
    if isinstance(out.get("assistant_message"), str):
        out["assistant_message"] = ResponseNormalizer.polish_llm_text(
            str(out.get("assistant_message") or ""),
            query=q,
        )
    # ── Image-compromise warn-and-continue surface ───────────────────────────
    # Products still flow; we prepend a clear warning and attach the breach
    # assessment (IP/ASN/GeoIP + intent + repercussions + human-notified) so the
    # user knows the upload is under review and the SOC has the evidence.
    if breach_assessment is not None or bool(image_security_posture.get("chat_lockdown")):
        _ba = breach_assessment if isinstance(breach_assessment, dict) else None
        # Only claim a product "in your photo" when one was actually recognised in-domain. An
        # off-domain / unrecognised upload must be narrated as text + sanitized image context — never
        # "based on the product in your photo" (the apple-image-on-gaming-query case exposed that as
        # factually wrong).
        if image_handling_mode == "sanitized_visual":
            # We kept the legitimate product recognition; only the QR/OCR/steg
            # channel was quarantined. Stay anchored on the recognised product.
            if recognized_image_label:
                _anchor = (
                    f"I still recognised {recognized_image_label} in the photo, so these "
                    f"recommendations are anchored to that. Let me know if I read the product wrong."
                )
            else:
                _anchor = (
                    "I couldn't confidently identify a product in the image, so these recommendations "
                    "are based on your text plus the image's sanitized context."
                )
            _warn_msg = (
                f"⚠️ Heads up: a suspicious element (e.g. QR code / hidden payload) in your image "
                f"was detected and neutralised — I did not open or follow it, and it's been logged for "
                f"security review. {_anchor}"
            )
        elif image_handling_mode == "text_only_fallback":
            # Pixels themselves looked altered → ask the user to recover context.
            _warn_msg = (
                f"⚠️ Your image looked altered or unreadable, so I couldn't safely identify the product "
                f"from it (this has been logged for security review). I've used your text for now — to get "
                f"you the right match, can you tell me the model or type you're after?"
            )
            _clarify_q = {
                "id": "clarify_product_identity",
                "text": "Which product is it? (model name or type, e.g. '17\" gaming laptop, RTX 4070')",
                "goal": "clarify_product_identity",
            }
            _nq = out.get("next_questions")
            if isinstance(_nq, list):
                if not any(isinstance(x, dict) and x.get("id") == "clarify_product_identity" for x in _nq):
                    out["next_questions"] = [_clarify_q] + _nq
            else:
                out["next_questions"] = [_clarify_q]
            out["needs_disambiguation"] = True
        else:
            if recognized_image_label:
                _basis = f"I've based these recommendations on {recognized_image_label} and your text."
            else:
                _basis = "I've based these recommendations on your text and the image's sanitized context."
            # Only ALARM the buyer when there is a genuine threat indicator — a benign upload that merely
            # tripped a soft posture check should not see "flagged by our security system" (the SOC breach
            # assessment + WORM audit still fire regardless; this only tunes the buyer-facing tone).
            _real_threat = (
                bool(image_security_posture.get("needs_human_review"))
                or bool(image_security_posture.get("chat_lockdown"))
                or str(image_security_posture.get("route") or "allow").lower() not in ("allow", "")
            )
            _warn_msg = (
                f"⚠️ Your uploaded image was flagged by our security system and logged for review. {_basis}"
                if _real_threat else _basis
            )
        if _ba and (_ba.get("ip_assessment") or {}).get("known_bad_actor"):
            _warn_msg = _warn_msg + " Note: this request originated from a network flagged as high-risk."
        _am = str(out.get("assistant_message") or "")
        if _warn_msg and "neutralised" not in _am.lower() and "flagged" not in _am.lower() and "[security]" not in _am.lower():
            out["assistant_message"] = f"{_warn_msg}\n\n{_am}".strip()
        out["platform_compromise"] = True
        out["needs_human_review"] = True
        out["security_warning"] = _warn_msg
        out["image_handling_mode"] = image_handling_mode
        out["recognized_product"] = recognized_image_label
        if _ba is not None:
            out["breach_assessment"] = _ba
    if isinstance(data.get("agent_steps"), list):
        out["agent_steps_readable"] = ResponseNormalizer.agent_steps_to_english(
            data.get("agent_steps") or []
        )
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
