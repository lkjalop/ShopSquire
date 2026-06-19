from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from src.app.services.decision_log import log_trace_event
from src.app.security.provider_boundary import sanitize_for_provider

import httpx

# Small tier: vision-language model — matches tier_ladder.json config.
# Must be a VLM (qwen3-vl, qwen2.5-vl, llava, etc.) so image-upload queries
# receive a model that can actually process pixel data.
SMALL_DEFAULT = os.getenv("OLLAMA_SMALL_MODEL", "qwen3-vl:8b")
# Medium / large / expert: text-reasoning models.
# qwen3.6:27b (Qwen3.5 27B Q4_K_M) — confirmed text-only, strong reasoning.
MEDIUM_DEFAULT = os.getenv("OLLAMA_MEDIUM_MODEL", "qwen3.6:27b")
BIG_DEFAULT = os.getenv("OLLAMA_BIG_MODEL", "qwen3.6:27b")
EXPERT_DEFAULT = os.getenv("OLLAMA_EXPERT_MODEL", "qwen3.6:27b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# Qwen3 thinking mode: pass /think in prompt or set think=True in options.
# Activates chain-of-thought reasoning for complex multi-hop queries.
_QWEN3_THINK_ENABLED = os.getenv("QWEN3_THINK_ENABLED", "1") == "1"
_QWEN3_THINK_SCORE_THRESHOLD = int(os.getenv("QWEN3_THINK_SCORE_THRESHOLD", "7"))

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

# Core technical keywords (vertical-agnostic reasoning signals).
_CORE_TECHNICAL_KEYWORDS = [
    "explain", "justify", "policy", "compliance",
    "architecture", "benchmark", "specs",
]

# Electronics-specific technical keywords (transitional fallback).
_ELECTRONICS_TECHNICAL_KEYWORDS = [
    "virtualization", "cad", "passthrough", "train", "training", "fine-tune", "finetune",
    "llm", "gpu", "vram", "cuda", "tensor", "inference", "quantization",
    "rag", "embedding", "transformer",
    "rtx", "radeon", "ram", "ssd", "nvme", "cpu", "cores", "threads",
    "resolution", "refresh rate", "thunderbolt",
    "gaming", "fps", "esports", "144hz", "240hz", "high refresh", "frame rate",
    "ray tracing", "dlss", "fsr", "anti-cheat", "overclocking", "thermal",
    "oled", "mini-led", "g-sync", "freesync",
]


def _get_technical_keywords() -> List[str]:
    """Resolve technical complexity keywords from the active StoreProfile.

    Profile slot: `complexity_keywords` — a list of domain-specific terms that indicate
    a query needs medium+ model tier. Falls back to electronics keywords when the profile
    lacks the slot.
    """
    try:
        from src.app.platform.store_profile import get_store_profile
        profile = get_store_profile()
        kws = profile.get("complexity_keywords")
        if isinstance(kws, list) and kws:
            return _CORE_TECHNICAL_KEYWORDS + [str(k).lower() for k in kws]
    except Exception:
        pass
    return _CORE_TECHNICAL_KEYWORDS + _ELECTRONICS_TECHNICAL_KEYWORDS


# Backward-compatible module-level alias (used by score_query_complexity).
# Resolved per-call now via _get_technical_keywords().
TECHNICAL_KEYWORDS = _CORE_TECHNICAL_KEYWORDS + _ELECTRONICS_TECHNICAL_KEYWORDS

# Use-case keywords that on their own indicate a higher-complexity product search.
# Gaming, creative, and engineering workloads need multi-constraint reasoning.
_USE_CASE_HIGH = re.compile(
    r"\b(gaming|esports|game|fps|streamer|streaming|content.creat|video.edit|3d.render|cad|"
    r"machine.learn|deep.learn|data.science|engineering|architecture|music.produc)\b",
    re.IGNORECASE,
)

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

    # 3. Technical keywords — scale with match count (profile-backed)
    _active_tech_kws = _get_technical_keywords()
    matched_tech = [k for k in _active_tech_kws if k in q]
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
        signals["multimodal"] = 2  # image alone warrants medium model minimum (was +1)
        explanations.append("Multimodal input (image + text)")
        import re as _re
        # Visual similarity: user wants "find me something like this"
        if _re.search(r"\b(similar|like this|alternatives?|compare|price range|same as|equivalent)\b", q):
            signals["visual_similarity_intent"] = 2
            explanations.append("Visual similarity intent with uploaded product image")
        # Vision synthesis: image + open-ended reasoning question
        if _re.search(
            r"\b(compatible|enough|better|difference|good for|will it|can it|should i|recommend|justify|explain)\b", q
        ):
            signals["vision_synthesis"] = 2
            explanations.append("Synthesis reasoning over uploaded image")
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
    if (_re2.search(r"(budget|under|below|less than|cheaper than|max price|price range)\s*[\$€£]?\s*\d", q)
            or _re2.search(r"[\$€£]\s*\d", q)
            or _re2.search(r"\b\d{3,5}\s+(to|and|-)\s*\d{3,5}\b", q)):  # "1200 to 1800" / "1200-1800"
        signals["budget_constraint"] = 1
        explanations.append("Explicit budget/price constraint")

    # 11. Use-case specific query (gaming/creative/engineering) — needs multi-constraint reasoning
    if _USE_CASE_HIGH.search(q):
        signals["use_case_specific"] = 2
        explanations.append("Use-case specific query (gaming/creative/engineering) — medium model minimum")

    # 11. Budget yes/no question — needs medium model to answer directly
    if _re2.search(
        r"\b(is\s+\$|is\s+that\s+enough|is\s+my\s+budget|enough\s+for|can\s+i\s+(afford|get)|will\s+\$|how\s+much\s+does)\b",
        q,
    ):
        signals["budget_question"] = 2
        explanations.append("Direct budget yes/no question — medium model required")

    total = min(10, sum(signals.values()))
    # Image input floor: bare image (no keyword match) still deserves vision-capable small model minimum.
    if ctx.get("has_image") and total < 3:
        total = 3
        explanations.append("Image input floor: score raised to 3 → VLM minimum")
    # Budget yes/no questions and use-case specific queries require at least medium tier.
    if signals.get("budget_question") and total < 5:
        total = 5
        explanations.append("Budget question floor: score raised to 5 → medium model")
    if signals.get("use_case_specific") and total < 5:
        total = 5
        explanations.append("Use-case query floor: score raised to 5 → medium model")
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


async def _openai_generate_fallback(prompt: str, options: Dict | None = None, trace_id: str | None = None) -> Dict | None:
    """Attempt OpenAI chat completion as fallback when Ollama is unavailable.

    Returns a response dict or None if OpenAI is not configured or also fails.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    prompt, _, _ = sanitize_for_provider("openai", prompt, data_categories=["llm_prompt"])
    base_url = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1").rstrip("/")
    fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", "gpt-4o-mini")
    opts = options or {}
    temperature = float(opts.get("temperature", 0.2))
    max_tokens = int(opts.get("num_predict", 256))
    payload: Dict = {
        "model": fallback_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        dt = (time.perf_counter() - t0) * 1000.0
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        try:
            log_trace_event(trace_id, "llm_fallback", "llm", fallback_model, "system", None, {"provider": "openai", "latency_ms": dt})
        except Exception:
            pass
        return {"model": fallback_model, "response": text, "total_duration_ms": dt, "provider": "openai_fallback"}
    except Exception:
        return None


async def ollama_generate(model: str, prompt: str, options: Dict | None = None, trace_id: str | None = None, *, complexity_score: int = 0) -> Dict:
    if not OLLAMA_URL:
        # Try OpenAI fallback before raising
        fallback = await _openai_generate_fallback(prompt, options, trace_id)
        if fallback is not None:
            return fallback
        err = RuntimeError("OLLAMA_URL_missing")
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(err)})
        except Exception:
            pass
        raise err
    # Thinking mode: only for large/expert tier (score >= threshold). Medium and below use no_think.
    _use_think = _QWEN3_THINK_ENABLED and "qwen3" in model.lower() and complexity_score >= _QWEN3_THINK_SCORE_THRESHOLD
    # Budget tokens and timeout scale with thinking mode
    _num_predict = 1024 if _use_think else 512
    _timeout = 90.0 if _use_think else 45.0
    payload: Dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": _num_predict,
        },
    }
    if "qwen3" in model.lower():
        payload["think"] = _use_think
    if options:
        payload["options"].update(options)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=_timeout) as client:
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
        # Ollama failed — try OpenAI fallback before propagating
        try:
            log_trace_event(trace_id, "llm_error", "llm", model, "system", None, {"error": str(e), "payload": {"prompt_len": len(prompt) if prompt else 0}})
        except Exception:
            pass
        fallback = await _openai_generate_fallback(prompt, options, trace_id)
        if fallback is not None:
            return fallback
        raise
