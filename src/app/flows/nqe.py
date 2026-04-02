from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from src.app.rag.retrieve import Retriever
from src.app.services.decision_log import log_trace_event


@lru_cache(maxsize=1)
def _load_use_case_kb() -> Dict[str, Any]:
    """Load data/use_case_kb.json once. Returns {} on any error."""
    _candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "use_case_kb.json"),
        os.path.join(os.getcwd(), "data", "use_case_kb.json"),
    ]
    for _path in _candidates:
        try:
            with open(os.path.normpath(_path), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            continue
    return {}


class NextQuestion(BaseModel):
    id: str
    text: str
    goal: str
    evidence_needed: List[str] = []
    stop_condition: Optional[str] = None
    source: str = "template"
    options: List[Dict[str, str]] = []  # optional quick-reply buttons


class NQEInput(BaseModel):
    intent: str
    product_category: str
    symptom: Optional[str] = None
    timeline_days: Optional[int] = None
    risk_score: float = 0.0
    missing_fields: List[str] = []
    tenant_id: Optional[str] = None
    template_variant: Optional[str] = None
    template_version: Optional[str] = None
    trace_id: Optional[str] = None
    query: Optional[str] = None
    previously_asked_ids: List[str] = []
    answered_fields: Dict[str, Any] = {}
    # Extracted structured facts from conversation (Layer 1 memory)
    facts: Dict[str, Any] = {}
    # Image context fields (populated when image is uploaded)
    has_image: bool = False
    image_identity_confidence: float = 1.0  # 0.0 = unknown, 1.0 = fully identified
    image_labels: List[str] = []
    detected_use_case: Optional[str] = None  # e.g. "university_general"
    # Chat history context for smarter follow-ups
    chat_history_summary: Optional[str] = None
    user_profile: Optional[Dict[str, Any]] = None  # logged-in user preferences
    # User profile preferences injected from episodic memory (returning customers)
    user_profile_prefs: Optional[Dict[str, Any]] = None
    detected_games: List[str] = []  # game titles mentioned in query
    detected_software: List[str] = []  # software names mentioned
    turn_intent: Optional[str] = None  # SEARCH | FILTER | EXPLAIN | COMPARE


# ── Game / software detection from query text ──
_GAME_PATTERNS: Dict[str, List[str]] = {
    "minecraft": [r"\bminecraft\b"],
    "fortnite": [r"\bfortnite\b"],
    "valorant": [r"\bvalorant\b"],
    "cs2": [r"\bcs\s?2\b", r"\bcounter[\s-]?strike\b"],
    "apex_legends": [r"\bapex\s?legends\b", r"\bapex\b"],
    "space_marines_2": [r"\bspace\s?marines?\s?2?\b", r"\bwarhammer\b"],
    "cyberpunk_2077": [r"\bcyberpunk\b"],
    "hogwarts_legacy": [r"\bhogwarts\b"],
    "baldurs_gate_3": [r"\bbaldur'?s?\s?gate\b", r"\bbg\s?3\b"],
    "elden_ring": [r"\belden\s?ring\b"],
    "league_of_legends": [r"\bleague\s?of\s?legends\b", r"\blol\b"],
    "gta_v": [r"\bgta\b"],
    "roblox": [r"\broblox\b"],
    "call_of_duty_warzone": [r"\bcall\s?of\s?duty\b", r"\bwarzone\b", r"\bcod\b"],
    "starfield": [r"\bstarfield\b"],
}

_SOFTWARE_PATTERNS: Dict[str, List[str]] = {
    "autocad": [r"\bautocad\b", r"\bauto\s?cad\b"],
    "solidworks": [r"\bsolidworks\b", r"\bsolid\s?works\b"],
    "adobe_premiere": [r"\bpremiere\b"],
    "blender": [r"\bblender\b"],
    "matlab": [r"\bmatlab\b"],
    "davinci_resolve": [r"\bdavinci\b", r"\bresolve\b"],
    "photoshop": [r"\bphotoshop\b"],
    "revit": [r"\brevit\b"],
    "docker": [r"\bdocker\b"],
    "android_studio": [r"\bandroid studio\b"],
    "xcode": [r"\bxcode\b"],
}


def detect_games_in_text(text: str) -> List[str]:
    """Return game slugs mentioned in text."""
    t = (text or "").lower()
    found = []
    for slug, patterns in _GAME_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t):
                found.append(slug)
                break
    return found


def detect_software_in_text(text: str) -> List[str]:
    """Return software slugs mentioned in text."""
    t = (text or "").lower()
    found = []
    for slug, patterns in _SOFTWARE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t):
                found.append(slug)
                break
    return found


