from __future__ import annotations

"""Query decomposition & intent routing (roadmap WS2.1 / WS2.3 / WS2.4).

Turns a raw shopper query into a structured ``QueryPlan`` so the recommend
pipeline can:

  * route comparison/knowledge questions to a *conceptual* answer path instead
    of returning a blank product list (WS2.2);
  * honour EVERY intent in a multi-intent query ("gaming + video editing +
    portable") rather than letting one persona win (WS2.3);
  * convert natural-language constraints ("240fps", "portable", "32GB") into
    HARD filters the retriever can enforce (WS2.4 → WS3.2).

Pure functions, no LLM, no I/O — fast and unit-testable. Builds on
``query_classifier`` for category / budget-question detection.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.services.query_classifier import (
    coarse_product_category,
    is_budget_question,
    is_followup_explain_query,
)

# ── Intent constants ──────────────────────────────────────────────────────────
INTENT_PRODUCT_SEARCH = "product_search"
INTENT_COMPARISON = "comparison"
INTENT_KNOWLEDGE = "knowledge"
INTENT_MULTI = "recommendation_multi"
INTENT_SUPPORT = "support"

_SUPPORT_RE = re.compile(
    r"\b(warranty|return|refund|broken|damaged|cracked|shattered|repair|"
    r"replacement|faulty|not working|dead pixel|bsod|blue screen|stop code)\b",
    re.IGNORECASE,
)

# Comparison: two named things being weighed against each other.
_COMPARISON_RE = re.compile(
    r"\b(vs\.?|versus|compare|comparison|difference between|which is better|"
    r"which one is better|better than|pros and cons of)\b",
    re.IGNORECASE,
)

# Knowledge: conceptual question answerable WITHOUT a product list.
_KNOWLEDGE_RE = re.compile(
    r"(what'?s the difference|what is the difference|"
    r"\bdo i (really )?need\b|\bhow much (ram|vram|storage|memory)\b|"
    r"\bis (an? )?\w+ (enough|better|worth)\b|\bwhat does .+ mean\b|"
    r"\bwhich (gpu|cpu|processor|ram|ssd|screen|panel) (is|should)\b|"
    r"\bwhat'?s? (better|the best) .* (for|between)\b)",
    re.IGNORECASE,
)

# Listy phrasing that forces product_search even if "what/which" appears.
_PRODUCT_LISTY_RE = re.compile(
    r"\b(show me|find me|recommend|suggest|looking for|i want|i need a|"
    r"best .* (laptop|pc|desktop|phone|tablet|monitor|headset)|"
    r"good .* (laptop|pc|desktop|gaming|for gaming))\b",
    re.IGNORECASE,
)

# ── Use cases (multi-intent detection) ────────────────────────────────────────
_USE_CASE_PATTERNS: Dict[str, re.Pattern] = {
    "gaming": re.compile(r"\b(gaming|gamer|esports|fps|valorant|fortnite|cyberpunk|aaa|triple ?a|ray ?tracing)\b", re.I),
    "video_editing": re.compile(r"\b(video edit\w*|premiere|davinci|resolve|4k edit\w*|content creat\w*|youtub\w*|streaming|render\w*)\b", re.I),
    "programming": re.compile(r"\b(coding|programming|developer|software dev|docker|compile|android studio|xcode|ide)\b", re.I),
    "ml_ai": re.compile(r"\b(machine learning|deep learning|ai training|train\w* (a )?model|llm|cuda|tensor|pytorch|data science)\b", re.I),
    "cad_3d": re.compile(r"\b(cad|autocad|solidworks|revit|3d model\w*|blender|rendering|engineering student)\b", re.I),
    "photo": re.compile(r"\b(photo edit\w*|photoshop|lightroom|raw photo)\b", re.I),
    "office": re.compile(r"\b(office work|excel|spreadsheet|word processing|email|business use|productivity)\b", re.I),
    "study": re.compile(r"\b(student|university|college|study|school work|note ?taking)\b", re.I),
}

# Use cases that imply a dedicated GPU.
_DGPU_USE_CASES = {"gaming", "video_editing", "ml_ai", "cad_3d"}

# Portability phrasing.
_PORTABLE_RE = re.compile(r"\b(portable|lightweight|light ?weight|thin and light|ultrabook|ultra ?portable|travel|carry around|commut\w*)\b", re.I)


@dataclass
class QueryPlan:
    query: str
    intent: str
    use_cases: List[str] = field(default_factory=list)
    is_multi_intent: bool = False
    needs_dedicated_gpu: bool = False
    hard_constraints: Dict[str, Any] = field(default_factory=dict)
    comparison_subjects: List[str] = field(default_factory=list)
    category: Optional[str] = None
    answer_without_products: bool = False  # comparison/knowledge → conceptual answer ok

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "use_cases": self.use_cases,
            "is_multi_intent": self.is_multi_intent,
            "needs_dedicated_gpu": self.needs_dedicated_gpu,
            "hard_constraints": self.hard_constraints,
            "comparison_subjects": self.comparison_subjects,
            "category": self.category,
            "answer_without_products": self.answer_without_products,
        }


def _extract_comparison_subjects(q: str) -> List[str]:
    """Pull the two things being compared, e.g. 'RTX 4060' & 'RTX 4070'."""
    ql = q
    subjects: List[str] = []
    # GPU model pairs: "RTX 4060 and 4070", "4060 vs 4070"
    gpus = re.findall(r"\b(?:rtx|gtx|rx)?\s*\b(\d{3,4})\b", ql, re.I)
    # "between X and Y"
    m = re.search(r"between\s+(.+?)\s+and\s+(.+?)(?:\?|$|\sfor\b|\sgaming\b)", ql, re.I)
    if m:
        subjects = [m.group(1).strip(), m.group(2).strip()]
    else:
        m = re.search(r"(.+?)\s+(?:vs\.?|versus|or)\s+(.+?)(?:\?|$|\sfor\b)", ql, re.I)
        if m:
            subjects = [m.group(1).strip(), m.group(2).strip()]
    # Trim leading filler
    cleaned = []
    for s in subjects:
        s = re.sub(r"^(the|a|an|what'?s|difference|is|which)\s+", "", s, flags=re.I).strip()
        if s and len(s) < 60:
            cleaned.append(s)
    return cleaned[:2]


def _extract_hard_constraints(q: str, use_cases: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    ql = q.lower()
    # Refresh rate: "240fps", "240 hz", "144 frames"
    m = re.search(r"\b(60|75|90|120|144|165|240|360)\s*(hz|fps|frames?)\b", ql)
    if m:
        out["refresh_hz_min"] = int(m.group(1))
    # Portability → weight cap
    if _PORTABLE_RE.search(ql):
        out["weight_kg_max"] = 2.0
    m = re.search(r"\bunder\s*([0-9](?:\.[0-9])?)\s*kg\b", ql)
    if m:
        out["weight_kg_max"] = float(m.group(1))
    # Explicit GPU model hint
    m = re.search(r"\brtx\s*(\d{3,4})\b", ql)
    if m:
        out["gpu_model_hint"] = f"rtx {m.group(1)}"
    # RAM
    m = re.search(r"\b(8|16|24|32|64)\s*gb\b", ql)
    if m:
        out["ram_gb_min"] = int(m.group(1))
    # Storage in TB
    m = re.search(r"\b([1248])\s*tb\b", ql)
    if m:
        out["storage_gb_min"] = int(m.group(1)) * 1024
    # Dedicated GPU requirement from use cases
    if any(uc in _DGPU_USE_CASES for uc in use_cases):
        out["must_have_dedicated_gpu"] = True
    # Esports competitive tier → high refresh implied if not stated
    if "gaming" in use_cases and re.search(r"\b(esports|competitive|valorant|cs2|counter ?strike|240)\b", ql):
        out.setdefault("refresh_hz_min", 144)
    return out


def decompose(query: Optional[str], *, has_image: bool = False) -> QueryPlan:
    """Decompose a raw query into a structured plan. Never raises."""
    q = str(query or "").strip()
    plan = QueryPlan(query=q, intent=INTENT_PRODUCT_SEARCH)
    if not q:
        return plan
    try:
        plan.category = coarse_product_category(q)
        plan.use_cases = [uc for uc, pat in _USE_CASE_PATTERNS.items() if pat.search(q)]
        plan.needs_dedicated_gpu = any(uc in _DGPU_USE_CASES for uc in plan.use_cases)
        plan.hard_constraints = _extract_hard_constraints(q, plan.use_cases)

        listy = bool(_PRODUCT_LISTY_RE.search(q))
        # 1. Support
        if _SUPPORT_RE.search(q):
            plan.intent = INTENT_SUPPORT
        # 2. Comparison — two named subjects weighed against each other
        elif _COMPARISON_RE.search(q) and not listy:
            plan.intent = INTENT_COMPARISON
            plan.comparison_subjects = _extract_comparison_subjects(q)
            plan.answer_without_products = True
        # 3. Knowledge — conceptual question, not a listy product request
        elif _KNOWLEDGE_RE.search(q) and not listy and not is_budget_question(q):
            plan.intent = INTENT_KNOWLEDGE
            plan.answer_without_products = True
        # 4. Multi-intent product search
        elif len(plan.use_cases) >= 2:
            plan.intent = INTENT_MULTI
            plan.is_multi_intent = True
        else:
            plan.intent = INTENT_PRODUCT_SEARCH
    except Exception:
        # Fail safe: behave like a plain product search.
        plan.intent = INTENT_PRODUCT_SEARCH
    return plan
