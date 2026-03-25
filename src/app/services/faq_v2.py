from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

from src.app.services.faq_bank import FAQ_BANK, match_faq

_log = logging.getLogger("shopsquire.faq_v2")

# ---------------------------------------------------------------------------
# Vector-backed FAQ search
# ---------------------------------------------------------------------------

def _faq_by_index(idx: int) -> Dict[str, Any] | None:
    try:
        return FAQ_BANK[idx]
    except (IndexError, TypeError):
        return None


def _try_vector_faq_search(query: str, top_k: int = 3) -> List[Dict[str, Any]]:
    """Query faq_embeddings table via EmbeddingPipeline.

    Returns list of FAQ dicts ordered by vector similarity.
    Returns [] if faq_embeddings table is empty or pipeline unavailable.
    """
    try:
        from src.app.services.embedding_pipeline import EmbeddingPipeline
        from src.app.services.vector_store import PgVectorStore

        store = PgVectorStore("faq_embeddings")
        if store.engine is None:
            return []
        pipeline = EmbeddingPipeline(store=store)
        result = pipeline.query(query, top_k=top_k)
        if not result.get("ok") or not result.get("results"):
            return []
        out: List[Dict[str, Any]] = []
        for hit in result["results"]:
            payload = hit.get("payload") or {}
            if isinstance(payload, dict) and payload.get("type") == "faq":
                out.append({
                    "q": payload.get("q", ""),
                    "a": payload.get("a", ""),
                    "tags": payload.get("tags") or [],
                    "_distance": hit.get("distance"),
                })
        return out
    except Exception as exc:
        _log.debug("vector FAQ search unavailable: %s", exc)
        return []

_FAQ_STOPWORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "how", "i", "if",
    "is", "it", "my", "of", "on", "or", "the", "to", "what", "when", "with",
    "you", "your",
}


def _tokenize(text: str) -> List[str]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t]
    return [t for t in tokens if t not in _FAQ_STOPWORDS]


def _intent(query: str) -> str:
    q = (query or "").lower()
    if any(k in q for k in ("return", "refund", "warranty", "exchange", "damaged", "broken")):
        return "returns_warranty"
    if any(k in q for k in ("shipping", "track", "delivery", "shipment")):
        return "shipping"
    if any(k in q for k in ("payment", "card", "paypal", "wallet", "chargeback")):
        return "payments"
    if any(k in q for k in ("dashboard", "approval rate", "autonomy", "margin", "sales trend")):
        return "admin_analytics"
    return "general"


def _jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    return float(len(sa & sb)) / float(max(1, len(sa | sb)))


def semantic_match_faq(query: str, *, role: str = "buyer") -> Tuple[Dict[str, Any] | None, float, str]:
    q_intent = _intent(query)

    # Vector search path — try first, fall back to Jaccard if unavailable/empty
    vector_hits = _try_vector_faq_search(query, top_k=3)
    if vector_hits:
        best_vec = vector_hits[0]
        dist = best_vec.get("_distance")
        # Convert L2 distance to a confidence-like score (lower distance = higher confidence)
        # Typical L2 distances for text embeddings range 0–2; map to 0.4–0.9
        if dist is not None:
            vec_score = max(0.0, min(1.0, 1.0 - float(dist) / 2.0))
        else:
            vec_score = 0.6
        if vec_score >= 0.45:
            item = {"q": best_vec["q"], "a": best_vec["a"], "tags": best_vec["tags"]}
            answer = str(item.get("a") or "")
            if q_intent == "returns_warranty" and ("return" not in answer.lower() and "warranty" not in answer.lower()):
                answer = f"{answer} For returns/warranty claims, submit a return request with photos and order evidence."
            if role in ("admin", "owner", "developer"):
                if q_intent == "admin_analytics":
                    answer = (
                        "Use Executive Pulse and NL-to-BI query agent in Admin BI for trends, "
                        "anomalies, causal chips, and decision replay by policy version."
                    )
                else:
                    answer = f"{answer} Admin note: audit this via Decision Replay and security trend pack before policy changes."
            out = {"q": item.get("q"), "a": answer, "tags": item.get("tags") or [], "_source": "vector"}
            return out, vec_score, q_intent

    # Jaccard fallback
    q_tokens = _tokenize(query)
    best: Dict[str, Any] | None = None
    best_score = 0.0
    for item in FAQ_BANK:
        q_text = str(item.get("q") or "")
        tags = [str(x) for x in (item.get("tags") or [])]
        cand_tokens = _tokenize(q_text) + _tokenize(" ".join(tags))
        score = _jaccard(q_tokens, cand_tokens)
        if q_intent in ("returns_warranty", "shipping", "payments"):
            if q_intent == "returns_warranty" and any(t in tags for t in ("return", "refund", "warranty", "damaged")):
                score += 0.15
            if q_intent == "shipping" and any(t in tags for t in ("shipping", "tracking", "delivery")):
                score += 0.15
            if q_intent == "payments" and any(t in tags for t in ("payment", "refund", "tax")):
                score += 0.15
        if score > best_score:
            best_score = score
            best = item
    if best is None:
        if role in ("admin", "owner", "developer") and q_intent == "admin_analytics":
            return (
                {
                    "q": "How is the business performing?",
                    "a": "Use Executive Pulse and NL-to-BI query agent in Admin BI for trends, anomalies, causal chips, and decision replay by policy version.",
                    "tags": ["admin", "analytics"],
                },
                0.35,
                q_intent,
            )
        return None, 0.0, q_intent
    answer = str(best.get("a") or "")
    if q_intent == "returns_warranty" and ("return" not in answer.lower() and "warranty" not in answer.lower()):
        answer = f"{answer} For returns/warranty claims, submit a return request with photos and order evidence."
    if role in ("admin", "owner", "developer"):
        if q_intent == "admin_analytics":
            answer = (
                "Use Executive Pulse and NL-to-BI query agent in Admin BI for trends, "
                "anomalies, causal chips, and decision replay by policy version."
            )
        else:
            answer = f"{answer} Admin note: audit this via Decision Replay and security trend pack before policy changes."
    out = {"q": best.get("q"), "a": answer, "tags": best.get("tags") or []}
    return out, min(1.0, best_score), q_intent


def resolve_faq_match(query: str, *, role: str = "buyer") -> Dict[str, Any] | None:
    lexical_item, lexical_score = match_faq(query or "")
    semantic_item, semantic_score, intent = semantic_match_faq(query or "", role=role)

    lexical_strong = bool(lexical_item and lexical_score >= 3.0)
    semantic_threshold = 0.55 if intent == "general" else 0.45
    semantic_ok = bool(semantic_item and semantic_score >= semantic_threshold)

    if lexical_strong:
        return {
            "answer": str(lexical_item.get("a") or ""),
            "source": "faq",
            "confidence": min(1.0, float(lexical_score) / 5.0),
            "question": lexical_item.get("q"),
            "intent": intent,
        }
    if semantic_ok:
        return {
            "answer": str(semantic_item.get("a") or ""),
            "source": "faq_v2",
            "confidence": float(semantic_score),
            "question": semantic_item.get("q"),
            "intent": intent,
        }
    if lexical_item and lexical_score >= 2.0:
        return {
            "answer": str(lexical_item.get("a") or ""),
            "source": "faq",
            "confidence": min(1.0, float(lexical_score) / 5.0),
            "question": lexical_item.get("q"),
            "intent": intent,
        }
    return None