def _detect_touch_screen_need(query: str, answered: Dict[str, Any]) -> bool:
    """Detect if user needs touch screen / pen input from query text."""
    q = (query or "").lower()
    touch_signals = [
        r"\btouch\s?screen\b", r"\bpen\s?input\b", r"\bstylus\b",
        r"\bnote[\s-]?taking\b", r"\bhandwrit", r"\bdraw\s?on\s?screen\b",
        r"\b2[\s-]?in[\s-]?1\b", r"\btablet\s?mode\b", r"\bdigit\w*\s?pen\b",
    ]
    return any(re.search(p, q) for p in touch_signals)


def _detect_corporate_subtype(query: str) -> Optional[str]:
    """Detect corporate work subtype from query."""
    q = (query or "").lower()
    if any(w in q for w in ["finance", "accounting", "excel", "spreadsheet", "power bi", "tableau", "sap", "bloomberg"]):
        return "office_finance"
    if any(w in q for w in ["executive", "travel", "presentation", "ceo", "cfo", "director", "boardroom"]):
        return "office_executive"
    if any(w in q for w in ["office", "corporate", "business", "admin", "clerical"]):
        return "office_general"
    return None


def _personalize_q(template: str, query_text: str, context: Optional[Dict[str, Any]] = None) -> str:
    """Inject query-derived context into a template question string.

    Pure string manipulation — no LLM, no latency.
    Returns the original template unchanged if no relevant context is found.
    """
    q = (query_text or "").lower()
    ctx = context or {}

    # Extract budget hint: "$1500", "$2,000", "2000 dollars", "under 1500"
    budget_hint: Optional[str] = None
    _budget_match = re.search(r"\$\s?(\d[\d,]+)", q)
    if _budget_match:
        try:
            budget_hint = f"${int(_budget_match.group(1).replace(',', '')):,}"
        except Exception:
            pass

    # Extract brand from query (common laptop brands)
    _BRANDS = ["lenovo", "dell", "hp", "asus", "acer", "apple", "microsoft", "samsung", "razer", "msi", "lg"]
    detected_brand: Optional[str] = next((b.title() for b in _BRANDS if b in q), None)
    if not detected_brand:
        detected_brand = str(ctx.get("brand") or "").strip().title() or None

    # --- Personalize gaming depth question ---
    if "what kind of games" in template.lower():
        prefix = ""
        if budget_hint:
            prefix = f"For a {budget_hint} setup, "
        elif detected_brand:
            prefix = f"For your {detected_brand}, "
        if prefix:
            return prefix + template[0].lower() + template[1:]
        return template

    # --- Personalize university subject question ---
    if "subject or field" in template.lower() or "field of study" in template.lower():
        prefix = ""
        if detected_brand:
            prefix = f"To match your {detected_brand} to your degree, "
            return prefix + "what field are you studying?"
        return template

    # --- Personalize corporate work type question ---
    if "type of work" in template.lower():
        if budget_hint:
            return f"For your {budget_hint} work laptop, what type of work will you mainly use it for?"
        return template

    return template


