"""T3 auto-classification (V2 Phase 3) — variant → taxonomy node, the clamp pipeline.

The onboarding intelligence: given any merchant's catalog (the live demo's 114 products carry
ZERO category/product_type data), classify every variant onto the pinned Shopify taxonomy so
retrieval, off-catalog honesty (is_sold) and the semantic router are grounded per-product.

THE PIPELINE (model-judged CLOSED-vocab → clamp → guard → deterministic-fallback):
  1. crosswalk  — if the variant already carries a category/product_type string that matches a
                  taxonomy node name exactly, take it (deterministic, no model).
  2. candidates — deterministic lexical scoring of the product text against all 14,606 node
                  paths → top-K real handles. THIS bounds the model: it can only ever pick
                  from nodes that exist. (Vector top-K can replace this scorer later without
                  touching the contract.)
  3. model pick — the LLM reads the product text + the K candidate paths and returns ONE
                  handle from the list, with confidence. Unbounded language → bounded choice.
  4. validation — the pick must be IN the candidate list (not merely in the release: a model
                  emitting a real-but-uncandidated handle is answering a different question);
                  registry upsert re-clamps to the release as defense in depth.
  5. fallback   — any miss (bad JSON, foreign handle, timeout) → highest-scoring lexical
                  candidate at low confidence, source='lexical_fallback'. NEVER unclassified
                  silently; ALWAYS status='proposed' — a human approves before anything sells
                  (T4). The model proposes; it never publishes.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.app.services.taxonomy_registry import (
    PINNED_RELEASE,
    TaxonomyNode,
    _nodes,
    get_node,
    upsert_classification,
)

logger = logging.getLogger("shopsquire.catalog_classifier")

LLMFn = Callable[[str, float], str]
TOP_K = int(os.getenv("CLASSIFIER_TOP_K", "12"))
MODEL_CONFIDENCE_FLOOR = float(os.getenv("CLASSIFIER_CONFIDENCE_FLOOR", "0.3"))

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
# Words that describe commerce, not category — they'd otherwise dominate overlap scoring.
_STOP = frozenset("the and for with pro max plus new sale pack of in to inch".split())


@dataclass(frozen=True)
class Classification:
    sku: str
    node_handle: str
    node_path: str
    confidence: float
    source: str            # crosswalk | model | lexical_fallback
    candidates: Tuple[str, ...] = ()


def _tokens(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(str(text or "").lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def _node_token_index() -> Dict[str, frozenset]:
    """handle → token set of its full path, weighted implicitly by leaf-name via scoring."""
    return {h: frozenset(_tokens(n.full_path)) for h, n in _nodes().items()}


def candidate_nodes(text: str, *, top_k: int = TOP_K) -> List[Tuple[TaxonomyNode, float]]:
    """Deterministic top-K taxonomy candidates for a product text. Leaf-name hits are
    COVERAGE-weighted: fully matching 'Laptops' (1/1 tokens) beats partially matching
    'Laptop Power Cords' (1/3) — otherwise deep accessory leaves outrank the true category
    on their depth bonus. Path hits add support; depth only breaks ties.
    Pure + cached index → fast enough to scan all 14,606 nodes per product."""
    toks = set(_tokens(text))
    if not toks:
        return []
    # singular/plural forgiveness both ways: laptop↔laptops, dress↔dresses, box↔boxes
    expanded = (toks | {t + "s" for t in toks} | {t + "es" for t in toks}
                | {t[:-1] for t in toks if t.endswith("s") and len(t) > 3}
                | {t[:-2] for t in toks if t.endswith("es") and len(t) > 4})
    scored: List[Tuple[TaxonomyNode, float]] = []
    nodes = _nodes()
    for handle, path_toks in _node_token_index().items():
        hits = expanded & path_toks
        if not hits:
            continue
        node = nodes[handle]
        leaf_toks = set(_tokens(node.name))
        leaf_hits = expanded & leaf_toks
        if not leaf_hits:
            continue  # a candidate must match the NODE'S OWN NAME, not just its ancestors'
        coverage = len(leaf_hits) / max(1, len(leaf_toks))
        score = 2.0 * len(leaf_hits) * coverage + len(hits) + node.depth * 0.1
        scored.append((node, score))
    scored.sort(key=lambda p: (-p[1], p[0].handle))
    return scored[: max(1, int(top_k))]


def _crosswalk(category_text: str) -> Optional[TaxonomyNode]:
    """Exact node-name match for an existing category string — merchant-declared data is
    high-trust, so it wins deterministically without a model call. Normalizes underscores
    and singular/plural ('hard_drive' → 'Hard Drives', 'laptop' → 'Laptops'). AMBIGUOUS
    names (multiple nodes named identically, e.g. bare 'Monitors') are NOT crosswalked —
    they go to the model path, which is the correct division of labor."""
    ct = str(category_text or "").strip().lower().replace("_", " ")
    if not ct:
        return None
    variants = {ct, ct + "s"}
    if ct.endswith("s") and len(ct) > 3:
        variants.add(ct[:-1])
    matches = [n for n in _nodes().values() if n.name.lower() in variants]
    return matches[0] if len(matches) == 1 else None


def _classifier_model() -> str:
    """CLASSIFIER_MODEL or the certified text default. Deliberately does NOT consult
    OLLAMA_SMALL_MODEL/OLLAMA_DEFAULT_MODEL: in real deployments those point at VISION
    models (qwen3-vl), which fail text-only generate — that chain is exactly how the
    2026-07-11 run resolved a VL model and read as 'model UNAVAILABLE'."""
    return os.getenv("CLASSIFIER_MODEL") or "qwen3:14b"


def _default_llm_fn(prompt: str, timeout: float) -> str:
    """Same local-Ollama call shape as llm_planner/semantic_turn_router. Failures are LOGGED —
    a cold model timing out on every call must read as 112 warnings in the run output, never
    as a silent all-lexical sweep (the mute-layer class; it happened on this module's first
    live run, 2026-07-11: 15s timeout < qwen3:14b cold-load → 112/112 fallback, zero errors
    shown). Callers warm the model first via warmup()."""
    try:
        import httpx
        url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = _classifier_model()
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
                   "options": {"temperature": 0, "num_predict": 128}}
        if "qwen3" in model.lower():
            payload["think"] = False
        r = httpx.post(f"{url}/api/generate", json=payload, timeout=max(2.0, float(timeout or 8.0)))
        data = r.json() or {}
        if r.status_code != 200 or data.get("error"):
            logger.warning("classifier model call failed: http=%s error=%s model=%s",
                           r.status_code, str(data.get("error"))[:120], model)
            return ""
        return str(data.get("response", "") or "")
    except Exception as exc:
        logger.warning("classifier model call failed: %s model=%s", repr(exc)[:120], _classifier_model())
        return ""


def warmup(*, timeout: float = 240.0) -> bool:
    """Load the classifier model once (cold load can exceed any sane per-item timeout) so the
    per-product calls run against a warm instance. Returns False when the model is unusable —
    the caller should SAY so and proceed lexical-only, not discover it 112 rows later."""
    out = _default_llm_fn('Return JSON: {"ok": true}\nJSON:', timeout)
    return bool(out.strip())


def _build_prompt(text: str, candidates: List[Tuple[TaxonomyNode, float]]) -> str:
    lines = "\n".join(f"  {n.handle} : {n.full_path}" for n, _ in candidates)
    return (
        "You are a product classifier. Pick the ONE taxonomy category that best fits this "
        "product, FROM THE CANDIDATE LIST ONLY.\n\n"
        f"PRODUCT: {str(text or '')[:300]}\n\n"
        f"CANDIDATES (handle : path):\n{lines}\n\n"
        "Rules: choose the most SPECIFIC candidate that truly matches; if several fit, prefer "
        "the deeper path; judge by what the product IS, not what it's used with (a laptop BAG "
        "is a bag, not a laptop).\n"
        'Return JSON: {"handle": "<one handle from the list>", "confidence": <0.0-1.0>}\n'
        "JSON:"
    )


def classify_text(text: str, *, existing_category: str = "",
                  llm_fn: Optional[LLMFn] = None, timeout: float = 30.0) -> Optional[Classification]:
    """Classify one product text. Returns None only when there is NO signal at all (no tokens,
    zero candidates) — every other path yields a proposal (model or lexical fallback)."""
    xw = _crosswalk(existing_category)
    if xw is not None:
        return Classification(sku="", node_handle=xw.handle, node_path=xw.full_path,
                              confidence=0.95, source="crosswalk")
    cands = candidate_nodes(text)
    # An AMBIGUOUS merchant category ('monitor', 'tablet') couldn't crosswalk, but it must
    # still SEED candidates — 'Tablet Computers' was crowded out of the top-K by Wi-Fi token
    # noise on the first live run, and the clamp means the model can never pick a node that
    # isn't offered. Union the hint's own candidates in, best score wins on dedup.
    if existing_category:
        merged: Dict[str, Tuple[TaxonomyNode, float]] = {n.handle: (n, s) for n, s in cands}
        for n, s in candidate_nodes(existing_category, top_k=5):
            if n.handle not in merged or s > merged[n.handle][1]:
                merged[n.handle] = (n, s)
        cands = sorted(merged.values(), key=lambda p: (-p[1], p[0].handle))[:TOP_K + 5]
    if not cands:
        return None
    allowed = {n.handle for n, _ in cands}
    fn = llm_fn or _default_llm_fn
    try:
        raw = fn(_build_prompt(text, cands), timeout)
        data = json.loads(raw) if raw else None
    except Exception:
        data = None
    if isinstance(data, dict):
        pick = str(data.get("handle") or "").strip()
        try:
            conf = max(0.0, min(1.0, float(data.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            conf = 0.0
        # THE CLAMP: the pick must come from the candidate list, with usable confidence
        if pick in allowed and conf >= MODEL_CONFIDENCE_FLOOR:
            node = get_node(pick)
            return Classification(sku="", node_handle=node.handle, node_path=node.full_path,
                                  confidence=conf, source="model",
                                  candidates=tuple(n.handle for n, _ in cands))
    best = cands[0][0]
    return Classification(sku="", node_handle=best.handle, node_path=best.full_path,
                          confidence=0.2, source="lexical_fallback",
                          candidates=tuple(n.handle for n, _ in cands))


def classify_catalog(db, *, tenant_id: str = "default", llm_fn: Optional[LLMFn] = None,
                     limit: Optional[int] = None, commit: bool = True,
                     mode: Optional[str] = None) -> Dict[str, Any]:
    """Classify every variant the read-model facade serves and write status='proposed' rows.
    Product text = title + brand + specs keys (whatever exists). Returns a report; the
    approval step (T4) is deliberately separate — nothing here changes what sells."""
    from src.app.services.catalog_read_model import search_variants
    views = search_variants(db, limit=int(limit or 500), mode=mode)
    report: Dict[str, Any] = {"release": PINNED_RELEASE, "total": len(views), "classified": 0,
                              "by_source": {}, "low_confidence": [], "unclassifiable": [],
                              "rows": []}
    for v in views:
        # Categorical spec VALUES only — dumping the raw spec dict floods the tokens with
        # schema noise ('display inches', 'storage gb', 'full hd') that buried the true
        # category on this module's first live run. And the legacy specs JSON turns out to
        # carry a clean `category` string on 90/114 demo products the empty DB column never
        # had — merchant-grade crosswalk input.
        cat_hint = str((v.specs or {}).get("category") or (v.specs or {}).get("type")
                       or "").replace("_", " ")
        text = " ".join(filter(None, [v.title, v.brand, v.product_type, cat_hint]))
        c = classify_text(text, existing_category=v.category or v.product_type or cat_hint,
                          llm_fn=llm_fn)
        if c is None:
            report["unclassifiable"].append(v.sku)
            continue
        if upsert_classification(db, sku=v.sku, node_handle=c.node_handle, source=c.source,
                                 confidence=c.confidence, status="proposed", tenant_id=tenant_id):
            report["classified"] += 1
            report["by_source"][c.source] = report["by_source"].get(c.source, 0) + 1
            if c.confidence < 0.5:
                report["low_confidence"].append({"sku": v.sku, "node": c.node_handle,
                                                 "conf": c.confidence})
            report["rows"].append({"sku": v.sku, "title": v.title[:60], "node": c.node_handle,
                                   "path": c.node_path, "conf": round(c.confidence, 2),
                                   "source": c.source})
    if commit:
        try:
            db.commit()
        except Exception as exc:
            logger.debug("classify_catalog commit failed: %s", exc)
    return report
