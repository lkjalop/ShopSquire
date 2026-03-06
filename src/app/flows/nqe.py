from __future__ import annotations

import re
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from src.app.rag.retrieve import Retriever
from src.app.services.decision_log import log_trace_event


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

        # ── University subject specialization ──
        if inp.detected_use_case == "university_general":
            questions.append(
                NextQuestion(
                    id="ask_university_subject",
                    text="What subject or field are you studying? This helps me match specs to your workload.",
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
                    text="What kind of games will you play? This determines the GPU level needed.",
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
                    text="What type of work will you mainly do? This helps me match the right specs.",
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
            # Prefer keeping coverage items first
            _keep_set = {'ask_budget', 'ask_budget_tier', 'ask_use_case', 'ask_platform', 'ask_brand_pref'}
            if inp.detected_use_case and 'university' in (inp.detected_use_case or '').lower():
                _keep_set.add('ask_university_subject')
            keep_ids = [q.id for q in out if q.id in _keep_set]
            result: List[NextQuestion] = []
            for q in out:
                if q.id in keep_ids and q not in result:
                    result.append(q)
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
