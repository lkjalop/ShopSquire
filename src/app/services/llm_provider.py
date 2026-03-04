from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from src.app.services.decision_log import log_trace_event

import httpx

SMALL_DEFAULT = os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b")
BIG_DEFAULT = os.getenv("OLLAMA_BIG_MODEL", "mixtral:8x7b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# ---------------------------------------------------------------------------
# Tier ladder (loaded once, cached)
# ---------------------------------------------------------------------------
_TIER_LADDER: Optional[Dict[str, Any]] = None


def _load_tier_ladder() -> Dict[str, Any]:
    global _TIER_LADDER
    if _TIER_LADDER is not None:
        return _TIER_LADDER
    path = os.getenv("TIER_LADDER_PATH", os.path.join("config", "ml", "tier_ladder.json"))
    try:
        with open(path, "r", encoding="utf-8") as f:
            _TIER_LADDER = json.load(f)
    except Exception:
        _TIER_LADDER = {}
    return _TIER_LADDER


def _tier_for_score(score: int) -> Tuple[str, Optional[str]]:
    """Return (tier_name, model_name) for a given complexity score."""
    ladder = _load_tier_ladder()
    tiers = ladder.get("tiers") or []
    for t in tiers:
        if t.get("score_min", 0) <= score <= t.get("score_max", 10):
            model = t.get("model")
            # Allow env overrides
            if model and "small" in (t.get("name") or ""):
                model = os.getenv("OLLAMA_SMALL_MODEL", model)
            elif model and t.get("name") in ("large", "expert"):
                model = os.getenv("OLLAMA_BIG_MODEL", model)
            elif model and t.get("name") == "medium":
                model = os.getenv("OLLAMA_MEDIUM_MODEL", os.getenv("OLLAMA_BIG_MODEL", model))
            return t.get("name", "small"), model
    # Fallback
    return ("small", SMALL_DEFAULT) if score < 5 else ("large", BIG_DEFAULT)


# ---------------------------------------------------------------------------
# Comparison / technical keyword lists
# ---------------------------------------------------------------------------
COMPARISON_KEYWORDS = [
    "compare", "tradeoff", "trade-off", "vs", "versus", "difference",
    "better", "which one", "pros and cons",
]

TECHNICAL_KEYWORDS = [
    "explain", "justify", "policy", "compliance", "virtualization", "cad",
    "passthrough", "architecture", "train", "training", "fine-tune", "finetune",
    "llm", "gpu", "vram", "cuda", "tensor", "inference", "quantization",
    "rag", "embedding", "transformer",
    "rtx", "radeon", "ram", "ssd", "nvme", "cpu", "cores", "threads",
    "benchmark", "specs", "resolution", "refresh rate", "thunderbolt",
]

NEGATION_PATTERNS = re.compile(
    r"\b(not|except|exclude|without|no\s+\w+|don'?t want)\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Dynamic N-tier complexity scorer
# ---------------------------------------------------------------------------
def score_query_complexity(
    query: str,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score a query on a 0-10 complexity scale using multiple signals.

    Parameters
    ----------
    query : str
        The user query text.
    context : dict, optional
        Session context with keys like ``conversation_turn``, ``has_image``,
        ``followup_explain``, ``constraints_present`` (list of present constraint names).

    Returns
    -------
    dict with keys: score, signals, tier, model, tier_description
    """
    q = (query or "").lower().strip()
    ctx = context or {}
    signals: Dict[str, int] = {}
    explanations: List[str] = []

    # 1. Length
    if len(q) > 200:
        signals["length_200"] = 2
        explanations.append(f"Long query ({len(q)} chars)")
    elif len(q) > 100:
        signals["length_100"] = 1
        explanations.append(f"Moderate length ({len(q)} chars)")

    # 2. Comparison keywords
    matched_comp = [k for k in COMPARISON_KEYWORDS if k in q]
    if matched_comp:
        signals["comparison_keywords"] = 2
        explanations.append(f"Comparison terms: {', '.join(matched_comp[:3])}")

    # 3. Technical keywords — scale with match count
    matched_tech = [k for k in TECHNICAL_KEYWORDS if k in q]
    if len(matched_tech) >= 3:
        signals["technical_keywords"] = 2
        explanations.append(f"Heavy technical terms: {', '.join(matched_tech[:4])}")
    elif matched_tech:
        signals["technical_keywords"] = 1
        explanations.append(f"Technical terms: {', '.join(matched_tech[:3])}")

    # 4. Conjunctions
    conj = sum(q.count(k) for k in [" and ", " or ", ", "])
    if conj >= 2:
        signals["conjunction_count"] = 1
        explanations.append(f"Multiple clauses ({conj} conjunctions)")

    # 5. Multi-turn depth
    turn = int(ctx.get("conversation_turn") or 0)
    if turn > 3:
        signals["multi_turn_depth"] = 1
        explanations.append(f"Deep conversation (turn {turn})")

    # 6. Multimodal (image + text)
    if ctx.get("has_image"):
        signals["multimodal"] = 1
        explanations.append("Multimodal input (image + text)")
        # BUG-2 fix: visual similarity intent with image → +2
        import re as _re
        if _re.search(r"\b(similar|like this|alternatives?|compare|price range|same as|equivalent)\b", q):
            signals["visual_similarity_intent"] = 2
            explanations.append("Visual similarity intent with uploaded product image")
        # Use-case query with image → +1
        if _re.search(r"\b(university|school|work|gaming|editing|engineering|student|college|profession)\b", q):
            signals["image_use_case_query"] = 1
            explanations.append("Use-case assessment with product image")

    # 7. Follow-up explain/why
    if ctx.get("followup_explain"):
        signals["followup_explain"] = 1
        explanations.append("Follow-up explain/why request")

    # 8. Fully constrained
    present = ctx.get("constraints_present") or []
    if all(c in present for c in ("budget", "specs", "use_case")):
        signals["fully_constrained"] = 1
        explanations.append("Fully constrained (budget + specs + use_case)")

    # 9. Negation constraints
    if NEGATION_PATTERNS.search(q):
        signals["negation_constraints"] = 1
        explanations.append("Negation constraints detected")

    # 10. Explicit budget / price constraint in query text
    import re as _re2
    if _re2.search(r"(budget|under|below|less than|cheaper than|max price|price range)\s*[\$€£]?\s*\d", q) or \
       _re2.search(r"[\$€£]\s*\d", q):
        signals["budget_constraint"] = 1
        explanations.append("Explicit budget/price constraint")

    total = min(10, sum(signals.values()))
    tier_name, model = _tier_for_score(total)

    return {
        "score": total,
        "signals": signals,
        "explanations": explanations,
        "tier": tier_name,
        "model": model,
        "matched_comparison": matched_comp,
        "matched_technical": matched_tech,
        "conjunction_count": conj,
    }


# ---------------------------------------------------------------------------
# Backward-compatible wrappers (used throughout codebase)
# ---------------------------------------------------------------------------
def is_complex_query(query: str, *, context: Optional[Dict[str, Any]] = None) -> bool:
    result = score_query_complexity(query, context=context)
    return result["score"] >= 5


def select_ollama_model(query: str, *, context: Optional[Dict[str, Any]] = None) -> str:
    result = score_query_complexity(query, context=context)
    return result["model"] or (BIG_DEFAULT if result["score"] >= 5 else SMALL_DEFAULT)


def complexity_explain(query: str, *, context: Optional[Dict[str, Any]] = None) -> Dict:
    """Return a structured explanation of complexity classification.

    Backward-compatible with existing callers while adding new N-tier fields.
    """
    result = score_query_complexity(query, context=context)
    q = (query or "").lower().strip()
    matched = result.get("matched_comparison", []) + result.get("matched_technical", [])
    return {
        "length_trigger": len(q) > 140,
        "matched_keywords": matched,
        "conjunction_count": result.get("conjunction_count", 0),
        "score": result["score"],
        # New N-tier fields
        "tier": result["tier"],
        "model": result["model"],
        "signals": result["signals"],
        "explanations": result.get("explanations", []),
    }


async def ollama_generate(model: str, prompt: str, options: Dict | None = None, trace_id: str | None = None) -> Dict:
    if not OLLAMA_URL:
        err = RuntimeError("OLLAMA_URL_missing")
        # surface via trace if available
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(err)})
        except Exception:
            pass
        raise err
    payload: Dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 256,
        },
    }
    if options:
        payload["options"].update(options)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=payload)
            r.raise_for_status()
            data = r.json()
        dt = (time.perf_counter() - t0) * 1000.0
        return {
            "model": model,
            "response": data.get("response"),
            "total_duration_ms": dt,
        }
    except Exception as e:
        # best-effort: log trace event so UI/telemetry surface LLM failures
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(e), "payload": {"prompt_len": len(prompt) if prompt else 0}})
        except Exception:
            pass
        raise
