from __future__ import annotations

import json
import os
import re
import time
import uuid
import math
import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text, bindparam

from src.app.services.semantic_search import SemanticService
from src.app.services.embeddings import VectorStoreEmbeddings
from src.app.repositories.embeddings import search_products_by_embedding

from src.app.models.db import db_session
from src.app.repositories.catalog import CatalogRepository
from src.app.observability.health import dependency_health_snapshot
from src.app.observability.tracing import get_tracer
from src.app.deps import scrub_pii, security_sanitize, hash_uid
from src.app.services.policy_evaluator import PolicyEvaluator
from src.app.services.decision_log import log_decision as central_log_decision
from src.app.services.recommendation_identity_graph import linked_uid_hashes
from src.app.services.recommendation_als import load_precomputed_cf_scores
from src.app.services.recommendation_bandit import choose_recommendation_arm

_USE_CASE_KB: dict | None = None
_USE_CASE_KB_LOADED: bool = False


def _load_use_case_kb() -> dict:
    global _USE_CASE_KB, _USE_CASE_KB_LOADED
    if _USE_CASE_KB_LOADED:
        return _USE_CASE_KB or {}
    try:
        _kb_path = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "use_case_kb.json")
        )
        with open(_kb_path, "r", encoding="utf-8") as _f:
            _USE_CASE_KB = json.load(_f)
    except Exception:
        _USE_CASE_KB = {}
    _USE_CASE_KB_LOADED = True
    return _USE_CASE_KB or {}


# ── Seasonal context auto-injection ──────────────────────────────────────────
_FEATURE_FLAGS_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "feature_flags.json")


def get_active_seasonal_boosts() -> Tuple[Optional[Dict[str, float]], Optional[str]]:
    """Read the SEASONAL_CONTEXT block from feature_flags.json.

    Returns ``(boosts_dict, season_name)`` if a season is active, else ``(None, None)``.
    Pure config read — no DB or network I/O.
    """
    try:
        path = os.path.normpath(_FEATURE_FLAGS_PATH)
        if not os.path.isfile(path):
            return None, None
        with open(path, "r", encoding="utf-8") as f:
            flags = json.load(f)
        sc = flags.get("SEASONAL_CONTEXT") or {}
        active = sc.get("active_season")
        if not active:
            return None, None
        boosts = (sc.get("boosts") or {}).get(active)
        if not boosts or not isinstance(boosts, dict):
            return None, None
        return boosts, str(active)
    except Exception:
        return None, None


PROMPT_CONTROL = {
    "system": (
        "You are a product recommendation reranker. "
        "You must ONLY reorder the provided candidates. "
        "Do not invent or suggest any SKU not in the candidate list. "
        "If a constraint cannot be met, explain briefly without fabricating products."
    ),
    "format": (
        "Return JSON with keys: ranked_skus (array), rationale (string). "
        "ranked_skus must be a permutation of input candidate SKUs."
    ),
}


# ── Budget tier classification ────────────────────────────────────────────────
def classify_budget_tier(budget_max: Optional[int]) -> Tuple[str, List[str]]:
    """Classify a budget ceiling into a tier label and advisory warning tags.

    Returns ``(tier_label, warning_tags)`` — a pure function with no I/O.

    Tiers
    -----
    accessories_only  < $100   — can't buy a laptop; redirect to accessories
    very_low          $100–349 — used/refurb only; warn about new laptop risk
    entry             $350–699 — entry-level new or solid refurb midrange
    mid               $700–999 — sweet-spot for most users
    premium           $1000–1999 — premium performance / longevity
    high_performance  $2000–3499 — creator / workstation / 4-year machine
    workstation_pro   $3500+    — niche; flag potential overspend
    """
    if budget_max is None:
        return "unknown", []
    b = int(budget_max)
    if b <= 99:
        return "accessories_only", ["budget_too_low_for_laptop"]
    if b <= 349:
        return "very_low", ["refurb_recommended", "budget_too_low_for_new_laptop"]
    if b <= 699:
        return "entry", []
    if b <= 999:
        return "mid", []
    if b <= 1999:
        return "premium", []
    if b <= 3499:
        return "high_performance", []
    return "workstation_pro", ["overspend_risk_check"]


_WARRANTY_HIGH_RISK_USE_CASES: frozenset[str] = frozenset({
    "gaming_aaa_heavy", "gaming_competitive", "content_creator",
    "engineering_student", "data_science_student", "ai_ml_workstation",
})


def classify_warranty_candidate(
    budget_max: Optional[int],
    use_case_key: Optional[str] = None,
) -> str:
    """Return warranty upsell priority tag: 'warranty_candidate_high', 'warranty_candidate_low',
    or 'warranty_candidate_neutral'.

    Push warranty when device is expensive (>=$1500) or when use-case involves
    heavy sustained load and budget is mid-range+.  Avoid pushing for low-budget
    purchases where it crowds out core value.
    """
    if budget_max is not None and budget_max >= 1500:
        return "warranty_candidate_high"
    if (
        use_case_key
        and use_case_key in _WARRANTY_HIGH_RISK_USE_CASES
        and budget_max is not None
        and budget_max >= 900
    ):
        return "warranty_candidate_high"
    if budget_max is not None and budget_max < 700:
        return "warranty_candidate_low"
    return "warranty_candidate_neutral"