class NextQuestionEngine:
    def __init__(self, rag: Retriever, templates) -> None:
        self.rag = rag
        self.templates = templates

    def propose(self, inp: NQEInput) -> List[NextQuestion]:
        questions: List[NextQuestion] = []
        query_text = inp.query or ""
        turn_intent = str(inp.turn_intent or "").strip().upper()

        # ── Inject facts from structured state into answered_fields ──
        if inp.facts:
            for fk, fv in inp.facts.items():
                if fk not in inp.answered_fields and fv is not None:
                    inp.answered_fields[fk] = fv

        # ── Inject returning-customer profile prefs to skip redundant questions ──
        if inp.user_profile_prefs:
            prefs = inp.user_profile_prefs
            if prefs.get("budget_tier") and "budget" not in inp.answered_fields:
                tier_map = {"budget": 700, "mid": 1200, "premium": 2500}
                inp.answered_fields["budget_max"] = tier_map.get(prefs["budget_tier"], 1200)
            if prefs.get("typical_use_cases"):
                for uc in prefs["typical_use_cases"][:2]:
                    if "use_case" not in inp.answered_fields:
                        inp.answered_fields["use_case"] = uc
            if prefs.get("preferred_brands"):
                if "brand_preference" not in inp.answered_fields:
                    inp.answered_fields["brand_preference"] = prefs["preferred_brands"][0]

        # Filter out fields the user has already answered in prior turns
        if inp.answered_fields:
            _answered_keys = set()
            for k in inp.answered_fields:
                kl = str(k).lower()
                _answered_keys.add(kl)
                # Map applied constraint keys to missing-field names
                if kl in ("budget_min", "budget_max"):
                    _answered_keys.add("budget")
                    _answered_keys.add("price")
                elif kl in ("use_case", "use_case_tags"):
                    _answered_keys.add("use_case")
                    _answered_keys.add("intent")
                elif kl in ("gpu_preference",):
                    _answered_keys.add("specs")
                    _answered_keys.add("spec")
                elif kl in ("brand_preference",):
                    _answered_keys.add("brand_preference")
                    _answered_keys.add("brand")
                elif kl in ("gaming_tier", "game_titles"):
                    _answered_keys.add("gaming_depth")
                elif kl in ("corporate_subtype", "work_type"):
                    _answered_keys.add("corporate_subtype")
                elif kl in ("touch_screen", "pen_input"):
                    _answered_keys.add("touch_screen")
                elif kl in ("academic_field", "university_subject"):
                    _answered_keys.add("university_subject")
            inp.missing_fields = [f for f in (inp.missing_fields or [])
                                  if str(f).lower() not in _answered_keys]

        # Explanation turns should not ask budget again.
        if turn_intent == "EXPLAIN":
            inp.missing_fields = [
                f
                for f in (inp.missing_fields or [])
                if str(f).lower() not in {"budget", "price", "budget_min", "budget_max"}
            ]

        # ── Convergence detection: stop asking when enough high-signal slots filled ──
        _HIGH_SIGNAL_SLOTS = {
            "budget", "budget_min", "budget_max", "price",
            "use_case", "use_case_tags", "intent",
            "brand_preference", "brand",
            "gaming_depth", "gaming_tier", "game_titles",
            "specs", "spec", "gpu_preference",
            "corporate_subtype", "work_type",
            "touch_screen", "pen_input",
            "university_subject", "academic_field",
            "software_confirmed",
            "buyer_persona",
        }
        _CONVERGENCE_THRESHOLD = 3  # stop asking after 3 high-signal slots answered
        _answered_high = 0
        for k in (inp.answered_fields or {}):
            if str(k).lower() in _HIGH_SIGNAL_SLOTS:
                _answered_high += 1
        if _answered_high >= _CONVERGENCE_THRESHOLD:
            # Enough info to recommend — emit trace and return no questions
            if inp.trace_id:
                try:
                    log_trace_event(
                        trace_id=inp.trace_id,
                        event_type="nqe_convergence",
                        source_type="agent",
                        source_id="NQE_Engine",
                        target_type=None,
                        target_id=None,
                        payload={
                            "high_signal_slots_filled": _answered_high,
                            "threshold": _CONVERGENCE_THRESHOLD,
                            "answered_keys": list((inp.answered_fields or {}).keys())[:20],
                        },
                    )
                except Exception:
                    pass
            return []

        # ── Risk register context injection ──
        # When a risk domain is elevated, inject a contextual warning.
        try:
            from src.app.routers.admin_grc import get_latest_risk_bands
            _rr_bands = get_latest_risk_bands()
            _high_domains = [d for d, b in _rr_bands.items() if b in ("high", "critical")]
            if _high_domains and "risk_context_shown" not in inp.answered_fields:
                _domain_labels = {
                    "supplier_trust": "supplier verification",
                    "insider_threat": "identity verification",
                    "email_deliverability": "communication security",
                    "inventory_resilience": "stock availability",
                }
                _reasons = [_domain_labels.get(d, d.replace("_", " ")) for d in _high_domains[:2]]
                questions.append(
                    NextQuestion(
                        id="risk_context_notice",
                        text=f"Note: Due to current {' and '.join(_reasons)} conditions, this order may require additional verification steps.",
                        goal="risk_context",
                        evidence_needed=["none"],
                        source="risk_register",
                    )
                )
        except Exception:
            pass

        # ── Detect implicit context from query ──
        detected_games = inp.detected_games or detect_games_in_text(query_text)
        detected_software = inp.detected_software or detect_software_in_text(query_text)
        touch_needed = _detect_touch_screen_need(query_text, inp.answered_fields)
        corporate_sub = _detect_corporate_subtype(query_text)

        # ── Use-case KB auto-resolve: skip questions when game titles or software resolve specs ──
        try:
            _kb = _load_use_case_kb()
            if _kb:
                _title_map = _kb.get("game_title_to_use_case") or {}
                # Resolve use_case and gaming_tier from detected game titles
                if detected_games and "gaming_depth" not in inp.answered_fields:
                    _resolved_uc: Optional[str] = None
                    _resolved_tier: Optional[str] = None
                    for _slug in detected_games:
                        _slug_clean = _slug.replace("_", " ").lower()
                        for _title_kw, _uc_key in _title_map.items():
                            if _title_kw in _slug_clean or _slug_clean in _title_kw:
                                _resolved_uc = _uc_key
                                break
                        if _resolved_uc:
                            break
                    if _resolved_uc:
                        _uc_data = (_kb.get("use_cases") or {}).get(_resolved_uc) or {}
                        if _uc_data:
                            _resolved_tier = "aaa_heavy" if "aaa" in _resolved_uc else "casual"
                            inp.answered_fields.setdefault("gaming_depth", _resolved_tier)
                            inp.answered_fields.setdefault("use_case", "gaming")
                            if _uc_data.get("min_budget_usd"):
                                inp.answered_fields.setdefault("_kb_min_budget", _uc_data["min_budget_usd"])
                            if _uc_data.get("min_gpu_examples"):
                                inp.answered_fields.setdefault("_kb_min_gpu", _uc_data["min_gpu_examples"][0])
                # Resolve use_case from detected software names
                if detected_software and "use_case" not in inp.answered_fields:
                    _sw_uc_map = {
                        "autocad": "student_university", "solidworks": "student_university",
                        "revit": "student_university", "matlab": "student_university",
                        "adobe_premiere": "content_creator", "davinci_resolve": "content_creator",
                        "blender": "content_creator", "photoshop": "photo_editing",
                        "docker": "professional_developer", "android_studio": "professional_developer",
                        "xcode": "professional_developer",
                    }
                    for _sw in detected_software:
                        _sw_uc = _sw_uc_map.get(_sw)
                        if _sw_uc:
                            inp.answered_fields.setdefault("use_case", _sw_uc)
                            _sw_uc_data = (_kb.get("use_cases") or {}).get(_sw_uc) or {}
                            if _sw_uc_data.get("min_ram_gb"):
                                inp.answered_fields.setdefault("_kb_min_ram_gb", _sw_uc_data["min_ram_gb"])
                            break
        except Exception:
            pass

        # Optional slot unification via recommendation analyzer
        try:
            if (not inp.missing_fields) and inp.query:
                from src.app.services.recommendations import RecommendationService
                analyzer = RecommendationService()
                analysis = analyzer.analyze_query(inp.query)
                slots = analysis.get("slots") or {}
                followups = analysis.get("followups") or []
                derived_missing: List[str] = []
                if not slots.get("price_min") and not slots.get("price_max") and not slots.get("budget"):
                    derived_missing.append("budget")
                if not (slots.get("specs") or {}).get("ram_gb_min"):
                    derived_missing.append("specs")
                if not analysis.get("entities", {}).get("use_case"):
                    derived_missing.append("use_case")
                if not (analysis.get("entities", {}).get("brands")):
                    derived_missing.append("brand_preference")
                # Merge with provided missing_fields without duplicates
                inp.missing_fields = list({*(inp.missing_fields or []), *derived_missing})
                # Emit trace for learning loop
                if inp.trace_id:
                    try:
                        log_trace_event(
                            trace_id=inp.trace_id,
                            event_type="nqe_slots_unified",
                            source_type="agent",
                            source_id="NQE_Engine",
                            target_type="system",
                            target_id=None,
                            payload={"derived_missing": derived_missing, "followups": followups[:3]},
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        if "order_id" in inp.missing_fields:
            questions.append(
                NextQuestion(
                    id="ask_order_id",
                    text="Could you share the order number or the email/phone used at checkout?",
                    goal="clarify_details",
                    evidence_needed=["none"],
                )
            )

        if "amount" in inp.missing_fields:
            questions.append(
                NextQuestion(
                    id="ask_amount",
                    text="Do you remember the purchase amount (approximate is fine)?",
                    goal="clarify_details",
                    evidence_needed=["none"],
                )
            )

        # ── Receipt / serial verification gate ──
        # Triggers when fraud risk is elevated, item value is high, or CV can't identify the product.
        _item_value = float(inp.answered_fields.get("item_value") or inp.answered_fields.get("price") or 0)
        _needs_receipt = (
            inp.risk_score > 50
            or inp.image_identity_confidence < 0.6
            or _item_value > 500
        )
        _receipt_not_yet_asked = (
            "receipt_verification" not in inp.previously_asked_ids
            and "receipt_uploaded" not in inp.answered_fields
            and "serial_confirmed" not in inp.answered_fields
        )
        _is_return_or_support = str(inp.intent or "").lower() in (
            "return_request", "warranty_claim", "damage_report", "support", "order_issue_report"
        )
        if _needs_receipt and _receipt_not_yet_asked and _is_return_or_support:
            questions.append(
                NextQuestion(
                    id="receipt_verification",
                    text=(
                        "To process your claim, please upload your purchase receipt "
                        "or a photo showing the device's serial number label "
                        "(usually on the bottom of the unit or in Settings → About)."
                    ),
                    goal="verify_purchase",
                    evidence_needed=["receipt_or_serial"],
                    source="fraud_gate",
                    options=[
                        {"label": "Upload receipt photo", "value": "receipt_photo"},
                        {"label": "Show serial number label", "value": "serial_label"},
                        {"label": "I don't have these right now", "value": "no_proof"},
                    ],
                )
            )

        # ── Image-aware questions ──
        if inp.has_image and inp.image_identity_confidence < 0.6:
            questions.append(
                NextQuestion(
                    id="ask_image_model",
                    text="I can see the product in your photo but couldn't identify the exact model. Could you share the model number (usually on the bottom label or settings screen)?",
                    goal="clarify_product_identity",
                    evidence_needed=["model_number"],
                    source="image_context",
                )
            )

        # ── High school hobby/extracurricular probe ──
        # Fire when use_case = high_school AND the user hasn't mentioned gaming/editing/
        # music yet AND we haven't already asked.  One question routes a $699 mainstream
        # pick to a $899 creator/gaming spec without requiring the user to know what RAM
        # or GPU they need.
        _hs_probe_not_asked = "high_school_activity" not in set(
            str(k).lower() for k in (inp.answered_fields or {})
        )
        _no_activity_signal = not any(
            w in (query_text or "").lower()
            for w in ("gaming", "game", "video edit", "editing", "music", "coding", "code", "design", "art", "graphics")
        )
        if (
            inp.detected_use_case in ("high_school", "student", "high_schooler")
            and _hs_probe_not_asked
            and _no_activity_signal
        ):
            questions.append(
                NextQuestion(
                    id="ask_high_school_activity",
                    text=_personalize_q(
                        "Any hobbies or after-school activities that need the laptop? "
                        "This helps us pick the right specs without overspending.",
                        query_text,
                    ),
                    goal="refine_use_case",
                    evidence_needed=["high_school_activity"],
                    source="use_case_disambiguation",
                    options=[
                        {"label": "School notes / browsing only — keep it light", "value": "high_school_basic"},
                        {"label": "Casual gaming (Minecraft, Roblox, Fortnite)", "value": "gaming_light"},
                        {"label": "Video editing / YouTube / content creation", "value": "content_creator"},
                        {"label": "Music production / audio software", "value": "music_production"},
                        {"label": "Coding / programming projects", "value": "engineering_student"},
                        {"label": "Digital art / graphic design", "value": "design_student"},
                    ],
                )
            )

        # ── University subject specialization ──
        if inp.detected_use_case == "university_general":
            questions.append(
                NextQuestion(
                    id="ask_university_subject",
                    text=_personalize_q("What subject or field are you studying? This helps me match specs to your workload.", query_text),
                    goal="refine_use_case",
                    evidence_needed=["academic_field"],
                    source="use_case_disambiguation",
                    options=[
                        {"label": "Computer Science / IT", "value": "computer_science_student"},
                        {"label": "Engineering / CAD", "value": "engineering_student"},
                        {"label": "Data Science / ML", "value": "data_science_student"},
                        {"label": "Design / Visual Arts", "value": "design_student"},
                        {"label": "Architecture", "value": "architecture_student"},
                        {"label": "Medical / Health Sciences", "value": "medical_student"},
                        {"label": "Law", "value": "law_student"},
                        {"label": "General Studies / Arts / Humanities", "value": "university_general"},
                    ],
                )
            )

        # ── Gaming depth question — what kind of games? ──
        _gaming_detected = any(
            w in (query_text or "").lower()
            for w in ["gaming", "game", "gamer", "play games", "fps", "esports"]
        )
        _gaming_not_yet_asked = "gaming_depth" not in set(
            str(k).lower() for k in (inp.answered_fields or {})
        )
        if _gaming_detected and _gaming_not_yet_asked and not detected_games:
            questions.append(
                NextQuestion(
                    id="ask_gaming_depth",
                    text=_personalize_q("What kind of games will you play? This determines the GPU level needed.", query_text),
                    goal="refine_gaming_tier",
                    evidence_needed=["game_titles", "gaming_tier"],
                    source="use_case_disambiguation",
                    options=[
                        {"label": "Light (Minecraft, Roblox, LoL)", "value": "gaming_light"},
                        {"label": "Casual (Fortnite, Apex, Valorant at 60fps)", "value": "gaming_casual"},
                        {"label": "Competitive Esports (CS2, Valorant at 144fps+)", "value": "gaming_competitive"},
                        {"label": "AAA Heavy (Cyberpunk, Space Marines 2, Starfield)", "value": "gaming_aaa_heavy"},
                    ],
                )
            )
        # If specific game was mentioned, auto-resolve tier — no need to ask
        if detected_games and inp.trace_id:
            try:
                log_trace_event(
                    trace_id=inp.trace_id,
                    event_type="nqe_games_detected",
                    source_type="agent",
                    source_id="NQE_Engine",
                    target_type=None,
                    target_id=None,
                    payload={"detected_games": detected_games},
                )
            except Exception:
                pass

        # ── Corporate work type question ──
        _corporate_detected = any(
            w in (query_text or "").lower()
            for w in ["office", "corporate", "work", "business", "professional"]
        )
        _corp_not_yet_asked = "corporate_subtype" not in set(
            str(k).lower() for k in (inp.answered_fields or {})
        )
        if _corporate_detected and _corp_not_yet_asked and not corporate_sub:
            questions.append(
                NextQuestion(
                    id="ask_corporate_work_type",
                    text=_personalize_q("What type of work will you mainly do? This helps me match the right specs.", query_text),
                    goal="refine_use_case",
                    evidence_needed=["work_type"],
                    source="use_case_disambiguation",
                    options=[
                        {"label": "General Office (Email, Teams, Documents)", "value": "office_general"},
                        {"label": "Finance / Data Analysis (Excel, Power BI, SAP)", "value": "office_finance"},
                        {"label": "Executive / Travel (Presentations, Premium Build)", "value": "office_executive"},
                    ],
                )
            )

        # ── Touch screen / pen input question ──
        if touch_needed and "touch_screen" not in set(
            str(k).lower() for k in (inp.answered_fields or {})
        ):
            questions.append(
                NextQuestion(
                    id="ask_touch_screen_type",
                    text="Do you need a touch screen with pen/stylus support for handwriting or drawing?",
                    goal="refine_form_factor",
                    evidence_needed=["touch_screen", "pen_input"],
                    source="use_case_disambiguation",
                    options=[
                        {"label": "Yes — touch + pen for notes/drawing", "value": "note_taking_student"},
                        {"label": "Touch screen only (no pen)", "value": "touch_only"},
                        {"label": "No — standard laptop is fine", "value": "no_touch"},
                    ],
                )
            )

        # ── Software-specific question when software is detected ──
        if detected_software and "software_confirmed" not in set(
            str(k).lower() for k in (inp.answered_fields or {})
        ):
            sw_names = []
            try:
                from src.app.services.use_case_advisor import get_software_specs
                for slug in detected_software[:3]:
                    sw = get_software_specs(slug)
                    if sw:
                        sw_names.append(sw.get("label", slug))
            except Exception:
                sw_names = detected_software[:3]
            if sw_names:
                questions.append(
                    NextQuestion(
                        id="ask_software_confirm",
                        text=f"I noticed you mentioned {', '.join(sw_names)}. Want me to match specs to run {'it' if len(sw_names) == 1 else 'them'} smoothly?",
                        goal="confirm_software_requirements",
                        evidence_needed=["software_confirmed"],
                        source="software_detection",
                        options=[
                            {"label": "Yes — match specs for this software", "value": "confirm"},
                            {"label": "No — just browsing", "value": "skip"},
                        ],
                    )
                )

        # ── Leverage user profile from logged-in sessions ──
        if inp.user_profile:
            prefs = inp.user_profile
            # If user has past purchase data, skip questions we can infer
            if prefs.get("preferred_brand") and "brand_preference" in (inp.missing_fields or []):
                inp.missing_fields = [f for f in inp.missing_fields if f != "brand_preference"]
            if prefs.get("budget_tier") and "budget" in (inp.missing_fields or []):
                inp.missing_fields = [f for f in inp.missing_fields if f != "budget"]

        # Prioritize templates that correspond to missing_fields first
        # Template governance: allow per-tenant overrides if templates support it
        raw_templates = self.templates.get_templates(
            inp.intent,
            inp.product_category,
            tenant_id=inp.tenant_id,
            variant=inp.template_variant,
            version=inp.template_version,
            trace_id=inp.trace_id,
        )
        if inp.trace_id:
            try:
                template_meta = {}
                if raw_templates:
                    template_meta = {
                        "variant": raw_templates[0].get("variant"),
                        "version": raw_templates[0].get("version"),
                    }
                log_trace_event(
                    trace_id=inp.trace_id,
                    event_type="nqe_template_selection",
                    source_type="agent",
                    source_id="NQE_Engine",
                    target_type=None,
                    target_id=None,
                    payload=template_meta,
                )
            except Exception:
                pass
        _embedder = getattr(self.rag, "embedder", None)

        def _embed_text_safe(text: str) -> Dict[str, float]:
            if not text or not str(text).strip() or _embedder is None:
                return {}
            fn = getattr(_embedder, "embed_text", None)
            if not callable(fn):
                return {}
            try:
                vec = fn(text)
                return vec if isinstance(vec, dict) else {}
            except Exception:
                return {}

        def _cosine_safe(a: Dict[str, float], b: Dict[str, float]) -> float:
            if not a or not b or _embedder is None:
                return 0.0
            fn = getattr(_embedder, "cosine", None)
            if not callable(fn):
                return 0.0
            try:
                return float(fn(a, b))
            except Exception:
                return 0.0

        def relevance(tmpl: dict) -> float:
            """Return embedding cosine similarity between user query and template text.

            Falls back to a keyword-based score when the template has no text.
            The existing keyword boost is added as a fractional tie-breaker so that
            two templates with equal cosine scores are still ordered by field coverage.
            """
            tmpl_text = str(tmpl.get("text") or tmpl.get("id") or "")
            if tmpl_text and _nqe_query_vec:
                tmpl_vec = _embed_text_safe(tmpl_text)
                base = _cosine_safe(_nqe_query_vec, tmpl_vec)
            else:
                base = 0.0
            # Add keyword boost (0–6 range) scaled to a small decimal so it only breaks ties
            id_low = (tmpl.get("id") or "").lower()
            kw = 0
            for mf in (inp.missing_fields or []):
                mfl = str(mf or "").lower()
                if mfl in ("budget", "price") and "budget" in id_low:
                    kw += 2
                if mfl in ("use_case", "intent") and ("use_case" in id_low or "platform" in id_low):
                    kw += 2
                if mfl in ("brand_preference", "brand") and "brand" in id_low:
                    kw += 2
                if mfl in ("specs", "spec") and "spec" in id_low:
                    kw += 1
            return base + kw * 0.01

        # Build a single query vector once for all template comparisons
        _nqe_query_parts = " ".join(filter(None, [
            inp.query or "",
            inp.intent or "",
            inp.product_category or "",
            " ".join(str(m) for m in (inp.missing_fields or [])),
        ]))
        _nqe_query_vec = _embed_text_safe(_nqe_query_parts)
        prioritized = sorted(raw_templates, key=lambda t: (-relevance(t), t.get("id") or ""))
        # Ensure coverage: include one question per key missing field before capping
        def find_tmpl(ids: List[str]) -> Optional[dict]:
            idset = {i for i in ids if i}
            for t in prioritized:
                if t.get('id') in idset:
                    return t
            return None
        coverage: List[dict] = []
        mfs = [str(m or '').lower() for m in (inp.missing_fields or [])]
        if any(m in ('budget','price') for m in mfs):
            t = find_tmpl(['ask_budget_tier','ask_budget'])
            if t: coverage.append(t)
        if any(m in ('use_case','intent') for m in mfs):
            t = find_tmpl(['ask_use_case','ask_platform'])
            if t: coverage.append(t)
        if any(m in ('brand_preference','brand') for m in mfs):
            t = find_tmpl(['ask_brand_pref'])
            if t: coverage.append(t)
        # Add remaining prioritized templates after coverage (preserve order), then convert
        seen_ids = {t.get('id') for t in coverage}
        ordered = coverage + [t for t in prioritized if t.get('id') not in seen_ids]
        for tmpl in ordered:
            questions.append(NextQuestion(**tmpl))

        rag_hits = self.rag.retrieve(f"{inp.product_category} {inp.intent} troubleshooting", tenant_id=inp.tenant_id)
        # Filter RAG by source reliability if configured
        min_rel = 0.0
        try:
            import os
            min_rel = float(os.environ.get("NQE_RAG_MIN_RELIABILITY", "0") or 0.0)
        except Exception:
            min_rel = 0.0
        filtered_hits = []
        for h in rag_hits or []:
            try:
                rel = float(h.meta.get("reliability", 1.0) or 1.0)
            except Exception:
                rel = 1.0
            if rel >= min_rel:
                filtered_hits.append(h)
        if rag_hits and inp.trace_id:
            try:
                log_trace_event(
                    trace_id=inp.trace_id,
                    event_type="rag_retrieved",
                    source_type="agent",
                    source_id="RAG_Retriever",
                    target_type="system",
                    target_id=None,
                    payload={
                        "query": f"{inp.product_category} {inp.intent} troubleshooting",
                        "chunks": [
                            {"doc_id": h.doc_id, "chunk_id": h.chunk_id, "score": h.score, "source": h.meta.get("source")}
                            for h in rag_hits
                        ],
                    },
                )
            except Exception:
                pass
        for hit in filtered_hits[:2]:
            questions.append(
                NextQuestion(
                    id=f"rag_{hit.chunk_id}",
                    text=f"Based on policy guidance: {hit.text}",
                    goal="clarify_details",
                    evidence_needed=["none"],
                    source="rag",
                )
            )

        # Risk-aware suggestion to run quick security/policy checks when signals warrant it
        try:
            if float(inp.risk_score or 0.0) >= 0.7:
                questions.append(
                    NextQuestion(
                        id="security_check",
                        text="Would you like me to run quick security/policy checks on this request?",
                        goal="policy_suggestion",
                        evidence_needed=["none"],
                        source="template",
                    )
                )
        except Exception:
            pass

        deduped: Dict[str, NextQuestion] = {}
        for q in questions:
            if turn_intent == "EXPLAIN" and str(q.id or "").strip().lower() in {"ask_budget", "ask_budget_tier"}:
                continue
            # Skip questions that were already asked in prior turns
            if q.id in (inp.previously_asked_ids or []):
                continue
            deduped[q.id] = q

        # Risk-aware cap: ask fewer questions when risk is high to reduce friction.
        cap = 3 if inp.risk_score < 0.7 else 2
        # Keep guaranteed coverage even if > cap by trimming after ensuring at least one per missing field group
        out = list(deduped.values())
        if len(out) > cap:
            # ── Prioritised keep set — domain-specific context before generic budget ──
            # Order matters: we prefer questions that narrow the use case first,
            # because knowing the use case often determines the right budget tier.
            _keep_set: set[str] = set()

            # 1. Use-case disambiguation is always highest priority
            if inp.detected_use_case and 'university' in (inp.detected_use_case or '').lower():
                _keep_set.add('ask_university_subject')
            if _gaming_detected and not detected_games:
                # Gaming detected in query but no specific game named → ask what kind of games first
                _keep_set.add('ask_gaming_depth')
            if detected_software:
                _keep_set.add('ask_software_confirm')
            if corporate_sub is None and any(
                w in (inp.query or '').lower()
                for w in ['office', 'corporate', 'work', 'business', 'professional']
            ):
                _keep_set.add('ask_corporate_work_type')
            if touch_needed:
                _keep_set.add('ask_touch_screen_type')
            if inp.has_image and inp.image_identity_confidence < 0.6:
                _keep_set.add('ask_image_model')

            # 2. Generic slot coverage comes after domain-specific questions
            _keep_set.update({'ask_budget', 'ask_budget_tier', 'ask_use_case', 'ask_platform', 'ask_brand_pref'})

            # Build result in priority order: domain-specific first, then generic slots
            _domain_priority = [
                'ask_university_subject', 'ask_gaming_depth', 'ask_software_confirm',
                'ask_corporate_work_type', 'ask_touch_screen_type', 'ask_image_model',
            ]
            _generic_priority = ['ask_budget_tier', 'ask_budget', 'ask_use_case', 'ask_platform', 'ask_brand_pref']
            _ordered_priority = _domain_priority + _generic_priority
            # Map each template id to the missing-field it covers so we never
            # consume two cap slots on the same field (e.g. ask_budget_tier AND
            # ask_budget both count for 'budget', leaving no room for brand_pref).
            _template_field_map: dict[str, str] = {
                'ask_budget_tier': 'budget',
                'ask_budget': 'budget',
                'ask_use_case': 'use_case',
                'ask_platform': 'use_case',
                'ask_brand_pref': 'brand_preference',
                'ask_specs': 'specs',
            }
            _covered_fields: set[str] = set()
            _out_by_id = {q.id: q for q in out}
            result: List[NextQuestion] = []
            for pid in _ordered_priority:
                if pid not in _keep_set or pid not in _out_by_id:
                    continue
                field = _template_field_map.get(pid)
                if field and field in _covered_fields:
                    continue  # already have a question for this field
                result.append(_out_by_id[pid])
                if field:
                    _covered_fields.add(field)
                if len(result) >= cap:
                    break
            if len(result) < cap:
                for q in out:
                    if q not in result:
                        result.append(q)
                    if len(result) >= cap:
                        break
            # Log proposed followups for learning loop
            if inp.trace_id:
                try:
                    log_trace_event(
                        trace_id=inp.trace_id,
                        event_type="nqe_followups_proposed",
                        source_type="agent",
                        source_id="NQE_Engine",
                        target_type=None,
                        target_id=None,
                        payload={"question_ids": [q.id for q in result[:cap]]},
                    )
                except Exception:
                    pass
            return result[:cap]
        return out
