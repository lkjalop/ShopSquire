from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from src.app.services.embeddings import cosine_dense, embed_text_dense


_INTENT_SEEDS: Dict[str, List[str]] = {
    "payment_redirect": [
        "update remittance destination for this cycle and use revised beneficiary route",
        "use the new settlement account and route this transfer to the revised payee",
        "redirect invoice payout to alternate beneficiary rails for this payment run",
    ],
    "urgent_pressure": [
        "this must be settled immediately before the cutoff window closes",
        "treat this as priority and complete transfer today without delay",
        "urgent settlement request with same-day completion required",
    ],
    "oob_bypass": [
        "do not call to verify and process this request directly",
        "skip voice confirmation and execute according to this message",
        "no out-of-band check is required for this transfer update",
    ],
    "credential_harvest": [
        "sign in to validate mailbox access and reauthenticate your account details",
        "verify credentials via secure sign-in to maintain payment continuity",
        "review invoice portal access by entering company credentials",
    ],
    "invoice_fraud": [
        "invoice destination has changed due to banking realignment",
        "payment terms remain the same but remittance destination has been replaced",
        "future statements should settle to updated account coordinates",
    ],
}

_INTENT_WEIGHTS: Dict[str, float] = {
    "payment_redirect": 0.28,
    "urgent_pressure": 0.18,
    "oob_bypass": 0.24,
    "credential_harvest": 0.14,
    "invoice_fraud": 0.16,
}


def _threshold(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return default


def _intent_similarity(text_vec: List[float], intent: str) -> Tuple[float, str]:
    best = 0.0
    best_seed = ""
    seeds = _INTENT_SEEDS.get(intent) or []
    for seed in seeds:
        seed_vec, _ = embed_text_dense(seed)
        sim = cosine_dense(text_vec, seed_vec)
        if sim > best:
            best = sim
            best_seed = seed
    return best, best_seed


def score_semantic_bec(email: Dict[str, Any]) -> Dict[str, Any]:
    enabled = str(os.getenv("SEMANTIC_BEC_ENABLED", "1")).strip().lower() not in ("0", "false", "off", "no")
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")
    text = f"{subject}\n{body}".strip()
    if not enabled or not text:
        return {
            "enabled": enabled,
            "score": 0.0,
            "detected": False,
            "review_threshold": _threshold("SEMANTIC_BEC_REVIEW_THRESHOLD", 0.72),
            "security_threshold": _threshold("SEMANTIC_BEC_SECURITY_THRESHOLD", 0.82),
            "provider": "none",
            "intent_scores": {},
            "matched_intent": None,
            "matched_seed": None,
        }

    text_vec, provider = embed_text_dense(text)
    intent_scores: Dict[str, float] = {}
    matched_seed: Dict[str, str] = {}
    for intent in _INTENT_SEEDS.keys():
        sim, seed = _intent_similarity(text_vec, intent)
        intent_scores[intent] = float(sim)
        matched_seed[intent] = seed

    weighted = 0.0
    for intent, score in intent_scores.items():
        weighted += float(score) * float(_INTENT_WEIGHTS.get(intent, 0.0))
    semantic_score = max(0.0, min(1.0, float(weighted)))
    matched_intent = max(intent_scores.keys(), key=lambda k: intent_scores.get(k, 0.0)) if intent_scores else None
    review_thr = _threshold("SEMANTIC_BEC_REVIEW_THRESHOLD", 0.72)
    security_thr = _threshold("SEMANTIC_BEC_SECURITY_THRESHOLD", 0.82)
    detected = semantic_score >= review_thr

    return {
        "enabled": enabled,
        "score": round(semantic_score, 4),
        "detected": bool(detected),
        "review_threshold": review_thr,
        "security_threshold": security_thr,
        "provider": provider,
        "intent_scores": {k: round(float(v), 4) for k, v in intent_scores.items()},
        "matched_intent": matched_intent,
        "matched_seed": matched_seed.get(matched_intent) if matched_intent else None,
    }