class RecommendationService:
    def __init__(self, session=None):
        # Optional injected SQLAlchemy Session for request-bound engine usage.
        self.catalog = CatalogRepository(session=session)
        self.tracer = get_tracer("recommendation-service")
        # Lightweight semantic service (embeddings) + small LRU cache for frequent products
        self._emb = SemanticService()
        self._emb_cache: Dict[str, Dict[str, float]] = {}
        self._emb_cache_order: List[str] = []
        self._emb_cache_max = 256
        self._intent_phrases = {
            "product_discovery_open_ended": [
                "i need something for",
                "not sure what to buy",
                "help me choose",
                "recommend something",
                "what should i get",
            ],
            "use_case_match": [
                "gaming laptop",
                "business laptop",
                "creative work",
                "for school",
                "for travel",
            ],
            "gift_recommendation": ["gift", "present", "for my friend", "for my kid"],
            "beginner_vs_pro": ["beginner", "entry level", "pro model", "professional"],
            "bundle_recommendation": ["bundle", "with monitor", "with dock", "setup"],
            "compatibility_check": ["work with ps5", "compatible with", "works with iphone"],
            "sizing_fit_advice": ["size chart", "fit", "sizing", "what size"],
            "accessory_needed": ["what cable", "which adapter", "what charger", "accessory"],
            "tradeoff_explainer": ["oled vs ips", "difference between", "trade off"],
            "feature_education": ["what is dlss", "what is esim", "explain"],
            "price_range": ["between $", "from $", "price range"],
            "budget_soft": ["around $", "about $", "roughly $"],
            "budget_hard_cap": ["max $", "under $", "no more than"],
            "price_floor": ["at least $", "minimum $", "no less than"],
            "value_for_money": ["best value", "bang for buck", "worth it"],
            "spec_minimums": ["at least 16gb ram", "minimum 1tb", "16gb or more"],
            "spec_exclusions": ["no amd", "without radeon", "no refurbished"],
            "brand_preference_positive": ["i like dell", "prefer lenovo", "only apple"],
            "brand_avoidance": ["no apple", "avoid acer", "not samsung"],
            "condition_filter": ["new only", "used", "refurbished"],
            "availability_filter": ["in stock", "available today"],
            "shipping_speed_filter": ["deliver by", "next day", "same day"],
            "local_pickup_filter": ["pickup", "pick up"],
            "region_voltage_plug_filter": ["us plug", "uk plug", "eu plug", "voltage"],
            "color_style_filter": ["black", "silver", "color", "style"],
            "sustainability_filter": ["energy star", "eco", "sustainable"],
            "compare_two_specific": ["compare x vs y", "vs", "versus"],
            "compare_multiple_shortlist": ["compare these", "compare shortlist"],
            "pros_cons_request": ["pros and cons", "advantages and disadvantages"],
            "which_should_i_buy": ["which should i buy", "help me decide"],
            "equivalent_alternative": ["similar to", "alternative to"],
            "upgrade_recommendation": ["upgrade from", "better than my"],
            "downgrade_recommendation": ["cheaper version", "budget version"],
            "new_release_vs_last_gen": ["new vs last gen", "latest vs previous"],
            "best_overall_in_category": ["best overall", "top rated"],
            "best_for_specific_metric": ["best battery", "best camera", "quietest"],
            "deal_finder": ["deal", "discount", "on sale"],
            "price_drop_watch": ["price drop", "watch price"],
            "coupon_applicability": ["coupon", "promo code"],
            "price_match_policy": ["price match"],
            "bulk_discount_inquiry": ["bulk discount", "volume pricing"],
            "procurement_intent": ["purchase order", "invoice", "net-30", "rfp", "quote", "site license"],
            "order_status": ["where is my order", "track order", "order status"],
            "return_request": ["return", "refund", "exchange"],
            "warranty_intent": ["warranty", "extended warranty"],
            "warranty_cost_inquiry": ["warranty cost", "extended warranty"],
            "total_cost_of_ownership": ["total cost", "running cost"],
            "authenticity_concern_product": ["authentic", "real product", "genuine"],
            "seller_trust_check": ["trusted seller", "seller rating"],
            "review_summary_request": ["review summary", "what do reviews say"],
            "review_manipulation_suspicion": ["fake reviews", "review manipulation"],
            "counterfeit_signal_report": ["counterfeit", "fake product"],
            "safety_recall_check": ["recall", "safety notice"],
            "compliance_check": ["ce", "fcc", "ul certified"],
            "age_restricted_flow": ["age restricted", "18+", "21+"],
            "order_issue_report": ["wrong item", "damaged", "missing parts"],
            "policy_eligibility_check": ["return policy", "warranty policy", "eligible for return"],
            "suspicious_request": ["bypass", "jailbreak", "ignore policy"],
        }
        self._use_case_phrases = {
            "ai_ml_workstation": [
                "ai engineering",
                "ai engineer",
                "machine learning",
                "ml engineering",
                "deep learning",
                "data science",
                "llm",
                "model training",
                "pytorch",
                "tensorflow",
                "cuda",
                "neural",
                # First-turn software signals — catches "matlab", "jupyter", etc.
                "matlab",
                "jupyter",
                "numpy",
                "pandas",
                "scikit",
                "transformers",
                "hugging face",
                "gradient descent",
                "gpu training",
                "fine-tuning",
                "inference",
            ],
            "engineering_student": [
                "autocad",
                "solidworks",
                "ansys",
                "catia",
                "fusion 360",
                "civil engineering",
                "mechanical engineering",
                "electrical engineering",
                "architecture student",
                "3d cad",
            ],
            "software_development": [
                "developer",
                "software engineering",
                "coding",
                "programming",
                "vs code",
                "visual studio",
                "intellij",
                "compile",
                "docker",
                "kubernetes",
                "git",
                "linux dev",
                "backend dev",
                "frontend dev",
            ],
            "student": [
                "university",
                "college",
                "student",
                "school",
                "campus",
                "grad school",
                "thesis",
                "dissertation",
                "lecture notes",
                "essay writing",
            ],
            "business": [
                "business",
                "office",
                "corporate",
                "enterprise",
                "work laptop",
                "microsoft teams",
                "zoom calls",
                "excel",
                "powerpoint",
                "salesforce",
            ],
            "gaming": [
                "gaming",
                "rtx",
                "geforce",
                "esports",
                "fps",
                "game",
                "play games",
                "high refresh",
                "144hz",
                "165hz",
                "240hz",
            ],
            "content_creation": [
                "video editing",
                "creator",
                "content creation",
                "adobe",
                "photoshop",
                "premiere",
                "3d",
                "rendering",
                "cad",
                "blender",
                "davinci resolve",
                "final cut",
                "after effects",
                "illustration",
                "graphic design",
                "color grading",
            ],
            "mobile": [
                "travel",
                "on the go",
                "battery",
                "lightweight",
                "thin",
                "commute",
                "portable",
                "ultrabook",
            ],
        }

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").lower()).strip()

    def _apply_multilingual_normalization(self, text: str) -> Tuple[str, str]:
        normalized = self._normalize_text(text)
        locale = "en"
        replacements = {
            "es": {
                "portatil": "laptop",
                "ordenador": "computer",
                "precio": "price",
                "presupuesto": "budget",
                "escuela": "school",
                "universidad": "university",
                "trabajo": "work",
                "juegos": "gaming",
            },
            "fr": {
                "ordinateur portable": "laptop",
                "prix": "price",
                "budget": "budget",
                "ecole": "school",
                "universite": "university",
                "travail": "work",
                "jeu": "gaming",
            },
        }
        es_markers = ("hola", "gracias", "portatil", "ordenador", "precio", "presupuesto")
        fr_markers = ("bonjour", "merci", "ordinateur", "prix", "universite", "travail")
        if any(m in normalized for m in es_markers):
            locale = "es"
        elif any(m in normalized for m in fr_markers):
            locale = "fr"
        repl = replacements.get(locale, {})
        for src, dst in repl.items():
            normalized = normalized.replace(src, dst)
        return normalized, locale

    def _extract_lifecycle_signal(self, text: str) -> str | None:
        t = self._normalize_text(text)
        if any(k in t for k in ("new year", "new-year", "january")):
            return "new_year_refresh"
        if any(k in t for k in ("back to school", "school", "semester", "campus")):
            return "back_to_school"
        if any(k in t for k in ("university", "college", "student")):
            return "university_term"
        if any(k in t for k in ("work", "office", "business", "corporate")):
            return "work_upgrade"
        return None

    def _parse_number_with_suffix(self, s: str) -> Optional[float]:
        # handles 1.2k, 2k, 1m, 1,200.50, etc.
        try:
            s = s.replace(",", "").lower().strip()
            mult = 1.0
            if s.endswith("k"):
                mult = 1_000.0
                s = s[:-1]
            elif s.endswith("m"):
                mult = 1_000_000.0
                s = s[:-1]
            return float(s) * mult
        except Exception:
            return None

    def _extract_price_range(self, text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        budget_min = None
        budget_max = None
        budget = None
        # Remove obvious PII-like tokens before numeric parsing so IDs/SSNs
        # cannot contaminate budget extraction.
        t = scrub_pii(text or "")
        # Remove storage/ram size mentions so they don't get misread as prices
        t = re.sub(r"\b\d+(?:\.\d+)?\s*(tb|gb)\b(?:\s*(ssd|storage|disk|hdd|ram))?", " ", t, flags=re.IGNORECASE)
        # Remove typical order/reference identifiers that may look numeric.
        t = re.sub(r"\b[a-z]{1,4}[-_]\d{3,}(?:[-_]\d{2,})+\b", " ", t, flags=re.IGNORECASE)
        # Patterns capturing ranges like "$1k-$2k", "between $100 and $200", "under $500"
        range_patterns = [
            r"between\s*\$?([\d\.,kKmM]+)\s*(?:and|to|-)\s*\$?([\d\.,kKmM]+)",
            r"\$?([\d\.,kKmM]+)\s*(?:-|to)\s*\$?([\d\.,kKmM]+)",
            r"from\s*\$?([\d\.,kKmM]+)\s*to\s*\$?([\d\.,kKmM]+)",
        ]
        for pat in range_patterns:
            m = re.search(pat, t)
            if m:
                a = self._parse_number_with_suffix(m.group(1))
                b = self._parse_number_with_suffix(m.group(2))
                if a is not None and b is not None:
                    a_i = int(a)
                    b_i = int(b)
                    budget_min, budget_max = (a_i, b_i) if a_i <= b_i else (b_i, a_i)
                    break
        if budget_min is None and budget_max is None:
            # look for single-value budget mentions: "under $500", "below 1000", or standalone $1000.
            # A trailing spec/measurement unit means the number is a SPEC, not a budget — "under 2 kg"
            # / "under 2kg" / "under 16 gb" must NOT become $2 / $2000 / $16 (live Tier-0 finding).
            _unit_guard = (r"(?!\s*(?:kg|kgs|lb|lbs|g|gb|tb|mb|kb|hz|ghz|mhz|khz|fps|inch|inches|"
                           r"cm|mm|w|watts|wh|mah|mp|cores?|nits|ppi|dpi)\b)")
            m = re.search(r"(?:under|below|less than)\s*\$?([\d\.,]+[kKmM]?)" + _unit_guard, t)
            if m:
                val = self._parse_number_with_suffix(m.group(1))
                if val is not None:
                    budget_max = int(val)
            else:
                # Prefer explicit currency first.
                for token in re.findall(r"\$[\d\.,]+[kKmM]?", t):
                    tok = token.strip().lstrip("$")
                    val = self._parse_number_with_suffix(tok)
                    if val is not None:
                        budget = int(val)
                        break
                # Then allow values only when tied to budget-like language.
                if budget is None:
                    m2 = re.search(
                        r"(?:budget|around|about|roughly|max(?:imum)?|cap|price)\D{0,12}([\d\.,]+[kKmM]?)",
                        t,
                        flags=re.IGNORECASE,
                    )
                    if m2:
                        val = self._parse_number_with_suffix(m2.group(1))
                        if val is not None:
                            budget = int(val)
        # Sane-budget floor: drop nonsensical sub-$50 values (e.g. a "$2" misread from "2 kg") and
        # absurd highs — matches the decomposer's band so all budget sources agree.
        def _sane(v):
            return v if (isinstance(v, (int, float)) and 50 <= v <= 1_000_000) else None
        return _sane(budget_min), _sane(budget_max), _sane(budget)

    def _extract_budget_delta(self, text: str) -> Optional[int]:
        """Extract relative budget updates like:
        - "widen budget by 600"
        - "increase budget by $200-$400"
        - "reduce budget by 300"
        Returns signed integer delta (positive/negative) or None.
        """
        t = scrub_pii(text or "")
        if not t:
            return None
        t_low = self._normalize_text(t)
        if "budget" not in t_low and "price range" not in t_low:
            return None

        dir_up = bool(re.search(r"\b(widen|increase|raise|bump|expand|broaden|extend|loosen)\b", t_low))
        dir_down = bool(re.search(r"\b(reduce|decrease|lower|tighten|cut|shrink)\b", t_low))
        if not dir_up and not dir_down:
            return None
        direction = 1 if dir_up and not dir_down else -1 if dir_down and not dir_up else 0
        if direction == 0:
            return None

        delta_val: Optional[int] = None
        m_rng = re.search(r"\bby\b\s*\$?([\d\.,kKmM]+)\s*(?:-|to)\s*\$?([\d\.,kKmM]+)", t_low)
        if m_rng:
            a = self._parse_number_with_suffix(m_rng.group(1))
            b = self._parse_number_with_suffix(m_rng.group(2))
            if a is not None and b is not None:
                delta_val = int(max(a, b))
        if delta_val is None:
            m = re.search(r"\bby\b\s*\$?([\d\.,kKmM]+)", t_low)
            if m:
                v = self._parse_number_with_suffix(m.group(1))
                if v is not None:
                    delta_val = int(v)
        if delta_val is None or delta_val <= 0:
            return None
        return int(direction * delta_val)

    def _extract_specs(self, text: str) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}
        ram_match = re.search(r"(\d+)\s*gb\s*ram", text)
        if ram_match:
            slots["ram_gb_min"] = int(ram_match.group(1))
        storage_match = re.search(r"(\d+)\s*(tb|gb)\s*(ssd|storage|disk|hdd)", text)
        if storage_match:
            val = int(storage_match.group(1))
            unit = storage_match.group(2)
            slots["storage_gb_min"] = val * 1024 if unit == "tb" else val
        if any(k in text for k in ("rtx", "nvidia", "gpu")):
            slots["gpu_class"] = "discrete"
        if any(k in text for k in ("oled", "ips")):
            slots["display_tech"] = "oled" if "oled" in text else "ips"
        if any(k in text for k in ("windows", "macos", "linux", "ubuntu")):
            if "windows" in text:
                slots["os"] = "windows"
            if "mac" in text:
                slots["os"] = "macos"
            if "linux" in text or "ubuntu" in text:
                slots["os"] = "linux"
        return slots

    def _infer_use_case_tags(self, text: str) -> List[str]:
        tags: List[str] = []
        for tag, phrases in self._use_case_phrases.items():
            if any(p in text for p in phrases):
                tags.append(tag)
        return tags

    def _extract_product_features(self, candidate: Dict[str, Any]) -> Dict[str, Any]:
        name = (candidate.get("name") or "").lower()
        specs = candidate.get("specs") or {}
        try:
            specs_text = json.dumps(specs, ensure_ascii=False).lower()
        except Exception:
            specs_text = str(specs).lower()
        text = f"{name} {specs_text}"

        def _first_int(pattern: str) -> Optional[int]:
            m = re.search(pattern, text)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        ram_gb = None
        try:
            ram_gb = int(specs.get("ram_gb")) if specs.get("ram_gb") is not None else None
        except Exception:
            ram_gb = None
        if ram_gb is None:
            ram_gb = _first_int(r"(\d+)\s*gb\s*ram")

        storage_gb = None
        try:
            storage_gb = int(specs.get("storage_gb")) if specs.get("storage_gb") is not None else None
        except Exception:
            storage_gb = None
        if storage_gb is None:
            tb = _first_int(r"(\d+)\s*tb")
            if tb is not None:
                storage_gb = tb * 1024
            else:
                storage_gb = _first_int(r"(\d+)\s*gb\s*(ssd|storage|disk)")

        gpu_discrete = any(k in text for k in ("rtx", "geforce", "nvidia", "radeon", "discrete"))
        cpu_high = any(k in text for k in ("i9", "ryzen 9", "ultra", "m3 max", "m3 pro", "m2 pro", "m2 max"))
        oled = "oled" in text

        return {
            "ram_gb": ram_gb,
            "storage_gb": storage_gb,
            "gpu_discrete": gpu_discrete,
            "cpu_high": cpu_high,
            "oled": oled,
            "text": text,
        }

    def _use_case_score(self, use_case: str, features: Dict[str, Any], price_cents: int | None) -> Tuple[float, List[str]]:
        score = 0.0
        reasons: List[str] = []
        ram = features.get("ram_gb")
        storage = features.get("storage_gb")
        gpu = features.get("gpu_discrete")
        cpu_high = features.get("cpu_high")
        oled = features.get("oled")
        text = features.get("text") or ""

        if use_case in ("ai_ml_workstation", "ai_engineering", "ml_training", "data_science"):
            if gpu:
                score += 2.5
                reasons.append("use_case_gpu")
            else:
                score -= 1.0
                reasons.append("use_case_no_gpu")
            if ram is not None and ram >= 32:
                score += 2.0
                reasons.append("use_case_ram_32")
            if storage is not None and storage >= 1024:
                score += 1.2
                reasons.append("use_case_storage_1tb")
            if cpu_high:
                score += 1.0
                reasons.append("use_case_cpu_high")
        elif use_case == "gaming":
            if gpu:
                score += 2.0
                reasons.append("use_case_gpu")
            else:
                score -= 3.0
                reasons.append("use_case_no_discrete_gpu")
            if "rtx" in text:
                score += 1.5
                reasons.append("use_case_rtx")
            _hz_m = re.search(r"(\d+)\s*hz", text)
            if _hz_m:
                try:
                    _hz = int(_hz_m.group(1))
                    if _hz >= 144:
                        score += 1.0
                        reasons.append("use_case_144hz")
                    elif _hz < 60:
                        score -= 1.5
                        reasons.append("use_case_low_refresh")
                except Exception:
                    pass
        elif use_case in ("content_creation", "content_creator"):
            if gpu:
                score += 1.5
                reasons.append("use_case_gpu")
            if ram is not None and ram >= 16:
                score += 1.0
                reasons.append("use_case_ram_16")
            if oled:
                score += 0.8
                reasons.append("use_case_oled")
        elif use_case == "software_development":
            if ram is not None and ram >= 16:
                score += 1.0
                reasons.append("use_case_ram_16")
            if storage is not None and storage >= 512:
                score += 0.8
                reasons.append("use_case_storage_512")
        elif use_case in ("business", "office_general", "office_executive", "business_professional"):
            if any(k in text for k in ("thinkpad", "latitude", "elitebook", "probook", "xps")):
                score += 1.2
                reasons.append("use_case_business_line")
            if any(k in text for k in ("light", "ultrabook", "air")):
                score += 0.6
                reasons.append("use_case_portable")
        elif use_case in ("student", "university_general", "note_taking_student", "law_student", "medical_student"):
            if price_cents is not None:
                if price_cents <= 90000:
                    score += 1.5
                    reasons.append("use_case_budget_900")
                elif price_cents <= 120000:
                    score += 0.8
                    reasons.append("use_case_budget_1200")
            if any(k in text for k in ("light", "ultrabook", "2-in-1", "convertible")):
                score += 0.6
                reasons.append("use_case_student_portable")
        elif use_case in ("office_finance",):
            if ram is not None and ram >= 16:
                score += 1.2
                reasons.append("use_case_ram_16")
            if cpu_high:
                score += 0.8
                reasons.append("use_case_cpu_high")
        elif use_case == "mobile":
            if any(k in text for k in ("thin", "light", "ultrabook", "air")):
                score += 1.0
                reasons.append("use_case_portable")

        # KB exclusion penalties — fires for any use_case defined in use_case_kb.json
        try:
            _kb = _load_use_case_kb()
            _uc_entry: dict = (_kb.get("use_cases") or {}).get(use_case, {})
            _excl_rules: list = _uc_entry.get("exclusion_rules") or []
            _excl_w = float(
                ((_kb.get("soft_requirement_weights") or {}).get("exclusion_violation") or -2.0)
            )
            for _rule in _excl_rules:
                if _rule == "integrated_gpu_only" and not features.get("gpu_discrete"):
                    # Only penalise once — skip if heuristic branch already applied no-GPU penalty
                    _already = any("no_discrete_gpu" in r or "no_gpu" in r for r in reasons)
                    if not _already:
                        score += _excl_w
                        reasons.append(f"kb_exclusion:{_rule}")
                elif _rule == "fanless_design" and "fanless" in text:
                    score += _excl_w
                    reasons.append(f"kb_exclusion:{_rule}")
                elif _rule == "refresh_hz_below_60":
                    _m = re.search(r"(\d+)\s*hz", text)
                    if _m:
                        try:
                            if int(_m.group(1)) < 60:
                                score += _excl_w
                                reasons.append(f"kb_exclusion:{_rule}")
                        except Exception:
                            pass
                elif _rule == "consumer_gaming_aesthetic":
                    if any(k in text for k in ("gaming", "omen", "nitro", "tuf", "predator", "lol")):
                        score += _excl_w
                        reasons.append(f"kb_exclusion:{_rule}")
        except Exception:
            pass

        return score, reasons

    def _extract_condition_availability(self, text: str) -> Dict[str, Any]:
        slots: Dict[str, Any] = {}
        if any(k in text for k in ("refurb", "refurbished")):
            slots["condition"] = "refurbished"
        elif "used" in text:
            slots["condition"] = "used"
        elif "new" in text:
            slots["condition"] = "new"
        if "in stock" in text or "available today" in text:
            slots["availability"] = "in_stock"
        return slots

    def _extract_shipping_deadline(self, text: str) -> Optional[str]:
        # Supports YYYY-MM-DD and MM/DD(/YYYY)
        m = re.search(r"(?:deliver|arrive|ship)\s+by\s+(\d{4}-\d{2}-\d{2})", text)
        if m:
            return m.group(1)
        m = re.search(r"(?:deliver|arrive|ship)\s+by\s+(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", text)
        if m:
            mm = int(m.group(1))
            dd = int(m.group(2))
            yyyy = int(m.group(3)) if m.group(3) else time.gmtime().tm_year
            return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
        return None

    def _extract_quantity(self, text: str) -> Optional[int]:
        # Pattern for "buy X", "want X", "need X", "order X", "get X", "purchase X"
        m = re.search(r"(?:buy|want|need|order|get|purchase)\s+(\d+)\b", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        m = re.search(r"(?:qty|quantity|units|pcs)\s*[:=]?\s*(\d+)", text)
        if m:
            return int(m.group(1))
        m = re.search(r"\b(\d+)\s*(?:units|pcs|items|of them|laptops?|computers?|machines?)\b", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    def _detect_buyer_type(self, text: str) -> Optional[str]:
        if any(k in text for k in ("rfp", "tender", "gsa", "government", "public sector")):
            return "government"
        if any(k in text for k in ("procurement", "po ", "purchase order", "invoice me", "net-30", "site license", "sla")):
            return "enterprise"
        if any(k in text for k in ("business", "company", "bulk", "tax exempt", "warehouse")):
            return "business"
        return "consumer"

    def _detect_compliance_request(self, text: str) -> bool:
        return any(k in text for k in ("iso27001", "soc2", "soc 2", "pci", "gdpr", "eu ai act", "hipaa", "gsa", "fcc", "ce"))

    def _extract_brands(self, text: str) -> Tuple[List[str], List[str]]:
        known_brands = ["dell", "lenovo", "hp", "apple", "asus", "acer", "msi", "samsung"]
        includes: List[str] = []
        excludes: List[str] = []
        # Map common Apple product wording to brand intent so
        # "macbook" queries don't drift toward unrelated Windows laptops.
        if any(k in text for k in ("macbook", "mac book", "macbook air", "macbook pro")):
            includes.append("apple")
        for b in known_brands:
            if b in text:
                includes.append(b)
        for b in known_brands:
            if re.search(rf"(no|not|avoid|without)\s+{b}", text):
                excludes.append(b)
        # Preserve order while removing duplicates.
        includes = list(dict.fromkeys(includes))
        excludes = list(dict.fromkeys(excludes))
        return includes, excludes

    def _infer_intents(self, text: str, slots: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        scores: Dict[str, float] = {}
        evidence: Dict[str, Any] = {"rules": {}, "semantic": {}}

        def bump(intent: str, amount: float, reason: str):
            scores[intent] = scores.get(intent, 0.0) + amount
            evidence["rules"].setdefault(intent, []).append(reason)

        # Tier 1: keyword and regex rules
        if any(k in text for k in ("compare", "vs", "versus")):
            bump("compare_two_specific", 2.0, "compare_keywords")
        if "compare" in text and "and" in text:
            bump("compare_multiple_shortlist", 1.5, "compare_multiple")
        if re.search(r"(between|from|to)\s+\$?\d+", text):
            bump("price_range", 2.0, "price_range_pattern")
        if any(k in text for k in ("around $", "about $", "roughly $")):
            bump("budget_soft", 1.5, "budget_soft")
        if any(k in text for k in ("under", "below", "max", "no more than")):
            bump("budget_hard_cap", 1.5, "budget_hard_cap")
        if any(k in text for k in ("at least", "minimum", "no less than")):
            bump("price_floor", 1.2, "price_floor")
        if slots.get("ram_gb_min") or slots.get("storage_gb_min"):
            bump("spec_minimums", 1.8, "spec_minimums")
        if re.search(r"(no|without|exclude)\s+\w+", text):
            bump("spec_exclusions", 0.8, "exclusion_words")
        if any(k in text for k in ("gift", "present", "for my")):
            bump("gift_recommendation", 1.2, "gift_keywords")
        if any(k in text for k in ("best", "top", "recommended")):
            bump("best_overall_in_category", 0.6, "best_keywords")
        if any(k in text for k in ("pros and cons", "advantages", "disadvantages")):
            bump("pros_cons_request", 1.2, "pros_cons")
        if any(k in text for k in ("which should i buy", "help me decide")):
            bump("which_should_i_buy", 1.8, "decision_help")
        if any(k in text for k in ("what is", "explain")):
            bump("feature_education", 1.0, "feature_education")
        if any(k in text for k in ("deal", "discount", "on sale")):
            bump("deal_finder", 1.0, "deal_finder")
        if any(k in text for k in ("coupon", "promo code")):
            bump("coupon_applicability", 1.2, "coupon")
        if any(k in text for k in ("price match", "match price")):
            bump("price_match_policy", 1.2, "price_match")
        if any(k in text for k in ("return policy", "warranty policy", "eligible for return")):
            bump("policy_eligibility_check", 1.2, "policy_check")
        if any(k in text for k in ("where is my order", "order status", "track my order")):
            bump("order_status", 1.3, "order_status")
        if any(k in text for k in ("return", "refund", "exchange")):
            bump("return_request", 1.3, "return_request")
        if any(k in text for k in ("invoice", "purchase order", "net-30", "quote", "rfp")):
            bump("procurement_intent", 1.4, "procurement_intent")
        if slots.get("quantity") and slots.get("quantity") >= 10:
            bump("bulk_discount_inquiry", 1.2, "bulk_quantity")
        if any(k in text for k in ("wrong item", "damaged", "missing parts")):
            bump("order_issue_report", 1.4, "order_issue")
        if any(k in text for k in ("fake", "counterfeit")):
            bump("counterfeit_signal_report", 1.2, "counterfeit")
        if any(k in text for k in ("authentic", "genuine")):
            bump("authenticity_concern_product", 1.0, "authenticity")
        if any(k in text for k in ("review", "reviews")):
            bump("review_summary_request", 0.7, "reviews")
        if any(k in text for k in ("size", "fit", "sizing")):
            bump("sizing_fit_advice", 0.7, "sizing")
        if any(k in text for k in ("bundle", "with", "plus")):
            bump("bundle_recommendation", 0.6, "bundle")
        if any(k in text for k in ("compatible", "work with")):
            bump("compatibility_check", 0.9, "compatibility")
        if any(k in text for k in ("in stock", "available")):
            bump("availability_filter", 0.7, "availability")

        # Tier 2: semantic match using lightweight embeddings
        q_emb = self._emb.embed_text(text)
        for intent, phrases in self._intent_phrases.items():
            best_sim = 0.0
            for phrase in phrases:
                sim = self._emb.cosine(q_emb, self._emb.embed_text(phrase))
                best_sim = max(best_sim, sim)
            if best_sim >= 0.35:
                scores[intent] = scores.get(intent, 0.0) + (best_sim * 1.5)
                evidence["semantic"][intent] = round(best_sim, 3)

        # Always include product_search fallback
        scores["product_search"] = scores.get("product_search", 0.2) + 0.2

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        total = sum(s for _, s in ranked) or 1.0
        intent_chain = []
        for intent, score in ranked[:6]:
            confidence = round(min(1.0, score / total), 3)
            if confidence < 0.1:
                continue
            intent_chain.append({"intent": intent, "confidence": confidence})

        if len(intent_chain) > 1:
            intent_chain.insert(0, {"intent": "multi_intent_query", "confidence": 0.75})

        return intent_chain, evidence

    def _cache_put(self, key: str, val: Dict[str, float]) -> None:
        try:
            if key in self._emb_cache:
                # Move to end (most recent)
                self._emb_cache_order = [k for k in self._emb_cache_order if k != key]
            self._emb_cache[key] = val
            self._emb_cache_order.append(key)
            if len(self._emb_cache_order) > self._emb_cache_max:
                old = self._emb_cache_order.pop(0)
                self._emb_cache.pop(old, None)
        except Exception:
            # Best-effort cache
            pass

    def _cache_get(self, key: str) -> Optional[Dict[str, float]]:
        try:
            val = self._emb_cache.get(key)
            if val is not None:
                # Touch ordering
                self._emb_cache_order = [k for k in self._emb_cache_order if k != key]
                self._emb_cache_order.append(key)
            return val
        except Exception:
            return None

    def _tokenize(self, text: str) -> List[str]:
        tokens = []
        buf = []
        for ch in (text or "").lower():
            if ch.isalnum():
                buf.append(ch)
            else:
                if buf:
                    tokens.append("".join(buf))
                buf = []
        if buf:
            tokens.append("".join(buf))
        return [t for t in tokens if len(t) > 2]

    def _levenshtein(self, a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            cur = [i]
            for j, cb in enumerate(b, start=1):
                ins = cur[j - 1] + 1
                delete = prev[j] + 1
                sub = prev[j - 1] + (0 if ca == cb else 1)
                cur.append(min(ins, delete, sub))
            prev = cur
        return prev[-1]

    def _spelling_correct(self, query: str) -> str:
        q = str(query or "").strip().lower()
        if not q:
            return q
        tokens = self._tokenize(q)
        if not tokens:
            return q
        # Small domain vocabulary for ecommerce recommendations.
        vocab = {
            "laptop", "notebook", "ultrabook", "keyboard", "monitor", "charger", "adapter",
            "gaming", "business", "student", "battery", "screen", "ssd", "ram", "windows",
            "macbook", "lenovo", "dell", "apple", "asus", "acer", "hp", "samsung", "budget",
        }
        out: List[str] = []
        for t in tokens:
            if t in vocab or len(t) <= 3:
                out.append(t)
                continue
            best = t
            best_d = 99
            for cand in vocab:
                d = self._levenshtein(t, cand)
                if d < best_d:
                    best_d = d
                    best = cand
                    if d == 1:
                        break
            out.append(best if best_d <= 2 else t)
        return " ".join(out)

    def _expand_synonyms(self, query: str) -> str:
        q = str(query or "").strip().lower()
        if not q:
            return q
        syn = {
            "notebook": "laptop",
            "ultrabook": "laptop",
            "portable": "laptop",
            "gpu": "graphics",
            "graphics card": "gpu",
            "charger": "power adapter",
            "dock": "docking station",
            "cheap": "budget",
            "affordable": "budget",
        }
        expanded = q
        for src, dst in syn.items():
            if src in expanded and dst not in expanded:
                expanded = f"{expanded} {dst}"
        return expanded

    def _reformulate_query(self, query: str) -> List[str]:
        base = self._normalize_text(query or "")
        if not base:
            return []
        corrected = self._spelling_correct(base)
        expanded = self._expand_synonyms(corrected)
        out = [base]
        for q in (corrected, expanded):
            q = self._normalize_text(q)
            if q and q not in out:
                out.append(q)
        return out[:3]

    def _tfidf_rank(self, query: str, products: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        docs = []
        for p in products:
            specs = p.get("specs") or {}
            if isinstance(specs, dict):
                spec_text = " ".join(str(v) for v in specs.values())
            else:
                spec_text = str(specs)
            docs.append(f"{p.get('name','')} {p.get('sku','')} {spec_text}")
        def enrich(tokens: List[str]) -> List[str]:
            bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)]
            return tokens + bigrams
        doc_tokens = [enrich(self._tokenize(d)) for d in docs]
        df: Dict[str, int] = {}
        for toks in doc_tokens:
            for t in set(toks):
                df[t] = df.get(t, 0) + 1
        n_docs = max(len(doc_tokens), 1)
        def tfidf_vec(tokens: List[str]) -> Dict[str, float]:
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            vec: Dict[str, float] = {}
            for t, c in tf.items():
                idf = math.log((1 + n_docs) / (1 + df.get(t, 0))) + 1.0
                tf_weight = 1.0 + math.log(c)
                vec[t] = tf_weight * idf
            return vec
        q_vec = tfidf_vec(enrich(self._tokenize(query)))
        def cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            dot = 0.0
            for k, v in a.items():
                if k in b:
                    dot += v * b[k]
            norm_a = sum(v * v for v in a.values()) ** 0.5
            norm_b = sum(v * v for v in b.values()) ** 0.5
            return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0
        scored = []
        for p, toks in zip(products, doc_tokens):
            score = cosine(q_vec, tfidf_vec(toks))
            scored.append((score, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _s, p in scored[:limit]]

    @staticmethod
    def _budget_to_cents(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric <= 0:
            return None
        if abs(numeric) >= 100_000:
            return int(numeric)
        return int(round(numeric * 100))

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            m = re.search(r"\d+", str(value))
            return int(m.group(0)) if m else None

    @classmethod
    def _candidate_satisfies_spec(cls, candidate: Dict[str, Any], spec: Any) -> Optional[bool]:
        spec_text = str(spec or "").strip().lower()
        if not spec_text:
            return None
        specs = candidate.get("specs") if isinstance(candidate.get("specs"), dict) else {}
        try:
            blob = f"{candidate.get('name') or ''} {json.dumps(specs, ensure_ascii=False)}".lower()
        except Exception:
            blob = f"{candidate.get('name') or ''} {specs}".lower()

        def _min_from_spec() -> Optional[int]:
            if ":" in spec_text:
                raw = spec_text.split(":", 1)[1]
            else:
                raw = spec_text
            m = re.search(r"\d+", raw)
            return int(m.group(0)) if m else None

        if spec_text.startswith(("ram_gb_min:", "ram:")):
            required = _min_from_spec()
            actual = cls._to_int(specs.get("ram_gb")) or cls._to_int(specs.get("ram"))
            if actual is None:
                actual = cls._to_int(re.search(r"(\d+)\s*gb\s*(?:ram|memory)?", blob).group(1)) if re.search(r"(\d+)\s*gb\s*(?:ram|memory)?", blob) else None
            return None if required is None or actual is None else actual >= required

        if spec_text.startswith("refresh_hz_min:"):
            required = _min_from_spec()
            actual = cls._to_int(specs.get("refresh_hz")) or cls._to_int(specs.get("display_hz"))
            if actual is None:
                m = re.search(r"(\d+)\s*hz", blob)
                actual = int(m.group(1)) if m else None
            return None if required is None or actual is None else actual >= required

        if spec_text.startswith(("storage_gb_min:", "ssd:", "storage:")):
            required = _min_from_spec()
            if required is not None and "tb" in spec_text:
                required *= 1024
            actual = cls._to_int(specs.get("storage_gb")) or cls._to_int(specs.get("storage"))
            if actual is None:
                tb = re.search(r"(\d+)\s*tb", blob)
                gb = re.search(r"(\d+)\s*gb\s*(?:ssd|storage|disk)?", blob)
                actual = int(tb.group(1)) * 1024 if tb else (int(gb.group(1)) if gb else None)
            return None if required is None or actual is None else actual >= required

        if spec_text == "gpu:discrete":
            try:
                from src.app.services.recommend_candidate_classify import gpu_tier

                return gpu_tier(candidate) in ("entry", "mid", "high")
            except Exception:
                return any(tok in blob for tok in ("rtx", "gtx", "geforce", "radeon rx", "radeon pro", "discrete"))

        return None

    def analyze_query(self, query: str, prior: Dict[str, Any] | None = None) -> Dict[str, Any]:
        text, locale = self._apply_multilingual_normalization(query)
        prior = prior or {}
        budget_min, budget_max, budget = self._extract_price_range(text)
        spec_slots = self._extract_specs(text)
        condition_slots = self._extract_condition_availability(text)
        ship_deadline = self._extract_shipping_deadline(text)
        brand_includes, brand_excludes = self._extract_brands(text)
        quantity = self._extract_quantity(text)
        buyer_type = self._detect_buyer_type(text)
        compliance_requested = self._detect_compliance_request(text)
        slots: Dict[str, Any] = {
            "price_min": budget_min,
            "price_max": budget_max,
            "budget": budget,
            "specs": {},
            "brand_includes": brand_includes,
            "brand_excludes": brand_excludes,
            "condition": condition_slots.get("condition"),
            "availability": condition_slots.get("availability"),
            "shipping_deadline": ship_deadline,
            "quantity": quantity,
        }
        slots["specs"].update(spec_slots)

        intent_chain, intent_evidence = self._infer_intents(text, slots)
        primary_intent = intent_chain[0]["intent"] if intent_chain else "product_search"
        primary_conf = intent_chain[0]["confidence"] if intent_chain else 0.2
        # Confidence calibration: richer entities imply lower ambiguity in production traffic.
        entity_richness = 0
        if budget_min is not None or budget_max is not None or budget is not None:
            entity_richness += 1
        if brand_includes:
            entity_richness += 1
        if spec_slots:
            entity_richness += 1
        if quantity:
            entity_richness += 1
        if entity_richness >= 3:
            primary_conf = min(0.99, round(primary_conf + 0.08, 4))
        elif entity_richness == 2:
            primary_conf = min(0.99, round(primary_conf + 0.04, 4))

        entities: Dict[str, Any] = {"brands": brand_includes, "specs": [], "use_case": None}
        entities["buyer_type"] = buyer_type
        entities["compliance_requested"] = compliance_requested
        if quantity:
            entities["quantity"] = quantity
        if budget_max:
            entities["budget_max"] = budget_max
        if budget_min:
            entities["budget_min"] = budget_min

        if slots["specs"].get("ram_gb_min"):
            entities["specs"].append(f"ram:{slots['specs']['ram_gb_min']}gb")
        if slots["specs"].get("storage_gb_min"):
            storage_gb = int(slots["specs"]["storage_gb_min"])
            if storage_gb >= 1024:
                entities["specs"].append("ssd:1tb")
            else:
                entities["specs"].append(f"ssd:{storage_gb}gb")
        if slots["specs"].get("gpu_class") == "discrete":
            entities["specs"].append("gpu:discrete")
        if slots["specs"].get("os"):
            entities["specs"].append(f"os:{slots['specs']['os']}")

        # AI/ML use case detection (check BEFORE generic "work" to avoid false match)
        use_case_tags = self._infer_use_case_tags(text)
        if any(k in use_case_tags for k in ("ai_ml_workstation",)):
            entities["use_case"] = "ai_ml_workstation"
            # AI/ML workloads need: high RAM (32GB+), discrete GPU (RTX/CUDA), fast storage
            if not slots["specs"].get("ram_gb_min"):
                slots["specs"]["ram_gb_min"] = 32
            if not slots["specs"].get("gpu_class"):
                slots["specs"]["gpu_class"] = "discrete"
        elif any(k in use_case_tags for k in ("software_development",)):
            entities["use_case"] = "software_development"
        elif any(k in use_case_tags for k in ("student",)):
            entities["use_case"] = "student"
        elif any(k in text for k in ("video", "creator", "editing")):
            entities["use_case"] = "content_creation"
        elif any(k in text for k in ("gaming", "gpu", "graphics")):
            entities["use_case"] = "gaming"
        elif any(k in text for k in ("travel", "battery", "on the go")):
            entities["use_case"] = "mobile"
        elif any(k in text for k in ("office", "work", "business")):
            entities["use_case"] = "business"
        if use_case_tags and not entities.get("use_case"):
            entities["use_case"] = use_case_tags[0]
        lifecycle_signal = self._extract_lifecycle_signal(text)
        if lifecycle_signal:
            entities["lifecycle_signal"] = lifecycle_signal

        # Use word-boundary matching so terms like "with" do not accidentally
        # trigger follow-up carryover via the substring "it".
        if re.search(r"\b(it|that|same|similar|these|those|previous|earlier)\b", text):
            if not entities.get("brands") and prior.get("brands"):
                entities["brands"] = prior.get("brands")
            if not entities.get("specs") and prior.get("specs"):
                entities["specs"] = prior.get("specs")
            if not entities.get("budget_max") and prior.get("budget_max"):
                entities["budget_max"] = prior.get("budget_max")

        preferences = {
            "brands": entities.get("brands") or prior.get("brands") or [],
            "specs": entities.get("specs") or prior.get("specs") or [],
            "budget_max": entities.get("budget_max") or prior.get("budget_max"),
            "budget_min": entities.get("budget_min") or prior.get("budget_min"),
            "use_case": entities.get("use_case") or prior.get("use_case"),
            "use_case_tags": use_case_tags or prior.get("use_case_tags") or [],
            "intent": primary_intent,
            "brand_excludes": brand_excludes,
            "availability": slots.get("availability"),
            "condition": slots.get("condition"),
            "buyer_type": buyer_type,
            "compliance_requested": compliance_requested,
            "quantity": quantity,
            "locale": locale,
            "lifecycle_signal": lifecycle_signal,
        }
        # Pre-LLM typed context pack for consistent agent handoff
        context_pack = {
            "intent": primary_intent,
            "use_case": entities.get("use_case"),
            "use_case_tags": use_case_tags,
            "quantity": quantity,
            "constraints": {
                "price_min": budget_min,
                "price_max": budget_max,
                "budget": budget,
                "specs": slots.get("specs") or {},
                "availability": slots.get("availability"),
                "condition": slots.get("condition"),
            },
            "state": None,
            "risk_band": None,
            "buyer_type": buyer_type,
            "locale": locale,
            "lifecycle_signal": lifecycle_signal,
        }
        followups = []
        if not entities.get("budget_max") and not entities.get("budget_min"):
            followups.append("What is your budget range?")
        if not entities.get("specs"):
            followups.append("Any must-have specs (RAM, screen size, OS)?")
        if not entities.get("use_case"):
            followups.append("What will you use the laptop for (work, travel, gaming)?")

        llm_fallback = primary_conf < 0.45 or len(intent_chain) > 3

        return {
            "intent": primary_intent,
            "intent_confidence": primary_conf,
            "intent_chain": intent_chain,
            "intent_evidence": intent_evidence,
            "entities": entities,
            "use_case_tags": use_case_tags,
            "preferences": preferences,
            "context_pack": context_pack,
            "locale": locale,
            "followups": followups,
            "slots": slots,
            "llm_fallback": llm_fallback,
        }

    def parse_constraints(self, query: str) -> Dict[str, Any]:
        text = self._normalize_text(query)
        constraints: Dict[str, Any] = {"brands": [], "specs": []}
        budget_min, budget_max, budget = self._extract_price_range(text)
        budget_delta = self._extract_budget_delta(text)
        spec_slots = self._extract_specs(text)
        condition_slots = self._extract_condition_availability(text)
        brand_includes, brand_excludes = self._extract_brands(text)

        # If user asked for relative budget movement ("increase/widen by X"),
        # avoid treating that number as an absolute cap.
        if budget_delta is not None and budget_min is None and budget_max is None:
            budget = None

        if budget is not None and budget_max is None:
            budget_max = budget
        if budget_delta is not None:
            constraints["budget_delta"] = int(budget_delta)
        if budget_min is not None:
            constraints["budget_min"] = budget_min
        if budget_max is not None:
            constraints["budget_max"] = budget_max
        constraints["brands"] = brand_includes
        if "apple" in [str(b).lower() for b in brand_includes]:
            constraints["brand_intent_strict"] = True
        if brand_excludes:
            constraints["brand_excludes"] = brand_excludes
        if condition_slots.get("availability"):
            constraints["availability"] = condition_slots.get("availability")
        if condition_slots.get("condition"):
            constraints["condition"] = condition_slots.get("condition")

        if spec_slots.get("ram_gb_min"):
            constraints["specs"].append(f"ram:{spec_slots['ram_gb_min']}gb")
        if spec_slots.get("storage_gb_min"):
            storage_gb = int(spec_slots["storage_gb_min"])
            if storage_gb >= 1024:
                constraints["specs"].append("ssd:1tb")
            else:
                constraints["specs"].append(f"ssd:{storage_gb}gb")
        if spec_slots.get("gpu_class") == "discrete":
            constraints["specs"].append("gpu:discrete")
        if spec_slots.get("os"):
            constraints["specs"].append(f"os:{spec_slots['os']}")
        return constraints

    def retrieve_candidates(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        def _candidate_from_product(p: Any, stock: Optional[int] = None) -> Dict[str, Any]:
            return {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "price_cents": p.price_cents,
                "currency": p.currency,
                "image_url": getattr(p, "image_url", None),
                "stock": stock,
                "specs": p.specs or {},
            }

        def _prepend_unique(preferred: List[Dict[str, Any]], existing: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            merged: List[Dict[str, Any]] = []
            seen: set[str] = set()
            for item in (preferred or []) + (existing or []):
                sku = str((item or {}).get("sku") or "").strip()
                if not sku or sku in seen:
                    continue
                merged.append(item)
                seen.add(sku)
            return merged

        with self.tracer.start_as_current_span("recommend.retrieve_candidates") as span:
            span.set_attribute("query.length", len(query or ""))
            span.set_attribute("limit", limit)
            products = []
            for q in self._reformulate_query(query):
                hits = self.catalog.search_products(q, limit=limit)
                for p in hits or []:
                    if any(getattr(p, "id", None) == getattr(x, "id", None) for x in products):
                        continue
                    products.append(p)
                    if len(products) >= max(8, limit * 2):
                        break
                if len(products) >= max(8, limit * 2):
                    break
        candidates: List[Dict[str, Any]] = []
        # Batch-fetch stock for products to avoid N DB round-trips
        prod_ids = [p.id for p in products]
        try:
            stock_map = self.catalog.get_stock_by_product_ids(prod_ids)
        except Exception:
            stock_map = {}
        for p in products:
            stock = stock_map.get(p.id) if stock_map is not None else None
            candidates.append(_candidate_from_product(p, stock=stock))

        # Augment with vector search results when embeddings provider enables it
        provider = (os.getenv("EMBEDDINGS_PROVIDER") or "bow").strip().lower()
        if provider in ("openai", "vector", "pgvector") and (query or "").strip():
            try:
                vec = VectorStoreEmbeddings()
                qvec = vec.embed_text_vector(query)
                sess = self.catalog._get_session()
                if sess is not None:
                    rows = search_products_by_embedding(sess, qvec, top_k=max(5, min(24, limit * 2)))
                else:
                    with db_session() as db:
                        rows = search_products_by_embedding(db, qvec, top_k=max(5, min(24, limit * 2)))
                ids = [r.get("product_id") for r in (rows or []) if r.get("product_id")]
                if ids:
                    prods = self.catalog.get_products_by_ids(ids)
                    by_id = {p.id: p for p in prods}
                    try:
                        v_stock = self.catalog.get_stock_by_product_ids(ids)
                    except Exception:
                        v_stock = {}
                    seen = {c.get("sku") for c in candidates}
                    for r in rows:
                        pid = r.get("product_id")
                        p = by_id.get(pid)
                        if not p:
                            continue
                        if p.sku in seen:
                            continue
                        candidates.append(_candidate_from_product(p, stock=(v_stock or {}).get(p.id)))
                        seen.add(p.sku)
                        if len(candidates) >= limit:
                            break
            except Exception:
                pass
        try:
            from src.app.services.recommend_candidate_classify import use_case_fit

            all_products = self.catalog.list_products(limit=400)
            pool: List[Dict[str, Any]] = []
            for p in all_products:
                pool.append(_candidate_from_product(p, stock=None))
            use_case_topups = []
            for item in pool:
                fit = use_case_fit(item, query)
                reasons = fit.get("reasons") or []
                if fit.get("use_case") and fit.get("meets") and len(reasons) > 1:
                    score = 0
                    tier = str(fit.get("tier") or "")
                    if tier == "high":
                        score += 3
                    elif tier == "mid":
                        score += 2
                    elif tier == "entry":
                        score += 1
                    score += min(3, len(reasons))
                    item["_use_case_topup_score"] = score
                    item["_use_case_topup_reasons"] = reasons
                    use_case_topups.append(item)
            if use_case_topups:
                topup_ids = [p["id"] for p in use_case_topups if p.get("id")]
                try:
                    topup_stock = self.catalog.get_stock_by_product_ids(topup_ids)
                except Exception:
                    topup_stock = {}
                for p in use_case_topups:
                    if p.get("id") in topup_stock:
                        p["stock"] = topup_stock.get(p.get("id"))
                use_case_topups.sort(
                    key=lambda p: (
                        int(p.get("stock") or 0) > 0,
                        float(p.get("_use_case_topup_score") or 0.0),
                        -float(p.get("price_cents") or 0.0),
                    ),
                    reverse=True,
                )
                candidates = _prepend_unique(use_case_topups[: max(8, limit)], candidates)
        except Exception:
            pass
        if len(candidates) < limit:
            try:
                all_products = self.catalog.list_products(limit=200)
                pool = []
                for p in all_products:
                    pool.append(_candidate_from_product(p, stock=None))
                ranked = self._tfidf_rank(query, pool, limit)
                seen = {c["sku"] for c in candidates}
                # Batch-fetch stock for ranked candidates
                ranked_ids = [p["id"] for p in ranked]
                try:
                    ranked_stock = self.catalog.get_stock_by_product_ids(ranked_ids)
                except Exception:
                    ranked_stock = {}
                for p in ranked:
                    if p["sku"] in seen:
                        continue
                    p_stock = ranked_stock.get(p["id"]) 
                    if p_stock is not None:
                        p["stock"] = p_stock
                    candidates.append(p)
                    seen.add(p["sku"])
                    if len(candidates) >= limit:
                        break
            except Exception:
                pass
        return candidates

    def rerank_candidates(self, candidates: List[Dict[str, Any]], constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
        scored = self.rerank_candidates_with_factors(candidates, constraints)
        return [s["candidate"] for s in scored]

    def _linked_uid_hashes(self, uid_hash: str | None) -> List[str]:
        uid = str(uid_hash or "").strip()
        if not uid:
            return []
        try:
            sess = self.catalog._get_session()
            if sess is not None:
                linked = linked_uid_hashes(sess, uid, max_depth=2, max_nodes=24)
            else:
                with db_session() as db:
                    linked = linked_uid_hashes(db, uid, max_depth=2, max_nodes=24)
            return linked or [uid]
        except Exception:
            return [uid]

    def _clickstream_affinity(self, uid_hash: str | None, sku: str, lookback_days: int = 45) -> float:
        if not uid_hash or not sku:
            return 0.0
        uid = str(uid_hash).strip()
        if not uid:
            return 0.0
        uid_keys = self._linked_uid_hashes(uid)
        if not uid_keys:
            return 0.0
        weight = {"hover": 0.15, "view": 0.25, "click": 0.85, "add_to_cart": 1.2, "atc": 1.2, "cart_add": 1.2}
        try:
            uid_placeholders = ", ".join([f":u{i}" for i in range(len(uid_keys))])
            params = {f"u{i}": uid_keys[i] for i in range(len(uid_keys))}
            params.update({"sku": str(sku), "window": f"-{max(1, int(lookback_days))} days"})
            sess = self.catalog._get_session()
            if sess is not None:
                rows = sess.execute(
                    text(
                        f"""
                        SELECT action, COUNT(*) AS n
                        FROM recommend_interactions
                        WHERE uid_hash IN ({uid_placeholders})
                          AND sku = :sku
                          AND datetime(event_time) >= datetime('now', :window)
                        GROUP BY action
                        """
                    ),
                    params,
                ).fetchall()
            else:
                with db_session() as db:
                    rows = db.execute(
                        text(
                            f"""
                            SELECT action, COUNT(*) AS n
                            FROM recommend_interactions
                            WHERE uid_hash IN ({uid_placeholders})
                              AND sku = :sku
                              AND datetime(event_time) >= datetime('now', :window)
                            GROUP BY action
                            """
                        ),
                        params,
                    ).fetchall()
        except Exception:
            return 0.0
        score = 0.0
        for r in rows or []:
            act = str(r[0] or "").strip().lower()
            cnt = int(r[1] or 0)
            if not act or cnt <= 0:
                continue
            score += float(weight.get(act, 0.0)) * float(cnt)
        return min(1.5, score)

    def _clickstream_affinity_map(
        self,
        uid_hash: str | None,
        skus: List[str],
        lookback_days: int = 45,
    ) -> Dict[str, float]:
        out: Dict[str, float] = {}
        uid = str(uid_hash or "").strip()
        clean = [str(s).strip() for s in (skus or []) if str(s).strip()]
        if not uid or not clean:
            return out
        for sku in clean:
            out[sku] = self._clickstream_affinity(uid, sku, lookback_days=lookback_days)
        return out

    def _collaborative_filter_scores(self, uid_hash: str | None, candidate_skus: List[str]) -> Dict[str, float]:
        uid = str(uid_hash or "").strip()
        if not uid or not candidate_skus:
            return {}
        linked_uids = self._linked_uid_hashes(uid)
        try:
            sess = self.catalog._get_session()
            if sess is not None:
                pre = load_precomputed_cf_scores(sess, linked_uids, candidate_skus)
            else:
                with db_session() as db:
                    pre = load_precomputed_cf_scores(db, linked_uids, candidate_skus)
            if pre:
                return pre
        except Exception:
            pass

        interactions: List[Tuple[str, str, int]] = []
        try:
            sess = self.catalog._get_session()
            if sess is not None:
                rows = sess.execute(
                    text(
                        f"""
                        SELECT uid_hash, sku, COUNT(*) AS n
                        FROM recommend_interactions
                        WHERE datetime(event_time) >= datetime('now', :window)
                          AND action IN ('click','add_to_cart','atc','cart_add')
                          AND uid_hash IS NOT NULL
                          AND sku IS NOT NULL
                        GROUP BY uid_hash, sku
                        LIMIT 6000
                        """
                    ),
                    {"window": "-90 days"},
                ).fetchall()
            else:
                with db_session() as db:
                    rows = db.execute(
                        text(
                            f"""
                            SELECT uid_hash, sku, COUNT(*) AS n
                            FROM recommend_interactions
                            WHERE datetime(event_time) >= datetime('now', :window)
                              AND action IN ('click','add_to_cart','atc','cart_add')
                              AND uid_hash IS NOT NULL
                              AND sku IS NOT NULL
                            GROUP BY uid_hash, sku
                            LIMIT 6000
                            """
                        ),
                        {"window": "-90 days"},
                    ).fetchall()
        except Exception:
            return {}
        for r in rows or []:
            interactions.append((str(r[0] or "").strip(), str(r[1] or "").strip(), int(r[2] or 0)))
        if not interactions:
            return {}

        user_item: Dict[str, Dict[str, float]] = defaultdict(dict)
        item_users: Dict[str, Dict[str, float]] = defaultdict(dict)
        for u, i, n in interactions:
            if not u or not i or n <= 0:
                continue
            val = min(4.0, 1.0 + math.log1p(float(n)))
            user_item[u][i] = val
            item_users[i][u] = val
        merged: Dict[str, float] = {}
        for lu in linked_uids:
            prof = user_item.get(str(lu), {})
            for sku, val in prof.items():
                merged[sku] = max(float(val), float(merged.get(sku, 0.0)))
        user_profile = merged
        if not user_profile:
            return {}

        out: Dict[str, float] = {}
        for sku in candidate_skus:
            if sku in user_profile:
                out[sku] = min(1.4, float(user_profile[sku]))
                continue
            users_for_sku = item_users.get(str(sku), {})
            if not users_for_sku:
                continue
            num = 0.0
            den = 0.0
            for seen_sku, pref in user_profile.items():
                users_for_seen = item_users.get(str(seen_sku), {})
                if not users_for_seen:
                    continue
                overlap = set(users_for_sku.keys()) & set(users_for_seen.keys())
                if not overlap:
                    continue
                top = 0.0
                left = 0.0
                right = 0.0
                for u in overlap:
                    a = float(users_for_sku.get(u, 0.0))
                    b = float(users_for_seen.get(u, 0.0))
                    top += a * b
                    left += a * a
                    right += b * b
                sim = (top / math.sqrt(max(1e-9, left * right))) if left > 0 and right > 0 else 0.0
                if sim <= 0:
                    continue
                num += sim * float(pref)
                den += abs(sim)
            if den > 0:
                out[str(sku)] = min(1.4, max(0.0, num / den))
        return out

    def _supplier_performance_map(self, candidate_skus: List[str], lookback_days: int = 30) -> Dict[str, float]:
        clean = [str(s).strip() for s in (candidate_skus or []) if str(s).strip()]
        if not clean:
            return {}
        params = {
            "skus": clean,
            "window": f"-{max(7, int(lookback_days))} days",
        }
        query = text(
            """
            SELECT sa.sku,
                   AVG(COALESCE(sa.score, 0)) AS supplier_score
            FROM supplier_score_audits sa
            WHERE sa.sku IN :skus
              AND datetime(sa.created_at) >= datetime('now', :window)
            GROUP BY sa.sku
            """
        ).bindparams(bindparam("skus", expanding=True))
        try:
            sess = self.catalog._get_session()
            if sess is not None:
                rows = sess.execute(query, params).fetchall()
            else:
                with db_session() as db:
                    rows = db.execute(query, params).fetchall()
        except Exception:
            return {}
        out: Dict[str, float] = {}
        for r in rows or []:
            sku = str(r[0] or "").strip()
            if not sku:
                continue
            score = float(r[1] or 0.0)
            # Normalize from ~0..2 range used by supplier audit scoring.
            out[sku] = max(0.0, min(1.0, score / 2.0))
        return out

    def _cross_encoder_score(self, query: str, candidate: Dict[str, Any]) -> float:
        q = str(query or "").strip()
        if not q:
            return 0.0
        text_blob = f"{candidate.get('name') or ''} {candidate.get('sku') or ''} {json.dumps(candidate.get('specs') or {}, ensure_ascii=False)}"
        model_name = str(os.getenv("RECO_CROSS_ENCODER_MODEL", "") or "").strip()
        if model_name:
            try:
                from sentence_transformers import CrossEncoder  # type: ignore

                model = getattr(self, "_cross_encoder_model", None)
                if model is None:
                    model = CrossEncoder(model_name)
                    setattr(self, "_cross_encoder_model", model)
                pred = float(model.predict([(q, text_blob)])[0])
                return pred
            except Exception:
                pass
        # Lightweight fallback: token overlap + contiguous phrase bonus.
        q_tokens = set(self._tokenize(q))
        d_tokens = set(self._tokenize(text_blob))
        if not q_tokens or not d_tokens:
            return 0.0
        overlap = len(q_tokens & d_tokens) / float(max(1, len(q_tokens)))
        phrase_bonus = 0.18 if " ".join(list(q_tokens)[:2]) in text_blob.lower() else 0.0
        return float(overlap + phrase_bonus)

    def rerank_candidates_with_factors(self, candidates: List[Dict[str, Any]], constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
        t0 = time.perf_counter()
        budget = constraints.get("budget_max")
        budget_cents = self._budget_to_cents(budget)
        brands = constraints.get("brands") or []
        specs = constraints.get("specs") or []
        intent = constraints.get("intent") or "recommend"
        use_case = constraints.get("use_case") or ""
        use_case_tags = constraints.get("use_case_tags") or []

        # ── Seasonal auto-inject: read active season from flags, resolve
        #    use-case priority factors, store on constraints for downstream use.
        if "seasonal_boosts" not in constraints:
            try:
                seasonal_boosts, season_name = get_active_seasonal_boosts()
                if seasonal_boosts:
                    from src.app.services.use_case_advisor import get_use_case_priority_factors
                    pf = get_use_case_priority_factors(use_case) if use_case else []
                    constraints["seasonal_boosts"] = seasonal_boosts
                    constraints["seasonal_season"] = season_name
                    constraints["use_case_priority_factors"] = pf
            except Exception:
                pass
        uid_hash = str(constraints.get("uid_hash") or "").strip() or None
        candidate_skus = [str((c or {}).get("sku") or "").strip() for c in candidates if str((c or {}).get("sku") or "").strip()]
        cf_scores = self._collaborative_filter_scores(uid_hash, candidate_skus)
        clickstream_scores = self._clickstream_affinity_map(uid_hash, candidate_skus)
        supplier_scores = self._supplier_performance_map(candidate_skus)
        bandit_arm = "balanced"
        try:
            bandit_ctx = {
                "budget_tight": 1.0 if budget_cents and budget_cents <= 100000 else 0.0,
                "is_repeat_user": 1.0 if uid_hash else 0.0,
                "query_specificity": min(1.0, len((specs or [])) / 3.0),
                "inventory_pressure": 1.0 if any((c.get("stock") or 0) <= 2 for c in candidates) else 0.0,
            }
            sess = self.catalog._get_session()
            if sess is not None:
                bandit = choose_recommendation_arm(sess, bandit_ctx)
            else:
                with db_session() as db:
                    bandit = choose_recommendation_arm(db, bandit_ctx)
            bandit_arm = str((bandit or {}).get("arm") or "balanced")
        except Exception:
            bandit_arm = "balanced"
        # Carry the chosen arm to the attribution capture seam (E0) + feedback endpoints so the
        # arm that ranked the results is the arm that gets rewarded (E3), not the A/B variant.
        from src.app.services.bandit_context import set_bandit_arm
        set_bandit_arm(bandit_arm)
        arm_weights = {
            "balanced": {"cf": 1.30, "click": 0.80, "supplier": 0.65, "cross": 0.60},
            "explore_novelty": {"cf": 0.95, "click": 1.15, "supplier": 0.50, "cross": 0.80},
            "price_value": {"cf": 1.05, "click": 0.60, "supplier": 0.90, "cross": 0.45},
            "personalized_heavy": {"cf": 1.55, "click": 1.00, "supplier": 0.50, "cross": 0.70},
        }
        arm_w = arm_weights.get(bandit_arm, arm_weights["balanced"])

        # Precompute query embedding once for similarity boost
        q_text = str(constraints.get("query") or "")
        if q_text:
            try:
                q_emb = self._emb.embed_text(q_text)
            except Exception:
                q_emb = None
        else:
            q_emb = None

        def score(c: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
            factors = {"positive": [], "negative": [], "checks": [], "weights": {}}
            s = 0.0
            if (c.get("stock") or 0) > 0:
                s += 10.0
                factors["positive"].append("+in_stock")
                factors["weights"]["in_stock"] = 10.0
            else:
                s -= 6.0
                factors["negative"].append("-out_of_stock")
                factors["weights"]["out_of_stock"] = -6.0
            price = c.get("price_cents", 0)
            if budget_cents:
                if price <= budget_cents:
                    s += 5.0
                    factors["positive"].append("+within_budget")
                    factors["weights"]["within_budget"] = 5.0
                else:
                    s -= 5.0
                    factors["negative"].append("-over_budget")
                    factors["weights"]["over_budget"] = -5.0
            if brands:
                name = (c.get("name") or "").lower()
                sku = (c.get("sku") or "").lower()
                if any(b in name or b in sku for b in brands):
                    s += 3.0
                    factors["positive"].append("+brand_match")
                    factors["weights"]["brand_match"] = 3.0
                else:
                    strict_brand_intent = bool(constraints.get("brand_intent_strict"))
                    mismatch_penalty = -8.0 if strict_brand_intent else -1.0
                    s += mismatch_penalty
                    factors["negative"].append("-brand_mismatch")
                    factors["weights"]["brand_mismatch"] = mismatch_penalty
            if specs:
                spec_text = json.dumps(c.get("specs") or {}, ensure_ascii=False).lower()
                for spec in specs:
                    spec_match = self._candidate_satisfies_spec(c, spec)
                    key = str(spec).replace(":", " ")
                    if spec_match is True or (spec_match is None and key.split()[0] in spec_text):
                        s += 1.5
                        factors["positive"].append(f"+{spec}")
                        factors["weights"][spec] = 1.5
                    else:
                        factors["negative"].append(f"-{spec}")
                        factors["weights"][spec] = -0.5
            if intent == "availability":
                s += 1.0
                factors["checks"].append("availability_priority")
                factors["weights"]["availability_priority"] = 1.0
            if use_case:
                factors["checks"].append(f"use_case:{use_case}")
                factors["weights"][f"use_case:{use_case}"] = 0.5
                features = self._extract_product_features(c)
                uc_score, uc_reasons = self._use_case_score(use_case, features, c.get("price_cents"))
                if uc_score != 0:
                    s += uc_score
                    if uc_score > 0:
                        factors["positive"].append(f"+use_case_match:{use_case}")
                    else:
                        factors["negative"].append(f"-use_case_match:{use_case}")
                    for r in uc_reasons:
                        factors["checks"].append(r)
                        factors["weights"][r] = round(uc_score, 2)
            if use_case_tags:
                for tag in use_case_tags:
                    if tag == use_case:
                        continue
                    features = self._extract_product_features(c)
                    uc_score, uc_reasons = self._use_case_score(tag, features, c.get("price_cents"))
                    if uc_score > 0:
                        s += uc_score * 0.5
                        factors["positive"].append(f"+use_case_tag:{tag}")
                        factors["weights"][f"use_case_tag:{tag}"] = round(uc_score * 0.5, 2)

            # Embeddings similarity boost: query vs product name/specs
            if q_emb:
                cache_key = f"emb:{c.get('sku')}:v1"
                p_emb = self._cache_get(cache_key)
                if p_emb is None:
                    p_name = c.get("name") or ""
                    p_specs = json.dumps(c.get("specs") or {}, ensure_ascii=False)
                    p_emb = self._emb.embed_product(p_name, p_specs)
                    self._cache_put(cache_key, p_emb)
                sim = self._emb.cosine(q_emb, p_emb)
                if sim > 0:
                    # Weight modestly to avoid overpowering stock/price
                    w = 2.0
                    s += sim * w
                    factors["positive"].append("+embedding_similarity")
                    factors["weights"]["embedding_similarity"] = round(sim * w, 3)
                else:
                    factors["negative"].append("-embedding_similarity")
                    factors["weights"]["embedding_similarity"] = 0.0

            sku_key = str(c.get("sku") or "").strip()
            cf = float(cf_scores.get(sku_key, 0.0) or 0.0)
            if cf > 0.0:
                cf_w = float(arm_w.get("cf", 1.35))
                s += cf * cf_w
                factors["positive"].append("+collaborative_filtering")
                factors["weights"]["collaborative_filtering"] = round(cf * cf_w, 3)
            clickstream = float(clickstream_scores.get(sku_key, 0.0) or 0.0)
            if clickstream > 0.0:
                cs_w = float(arm_w.get("click", 0.8))
                s += clickstream * cs_w
                factors["positive"].append("+clickstream_affinity")
                factors["weights"]["clickstream_affinity"] = round(clickstream * cs_w, 3)
            supplier = float(supplier_scores.get(sku_key, 0.0) or 0.0)
            if supplier > 0.0:
                sp_w = float(arm_w.get("supplier", 0.65))
                s += supplier * sp_w
                factors["positive"].append("+supplier_performance")
                factors["weights"]["supplier_performance"] = round(supplier * sp_w, 3)
            return s, factors

        # Optional LTR scorer when model is available; otherwise use rule-based score.
        # Strict feature gate defaults to disabled.
        ltr_model = None
        ltr_type = None
        rerank_mode = "heuristic"
        try:
            ltr_enabled = str(os.environ.get("LTR_ENABLED", "0")).strip().lower() in ("1", "true", "yes", "on")
            rollout = int(os.environ.get("LTR_ROLLOUT_PERCENT", "0") or 0)
            rollout = max(0, min(100, rollout))
            key = str(constraints.get("query") or constraints.get("tenant_id") or "global")
            bucket = int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16) % 100
            ltr_allowed = ltr_enabled and (bucket < rollout)
            path = os.environ.get("LTR_MODEL_PATH") or ""
            if ltr_allowed and path:
                try:
                    import xgboost as xgb  # type: ignore
                    ltr_model = xgb.XGBRegressor()
                    ltr_model.load_model(path)
                    ltr_type = "xgb"
                except Exception:
                    import joblib  # type: ignore
                    ltr_model = joblib.load(path)
                    ltr_type = "sklearn"
        except Exception:
            ltr_model = None
            ltr_type = None

        def _ltr_features(c: Dict[str, Any], f: Dict[str, Any]) -> List[float]:
            # Build a small numeric feature vector compatible with common LTR setups
            price = float(c.get("price_cents") or 0.0)
            stock = float(c.get("stock") or 0.0)
            emb_sim = float(f.get("weights", {}).get("embedding_similarity", 0.0) or 0.0)
            within_budget = 1.0 if "+within_budget" in f.get("positive", []) else 0.0
            brand_match = 1.0 if "+brand_match" in f.get("positive", []) else 0.0
            spec_match = sum(1.0 for k in f.get("positive", []) if k.startswith("+"))
            use_case_weight = 0.0
            for k, v in f.get("weights", {}).items():
                if str(k).startswith("use_case"):
                    try:
                        use_case_weight += float(v or 0.0)
                    except Exception:
                        pass
            return [price, stock, emb_sim, within_budget, brand_match, spec_match, use_case_weight]

        scored: List[Dict[str, Any]] = []
        for c in candidates:
            base_score, factors = score(c)
            s_val = base_score
            if ltr_model is not None:
                try:
                    X = [_ltr_features(c, factors)]
                    if ltr_type == "xgb":
                        s_val = float(ltr_model.predict(X)[0])
                    else:
                        s_val = float(ltr_model.predict(X)[0])
                    rerank_mode = "ltr"
                except Exception:
                    s_val = base_score
            scored.append({"candidate": c, "score": s_val, "factors": factors})
        scored.sort(key=lambda x: x["score"], reverse=True)
        ce_enabled = str(os.environ.get("RECO_CROSS_ENCODER_ENABLED", "1")).strip().lower() in ("1", "true", "yes", "on")
        if ce_enabled and scored:
            ce_w = float(arm_w.get("cross", 0.60))
            for item in scored:
                ce = self._cross_encoder_score(q_text, item.get("candidate") or {})
                if ce <= 0:
                    continue
                item["score"] = float(item.get("score") or 0.0) + ce_w * float(ce)
                f = item.get("factors") or {}
                w = f.get("weights") or {}
                w["cross_encoder"] = round(ce_w * float(ce), 3)
                f["weights"] = w
                pos = f.get("positive") or []
                pos.append("+cross_encoder")
                f["positive"] = pos
                item["factors"] = f
            scored.sort(key=lambda x: x["score"], reverse=True)

        # Apply MMR diversification to reduce near-duplicates
        try:
            lam = float(os.environ.get("MMR_LAMBDA", "0.7") or 0.7)
        except Exception:
            lam = 0.7
        def _sim(a: Dict[str, Any], b: Dict[str, Any]) -> float:
            try:
                ca = a.get("candidate") or {}
                cb = b.get("candidate") or {}
                na = (ca.get("name") or "").lower()
                nb = (cb.get("name") or "").lower()
                if na and na == nb:
                    return 1.0
                # Same GPU model (e.g., both RTX 4060) → highly redundant result set
                sa = ca.get("specs") if isinstance(ca.get("specs"), dict) else {}
                sb = cb.get("specs") if isinstance(cb.get("specs"), dict) else {}
                gpu_a = str(sa.get("gpu_model") or "").lower().strip()
                gpu_b = str(sb.get("gpu_model") or "").lower().strip()
                if gpu_a and gpu_b and gpu_a == gpu_b:
                    return 0.65
                # Same brand + within 15% price bracket → moderately redundant
                brand_a = str(ca.get("brand") or "").lower().strip() or na[:6]
                brand_b = str(cb.get("brand") or "").lower().strip() or nb[:6]
                price_a = float(ca.get("price_cents") or 0)
                price_b = float(cb.get("price_cents") or 0)
                if brand_a and brand_a == brand_b and price_b > 0:
                    ratio = price_a / price_b
                    if 0.85 <= ratio <= 1.15:
                        return 0.35
                return 0.0
            except Exception:
                return 0.0
        mmr: List[Dict[str, Any]] = []
        pool = scored[:]
        while pool and len(mmr) < len(scored):
            if not mmr:
                mmr.append(pool.pop(0))
                continue
            # select item maximizing lambda*rel - (1-lambda)*max_sim
            best = None
            best_val = -9999.0
            for item in pool:
                rel = float(item.get("score") or 0.0)
                max_sim = 0.0
                for s in mmr:
                    max_sim = max(max_sim, _sim(item, s))
                val = lam * rel - (1.0 - lam) * max_sim
                if val > best_val:
                    best_val = val
                    best = item
            if best is None:
                mmr.append(pool.pop(0))
            else:
                pool.remove(best)
                mmr.append(best)
        scored = mmr
        # Add confidence based on rank distance from max
        if scored:
            max_score = scored[0]["score"] or 1.0
            for item in scored:
                item["confidence"] = round(max(0.1, min(1.0, item["score"] / max_score)), 3)
        # Emit rerank telemetry for admin snapshot and AB control dashboards.
        try:
            from src.app.observability.metrics import record_recommendation_rerank

            topk = scored[: min(5, len(scored))]
            rels = [float(x.get("score") or 0.0) for x in topk]
            # Deterministic proxy nDCG: normalized discounted score.
            dcg = 0.0
            idcg = 0.0
            ideal = sorted(rels, reverse=True)
            for i, rel in enumerate(rels):
                dcg += rel / math.log2(i + 2.0)
            for i, rel in enumerate(ideal):
                idcg += rel / math.log2(i + 2.0)
            ndcg_proxy = float(dcg / idcg) if idcg > 0 else 0.0
            # Deterministic proxy recall@k: fraction of top-k candidates that are in-stock.
            in_stock = 0
            for x in topk:
                cand = x.get("candidate") or {}
                if int(cand.get("stock") or 0) > 0:
                    in_stock += 1
            recall_proxy = float(in_stock / max(1, len(topk)))
            record_recommendation_rerank(
                mode=f"{rerank_mode}:{bandit_arm}",
                latency_s=max(0.0, time.perf_counter() - t0),
                ndcg_proxy_val=ndcg_proxy,
                recall_proxy_val=recall_proxy,
            )
        except Exception:
            pass
        return scored

    def build_prompt(self, candidates: List[Dict[str, Any]], constraints: Dict[str, Any]) -> Dict[str, Any]:
        # For future LLM integration; not used by the stub reranker.
        return {
            "system": PROMPT_CONTROL["system"],
            "format": PROMPT_CONTROL["format"],
            "constraints": constraints,
            "candidates": [{"sku": c["sku"], "name": c["name"], "price_cents": c["price_cents"]} for c in candidates],
        }

    def maybe_llm_rerank(self, uid: str, candidates: List[Dict[str, Any]], constraints: Dict[str, Any], use_llm: bool = False) -> List[Dict[str, Any]]:
        if not use_llm:
            return self.rerank_candidates(candidates, constraints)
        try:
            from src.app.services.llm import LLMOrchestrator
            llm = LLMOrchestrator()
            return llm.rerank_with_budget(uid, candidates, constraints) or candidates
        except Exception:
            return self.rerank_candidates(candidates, constraints)

    def log_decision(
        self,
        uid: str,
        query: str,
        retrieved_context: Dict[str, Any],
        proposal: Dict[str, Any],
        policy_version: str,
        flags: Dict[str, Any] | None = None,
        agent_name: str = "recommendation_agent",
        decision_id: str | None = None,
        tenant_id: str | None = None,
    ) -> str | None:
        flags = flags or {}
        sanitized_query = scrub_pii(query or "")
        input_payload = {
            "uid": uid,
            "uid_hash": hash_uid(uid),
            "user_query": sanitized_query,
            "query": sanitized_query,
            "query_length": len(query or ""),
            # Persist original query text for embedding-based audit
            "embedding_query_text": sanitized_query,
        }
        safe_context = security_sanitize(retrieved_context or {})
        # Apply detail level policy for persisted agent output
        detail_level = str(flags.get("LOG_DETAIL_LEVEL", "standard")).lower()
        if detail_level == "minimal":
            action_to_store: Dict[str, Any] = {
                "decision_mode": proposal.get("decision_mode"),
                "ranked_skus": proposal.get("ranked_skus", []),
            }
            reason_to_store = None
        else:
            action_to_store = proposal
            reason_to_store = proposal.get("rationale", "")
        # Attach evidence (top candidates) for RAGAS / auditability if available
        try:
            if isinstance(action_to_store, dict) and "ranked_skus" in action_to_store:
                # Pull candidate details from retrieved_context if present
                docs = []
                try:
                    cand_pool = (retrieved_context or {}).get("candidates") if isinstance(retrieved_context, dict) else None
                except Exception:
                    cand_pool = None
                if cand_pool and isinstance(cand_pool, list):
                    sku_to_item = {c.get("sku"): c for c in cand_pool if c.get("sku")}
                    top = []
                    for s in action_to_store.get("ranked_skus", [])[:5]:
                        if s in sku_to_item:
                            item = sku_to_item[s]
                            top.append({"sku": item.get("sku"), "name": item.get("name"), "price_cents": item.get("price_cents")})
                    if top:
                        action_to_store["evidence"] = top
        except Exception:
            pass
        # Use central decision_log to ensure tenant scoping and policy evaluation
        try:
            dec_id = central_log_decision(
                agent_name=agent_name,
                input_data=input_payload,
                retrieved_context=safe_context,
                proposed_action=action_to_store,
                agent_reasoning=reason_to_store or "",
                policy_version=policy_version,
                approval_required=False,
                execution_status="executed",
                decision_id=decision_id,
                tenant_id=tenant_id,
            )
            return dec_id
        except Exception:
            return None
