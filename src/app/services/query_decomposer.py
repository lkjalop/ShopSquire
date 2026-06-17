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
    "study": re.compile(r"\b(student|university|uni|college|study|school work|note ?taking)\b", re.I),
}

# Use cases that imply a dedicated GPU.
_DGPU_USE_CASES = {"gaming", "video_editing", "ml_ai", "cad_3d"}

# Portability phrasing.
_PORTABLE_RE = re.compile(r"\b(portable|lightweight|light ?weight|thin and light|ultrabook|ultra ?portable|travel|carry around|commut\w*)\b", re.I)


@dataclass
class SubQuestion:
    """One atomic ask inside a compound query ("…uni work? is $1400 enough?")."""
    text: str
    intent: str
    use_cases: List[str] = field(default_factory=list)
    hard_constraints: Dict[str, Any] = field(default_factory=dict)
    comparison_subjects: List[str] = field(default_factory=list)
    answer_without_products: bool = False
    is_budget_question: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "intent": self.intent,
            "use_cases": self.use_cases,
            "hard_constraints": self.hard_constraints,
            "comparison_subjects": self.comparison_subjects,
            "answer_without_products": self.answer_without_products,
            "is_budget_question": self.is_budget_question,
        }


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
    sub_questions: List[SubQuestion] = field(default_factory=list)  # compound decomposition
    is_compound: bool = False  # ≥2 distinct sub-questions

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
            "is_compound": self.is_compound,
            "sub_questions": [sq.to_dict() for sq in self.sub_questions],
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


def _classify_clause(q: str) -> SubQuestion:
    """Classify ONE clause/segment into a SubQuestion (intent + extracted bits).
    Shared by the top-level plan and each compound sub-question so they agree."""
    use_cases = [uc for uc, pat in _USE_CASE_PATTERNS.items() if pat.search(q)]
    hc = _extract_hard_constraints(q, use_cases)
    budget_q = is_budget_question(q)
    listy = bool(_PRODUCT_LISTY_RE.search(q))
    sq = SubQuestion(text=q, intent=INTENT_PRODUCT_SEARCH, use_cases=use_cases,
                     hard_constraints=hc, is_budget_question=budget_q)
    if _SUPPORT_RE.search(q):
        sq.intent = INTENT_SUPPORT
    elif _COMPARISON_RE.search(q) and not listy:
        sq.intent = INTENT_COMPARISON
        sq.comparison_subjects = _extract_comparison_subjects(q)
        sq.answer_without_products = True
    elif _KNOWLEDGE_RE.search(q) and not listy and not budget_q:
        sq.intent = INTENT_KNOWLEDGE
        sq.answer_without_products = True
    elif len(use_cases) >= 2:
        sq.intent = INTENT_MULTI
    else:
        sq.intent = INTENT_PRODUCT_SEARCH
    return sq


# A trailing conjunct is its OWN clause (worth splitting on " and "/" also ") only when
# it stands alone as a question/request — a budget-sufficiency, knowledge, or comparison
# question, OR a clause that OPENS with an interrogative/listy marker ("which laptop…",
# "show me…"). This splits genuine compounds while NOT fragmenting single product
# requests ("laptop for gaming and under 1500") or use-case lists ("gaming and video
# editing") whose conjuncts don't open with such a marker.
_CLAUSE_START_RE = re.compile(
    r"^(which|what'?s?|how|is|are|do|does|can|should|would|"
    r"show me|find me|recommend|suggest|i need|i want|looking for)\b",
    re.IGNORECASE,
)


def _is_independent_clause(seg: str) -> bool:
    s = seg.strip()
    if not s:
        return False
    if is_budget_question(s):
        return True
    if len(s.split()) < 2:
        return False
    if _KNOWLEDGE_RE.search(s) or _COMPARISON_RE.search(s):
        return True
    return bool(_CLAUSE_START_RE.match(s) and len(s.split()) >= 3)


def _segment_query(q: str) -> List[str]:
    """Split a compound query into atomic clauses. High-precision: splits on strong
    boundaries (? ; sentence .) always, and on ' and '/' also '/' plus only when the
    trailing conjunct is an independent question of a different shape."""
    # 1) strong boundaries
    raw = [p for p in re.split(r"[?;]+|(?<=[a-z0-9])\.\s+", q) if p and p.strip()]
    segments: List[str] = []
    for part in raw:
        part = part.strip()
        # 2) conservative conjunction split (left-to-right, one level)
        pieces = re.split(r"\s+(?:and also|and|also|plus|,\s*and|,\s*also)\s+", part, flags=re.IGNORECASE)
        if len(pieces) >= 2 and any(_is_independent_clause(pc) for pc in pieces[1:]):
            # keep the head with everything up to the first independent conjunct merged,
            # then each independent conjunct as its own segment.
            head = pieces[0].strip()
            buf = head
            for pc in pieces[1:]:
                if _is_independent_clause(pc):
                    if buf.strip():
                        segments.append(buf.strip())
                    buf = pc.strip()
                else:
                    buf = (buf + " and " + pc).strip()
            if buf.strip():
                segments.append(buf.strip())
        else:
            segments.append(part)
    # 3) clean + dedup
    out: List[str] = []
    seen = set()
    for s in segments:
        s2 = s.strip(" ,.")
        if not s2:
            continue
        if len(s2.split()) < 2 and not is_budget_question(s2):
            continue
        key = s2.lower()
        if key not in seen:
            seen.add(key)
            out.append(s2)
    return out


def decompose(query: Optional[str], *, has_image: bool = False) -> QueryPlan:
    """Decompose a raw query into a structured plan, including compound sub-questions.
    Never raises. The top-level fields stay backward-compatible (classified from the
    WHOLE query); ``sub_questions``/``is_compound`` are additive."""
    q = str(query or "").strip()
    plan = QueryPlan(query=q, intent=INTENT_PRODUCT_SEARCH)
    if not q:
        return plan
    try:
        plan.category = coarse_product_category(q)
        # Top-level classification (whole query) — preserves existing behaviour.
        top = _classify_clause(q)
        plan.intent = top.intent
        plan.use_cases = top.use_cases
        plan.needs_dedicated_gpu = any(uc in _DGPU_USE_CASES for uc in plan.use_cases)
        plan.hard_constraints = top.hard_constraints
        plan.comparison_subjects = top.comparison_subjects
        plan.answer_without_products = top.answer_without_products
        if plan.intent == INTENT_MULTI:
            plan.is_multi_intent = True

        # Compound decomposition — split into sub-questions and classify each.
        segments = _segment_query(q)
        if len(segments) >= 2:
            subs = [_classify_clause(s) for s in segments]
            distinct_intents = {s.intent for s in subs}
            # Treat as compound only when the split produced genuinely different asks
            # (e.g. product_search + budget question, or knowledge + product_search) —
            # not two near-identical product clauses.
            has_qna = any(s.answer_without_products or s.is_budget_question for s in subs)
            if len(distinct_intents) >= 2 or has_qna:
                plan.sub_questions = subs
                plan.is_compound = True
                plan.is_multi_intent = True
    except Exception:
        # Fail safe: behave like a plain product search.
        plan.intent = INTENT_PRODUCT_SEARCH
    return plan
