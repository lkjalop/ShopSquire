"""NQE question selection pipeline helpers.

Extracted from the recommend.py monolith (strangler-fig pattern).
Contains question filtering, deduplication, fatigue detection, persona fallback,
and intent-specific question bank logic.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • question_slot_from_id() — maps question IDs to semantic slots.
  • normalize_recent_nqe_asked() — normalizes raw NQE history entries.
  • contradicted_slots() — detects which constraints the user is contradicting.
  • question_fatigue_filter() — prevents re-asking recent questions.
  • apply_persona_confidence_fallback() — inserts broad use-case question when
    persona confidence is too low.
  • dedupe_next_questions_for_render() — final dedup/slot guard.
  • question_flow() — route to student/office/creator/general flow.
  • apply_intent_specific_question_bank() — adapt question wording per flow.

ADAPTER (product-type-specific):
  • append_gpu_disambiguation_question() — electronics-specific GPU tier questions.
    Phase 2: generalize to profile-driven capability disambiguation.
  • append_standard_nqe_options() — electronics-specific budget tiers and use-case
    options. Phase 2: read option sets from StoreProfile["nqe_option_sets"].
  • _TECHY_QUERY_TOKENS — GPU/hardware tokens for "techy query" detection.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Tuple

from src.app.services.recommend_budget_parsing import classify_budget_bracket

# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific techy query tokens
# ═══════════════════════════════════════════════════════════════════════════════

_TECHY_QUERY_TOKENS = (
    "gpu",
    "rtx",
    "radeon",
    "cuda",
    "vram",
    "ram",
    "ssd",
    "tb",
    "i7",
    "i9",
    "ryzen",
    "threadripper",
    "cores",
    "ghz",
    "fps",
    "gaming",
    "gamer",
    "esports",
    "144hz",
    "240hz",
)


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Question slot mapping and normalization
# ═══════════════════════════════════════════════════════════════════════════════


def question_slot_from_id(question_id: str | None) -> str:
    qid = str(question_id or "").strip().lower()
    if qid in {"ask_budget", "ask_budget_tier"}:
        return "budget"
    if qid in {
        "ask_use_case",
        "ask_platform",
        "ask_university_subject",
        "ask_corporate_work_type",
        "ask_gaming_depth",
        "ask_high_school_activity",
        "ask_software_confirm",
    }:
        return "use_case"
    if qid in {"ask_brand_pref", "ask_brand"}:
        return "brand_preference"
    if qid in {"ask_gpu_preference", "ask_specs", "ask_requirements", "ask_system_requirements"}:
        return "specs"
    if qid in {"ask_touch_screen_type"}:
        return "touch_form_factor"
    if qid in {"ask_image_model", "reupload_clean_image"}:
        return "image_quality"
    return "unknown"


def normalize_recent_nqe_asked(raw: Any) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            qid = str(item.get("id") or item.get("question_id") or "").strip().lower()
            if not qid:
                continue
            try:
                turn = int(item.get("turn") or 0)
            except Exception:
                turn = 0
            slot = str(item.get("slot") or question_slot_from_id(qid)).strip().lower()
            out.append({"id": qid, "slot": slot or "unknown", "turn": turn})
        else:
            qid = str(item or "").strip().lower()
            if qid:
                out.append({"id": qid, "slot": question_slot_from_id(qid), "turn": 0})
    return out[-60:]


def contradicted_slots(
    *,
    query: str | None,
    constraints: Dict[str, Any],
    prior_constraints: Dict[str, Any] | None,
    nqe_selection_applied: Dict[str, Any] | None,
) -> set[str]:
    q = str(query or "").lower()
    prior = prior_constraints if isinstance(prior_constraints, dict) else {}
    applied = nqe_selection_applied if isinstance(nqe_selection_applied, dict) else {}
    contradicted: set[str] = set()

    if "budget_min" in applied or "budget_max" in applied:
        contradicted.add("budget")
    if "use_case" in applied or "use_case_tags" in applied:
        contradicted.add("use_case")
    if "gpu_preference" in applied:
        contradicted.add("specs")

    try:
        old_min = prior.get("budget_min")
        old_max = prior.get("budget_max")
        new_min = constraints.get("budget_min")
        new_max = constraints.get("budget_max")
        if (new_min is not None or new_max is not None) and (old_min != new_min or old_max != new_max):
            contradicted.add("budget")
    except Exception:
        pass
    try:
        if prior.get("brands") is not None and list(prior.get("brands") or []) != list(constraints.get("brands") or []):
            contradicted.add("brand_preference")
    except Exception:
        pass
    try:
        if prior.get("specs") is not None and list(prior.get("specs") or []) != list(constraints.get("specs") or []):
            contradicted.add("specs")
    except Exception:
        pass
    try:
        if prior.get("use_case") and prior.get("use_case") != constraints.get("use_case"):
            contradicted.add("use_case")
    except Exception:
        pass

    contradiction_cues = ("actually", "instead", "changed", "change", "not anymore", "rather", "switch")
    if any(c in q for c in contradiction_cues):
        if any(x in q for x in ("budget", "$", "under", "between")):
            contradicted.add("budget")
        if any(x in q for x in ("use case", "for work", "for school", "for uni", "for office", "gaming", "rendering")):
            contradicted.add("use_case")
        if any(x in q for x in ("brand", "apple", "dell", "lenovo", "asus", "hp", "msi")):
            contradicted.add("brand_preference")
        if any(x in q for x in ("gpu", "ram", "ssd", "storage", "cpu", "cores")):
            contradicted.add("specs")
    return contradicted


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — NQE input state (vertical-agnostic). Single source of truth for the
# fatigue-filtered asked-id list + the answered-fields bridge, shared by BOTH NQE
# paths in recommend.py (the open-ended early-return path and the post-retrieval
# run_recommend_nqe_stage) so they cannot drift.
# ═══════════════════════════════════════════════════════════════════════════════


def build_nqe_asked_and_answered(
    *,
    structured_state: Dict[str, Any],
    kv: Dict[str, Any],
    constraints: Dict[str, Any],
    recent_asked_entries: List[Dict[str, Any]] | None,
    current_turn: int,
    fatigue_turns: int,
    contradicted_slots: set[str],
    use_case_needs_nqe_refinement: Callable[[Any], bool],
) -> Tuple[List[str], Dict[str, Any]]:
    """Return (previously_asked_ids, answered_fields) for an NQEInput.

    asked_ids = persisted nqe_asked_ids + recent-asked entries that are still within the
    fatigue window and not on a contradicted slot. answered_fields = persisted
    nqe_answered_fields bridged with text-extracted constraints (budget/use_case/brand/gpu).
    """
    ss = structured_state if isinstance(structured_state, dict) else {}
    kvd = kv if isinstance(kv, dict) else {}
    asked: List[str] = list(ss.get("nqe_asked_ids") or kvd.get("nqe_asked_ids") or [])
    for entry in recent_asked_entries or []:
        turn = int((entry or {}).get("turn") or 0)
        slot = str((entry or {}).get("slot") or "").strip().lower()
        qid = str((entry or {}).get("id") or "").strip().lower()
        if (
            qid
            and turn > 0
            and (current_turn - turn) <= fatigue_turns
            and slot not in contradicted_slots
            and qid not in asked
        ):
            asked.append(qid)
    answered: Dict[str, Any] = dict(ss.get("nqe_answered_fields") or kvd.get("nqe_answered_fields") or {})
    for key, value in (
        ("budget_min", constraints.get("budget_min")),
        ("budget_max", constraints.get("budget_max")),
        ("use_case", constraints.get("use_case")),
        ("brand_preference", (constraints.get("brands") or [None])[0]),
        ("gpu_preference", constraints.get("gpu_preference")),
    ):
        if key == "use_case" and use_case_needs_nqe_refinement(value):
            continue
        if value and not answered.get(key):
            answered[key] = value
    return asked, answered


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Question fatigue filtering (vertical-agnostic)
# ═══════════════════════════════════════════════════════════════════════════════


def question_fatigue_filter(
    questions: list[dict] | None,
    *,
    recent_asked: list[dict] | None,
    current_turn: int,
    window_turns: int,
    contradicted_slots_set: set[str] | None = None,
) -> tuple[list[dict], list[str]]:
    out = [dict(q) for q in (questions or []) if isinstance(q, dict)]
    if not out:
        return [], []
    contradicted = {str(s or "").strip().lower() for s in (contradicted_slots_set or set()) if str(s or "").strip()}
    recent = normalize_recent_nqe_asked(recent_asked or [])
    blocked: list[str] = []
    filtered: list[dict] = []
    seen_slots: set[str] = set()
    for q in out:
        qid = str(q.get("id") or "").strip().lower()
        qtext = str(q.get("text") or "").lower()
        if flow == "creator" and "what kind of games" in qtext:
            q["text"] = "Which development or creative tools will you run, and how complex are the projects?"
            q["goal"] = "resolve_software_workload"
            q["options"] = [
                {"id": "tools_entry", "label": "Learning / small projects"},
                {"id": "tools_realtime_3d", "label": "Real-time 3D / engine editor"},
                {"id": "tools_heavy", "label": "Large scenes / heavy rendering and builds"},
            ]
        slot = question_slot_from_id(qid)
        q["question_slot"] = slot
        asked_recently = False
        for e in recent:
            turn = int(e.get("turn") or 0)
            same_slot = str(e.get("slot") or "").strip().lower() == slot
            same_qid = str(e.get("id") or "").strip().lower() == qid
            if not (same_slot or same_qid):
                continue
            if turn > 0 and (current_turn - turn) <= max(1, int(window_turns)):
                asked_recently = True
                break
        if asked_recently and slot not in contradicted:
            blocked.append(qid or slot)
            continue
        if slot in seen_slots and slot not in contradicted:
            continue
        seen_slots.add(slot)
        filtered.append(q)
    return filtered, blocked


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Persona confidence fallback
# ═══════════════════════════════════════════════════════════════════════════════


def apply_persona_confidence_fallback(
    questions: list[dict] | None,
    *,
    persona: str | None,
    persona_confidence: float | None,
    use_case_known: bool = False,
) -> list[dict]:
    out = [dict(q) for q in (questions or []) if isinstance(q, dict)]
    if not out:
        return out
    # NEVER re-ask "what will you mainly use it for" when the session already KNOWS the use-case
    # (constraints/answered fields) — low persona confidence is not a license to re-interrogate a buyer
    # who already answered; that redundancy was the live complaint ("I already said gaming").
    if use_case_known:
        # also strip any ask_use_case already present (an empty list is CORRECT — nothing left to ask)
        return [q for q in out if str((q or {}).get("id") or "").strip().lower() != "ask_use_case"]
    conf = float(persona_confidence or 0.0)
    min_conf = float(os.getenv("PERSONA_CONFIDENCE_MIN", "0.34") or 0.34)
    if conf >= min_conf:
        return out
    # Vertical-blind: the disambiguation question + options come from the active StoreProfile
    # (slot nqe_use_case_fallback_question). The neutral inline default is a safe last resort if a
    # profile lacks the slot — it carries no electronics flavour.
    spec: dict = {}
    try:
        from src.app.platform.store_profile import profile_slot
        cand = profile_slot("nqe_use_case_fallback_question", default=None)
        if isinstance(cand, dict) and str(cand.get("text") or "").strip():
            spec = cand
    except Exception:
        spec = {}
    fallback = {
        "id": "ask_use_case",
        "text": str(spec.get("text") or "To help narrow it down, what will you mainly use this for?"),
        "goal": "resolve_use_case",
        "question_slot": "use_case",
        "options": list(spec.get("options") or [
            {"id": "use_case_primary", "label": "Everyday / general use"},
            {"id": "use_case_specialised", "label": "Specialised / professional use"},
        ]),
    }
    existing_ids = {str((q or {}).get("id") or "").strip().lower() for q in out}
    if "ask_use_case" not in existing_ids:
        out.insert(0, fallback)
    else:
        out = [fallback if str((q or {}).get("id") or "").strip().lower() == "ask_use_case" else q for q in out]
    return out[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Grounding residual question injection
# ═══════════════════════════════════════════════════════════════════════════════


def inject_grounding_residual_question(
    questions: list[dict] | None, constraints: dict | None
) -> list[dict]:
    rq = (constraints or {}).get("_identity_residual_question") if isinstance(constraints, dict) else None
    if not isinstance(rq, dict) or not str(rq.get("text") or "").strip():
        return list(questions or [])
    rid = str(rq.get("id") or "clarify_product_identity")
    nq = [
        q for q in (questions or [])
        if isinstance(q, dict) and str(q.get("id") or "") not in ("ask_image_model", rid)
    ]
    return [rq] + nq


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Question deduplication for render
# ═══════════════════════════════════════════════════════════════════════════════


def dedupe_next_questions_for_render(questions: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_slots: set[str] = set()
    seen_text: set[str] = set()
    for q in (questions or []):
        if not isinstance(q, dict):
            continue
        qq = dict(q)
        qid = str(qq.get("id") or "").strip().lower()
        qtext = " ".join(str(qq.get("text") or "").strip().lower().split())
        slot = str(qq.get("question_slot") or question_slot_from_id(qid)).strip().lower()
        if qid and qid in seen_ids:
            continue
        if qtext and qtext in seen_text:
            continue
        if slot and slot != "unknown" and slot in seen_slots:
            continue
        if qid:
            seen_ids.add(qid)
        if qtext:
            seen_text.add(qtext)
        if slot and slot != "unknown":
            seen_slots.add(slot)
        qq["question_slot"] = slot or "unknown"
        out.append(qq)
    return out[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Question flow routing
# ═══════════════════════════════════════════════════════════════════════════════


def question_flow(
    *,
    query: str | None,
    constraints: Dict[str, Any] | None,
) -> str:
    q = str(query or "").lower()
    c = constraints or {}
    use_case = str(c.get("use_case") or "").lower()
    use_case_tags = [str(x).lower() for x in (c.get("use_case_tags") or [])]

    if use_case in {"content_creator", "content_creation", "game_development", "ai_ml_workstation", "engineering_student", "architecture_student", "data_science_student"}:
        return "creator"
    if use_case.startswith("office_") or any("office_" in t for t in use_case_tags):
        return "office"
    if "student" in use_case or "university" in use_case or any(("student" in t or "university" in t) for t in use_case_tags):
        return "student"
    if any(t in q for t in ("video editing", "rendering", "creator", "blender", "autocad", "solidworks", "davinci", "premiere", "ai training", "ml training")):
        return "creator"
    if any(t in q for t in ("university", "college", "student", "school", "lecture", "assignment")):
        return "student"
    if any(t in q for t in ("office", "work", "corporate", "business", "excel", "teams", "outlook")):
        return "office"
    return "general"


# ═══════════════════════════════════════════════════════════════════════════════
# CORE — Intent-specific question bank adaptation (framework) +
# ADAPTER — Electronics-specific wording adjustments
# ═══════════════════════════════════════════════════════════════════════════════


def is_techy_query(query: str | None) -> bool:
    q = str(query or "").lower()
    if not q:
        return False
    return any(tok in q for tok in _TECHY_QUERY_TOKENS)


def append_gpu_disambiguation_question(existing: list[dict] | None, query: str | None = None,
                                       use_case: str | None = None) -> list[dict]:
    """ADAPTER: Electronics-specific GPU tier disambiguation."""
    out = [q for q in (existing or []) if isinstance(q, dict)]
    qid = "ask_gpu_preference"
    if any(str((q or {}).get("id") or "") == qid for q in out):
        return out
    techy = is_techy_query(query)
    q_low = str(query or "").lower()
    normalized_use_case = str(use_case or "").strip().lower()
    development_workload = (bool(normalized_use_case) and not normalized_use_case.startswith("gaming")) or any(tok in q_low for tok in (
        "game development", "gaming development", "game developer", "develop games",
        "build games", "unity", "unreal engine", "godot",
    ))
    gaming_query = (not development_workload) and any(
        tok in q_low for tok in ("gaming", "gamer", "game", "esports", "fps")
    )

    if gaming_query:
        question_text = "What kind of games will you mainly play? This determines the GPU tier needed."
        options = [
            {"id": "gaming_light", "label": "Light (Minecraft, Roblox, League of Legends)", "value": "gaming_light"},
            {"id": "gaming_casual", "label": "Casual (Fortnite, Apex, Valorant at 60fps)", "value": "gaming_casual"},
            {"id": "gaming_competitive", "label": "Competitive Esports (CS2, Valorant at 144fps+)", "value": "gaming_competitive"},
            {"id": "gaming_aaa_heavy", "label": "AAA Heavy (Cyberpunk, Starfield, Space Marines 2)", "value": "gaming_aaa_heavy"},
        ]
    elif techy:
        question_text = "Do you want a dedicated GPU (RTX/Radeon) or integrated graphics only?"
        options = [
            {"id": "with_discrete", "label": "Dedicated GPU (RTX/Radeon)"},
            {"id": "without_discrete", "label": "Integrated graphics only"},
            {"id": "no_preference", "label": "No strong preference"},
        ]
    else:
        question_text = "What matters more for your laptop: faster heavy-task performance, or longer battery life and lower cost?"
        options = [
            {"id": "with_discrete", "label": "Better performance for gaming/creative work"},
            {"id": "without_discrete", "label": "Longer battery life and lower price"},
            {"id": "no_preference", "label": "Show both"},
        ]
    out.append(
        {
            "id": qid,
            "text": question_text,
            "goal": "narrow_results",
            "why_hint": "GPU choice changes performance, battery life, heat, and price more than most other specs.",
            "options": options,
        }
    )
    return out[:3]


def append_standard_nqe_options(existing: list[dict] | None, query: str | None = None) -> list[dict]:
    """ADAPTER: Electronics-specific budget tier and use-case option sets."""
    q_low = str(query or "").strip().lower()
    gaming_like = any(tok in q_low for tok in ("gaming", "esports", "rtx", "render", "video editing", "creative", "3d", "cad", "ml", "ai"))
    student_like = any(tok in q_low for tok in ("student", "school", "high school", "university", "college", "note taking", "notes"))
    out: list[dict] = []
    for item in (existing or []):
        if not isinstance(item, dict):
            continue
        q = dict(item)
        qid = str(q.get("id") or "").strip().lower()
        if qid == "ask_budget" and not q.get("options"):
            if gaming_like:
                q["why_hint"] = "Gaming and creative workloads usually need a higher budget for GPU + cooling than note-taking or basic school use."
                q["options"] = [
                    {"id": "budget_under_1000", "label": "Under $1,200 (entry gaming; tradeoffs likely)", "value": "0-1200"},
                    {"id": "budget_1000_1500", "label": "$1,200-$1,800 (balanced gaming value)", "value": "1200-1800"},
                    {"id": "budget_1500_2200", "label": "$1,800-$2,500 (higher FPS / creator headroom)", "value": "1800-2500"},
                    {"id": "budget_2200_plus", "label": "$2,500+ (premium/high-end gaming)", "value": "2500+"},
                ]
            elif student_like:
                q["why_hint"] = "For school and note-taking, you can often stay lower budget unless you also need gaming or heavy creative workloads."
                q["options"] = [
                    {"id": "budget_under_1000", "label": "Under $1,000 (best value for school basics)", "value": "0-1000"},
                    {"id": "budget_1000_1500", "label": "$1,000-$1,500 (better battery/build longevity)", "value": "1000-1500"},
                    {"id": "budget_1500_2200", "label": "$1,500-$2,200 (premium; often optional for note-taking)", "value": "1500-2200"},
                    {"id": "budget_2200_plus", "label": "$2,200+ (usually overkill for basic study)", "value": "2200+"},
                ]
            else:
                q["why_hint"] = "Budget keeps recommendations realistic and prevents irrelevant high-end results."
                q["options"] = [
                    {"id": "budget_under_1000", "label": "Under $1,000", "value": "0-1000"},
                    {"id": "budget_1000_1500", "label": "$1,000-$1,500", "value": "1000-1500"},
                    {"id": "budget_1500_2200", "label": "$1,500-$2,200", "value": "1500-2200"},
                    {"id": "budget_2200_plus", "label": "$2,200+", "value": "2200+"},
                ]
        elif qid == "ask_use_case" and not q.get("options"):
            q["why_hint"] = "Use-case helps rank for what you care about most (battery, performance, portability, value)."
            q["options"] = [
                {"id": "use_case_student", "label": "School and everyday"},
                {"id": "use_case_business", "label": "Work and productivity"},
                {"id": "use_case_gaming", "label": "Gaming"},
                {"id": "use_case_video_editing", "label": "Video editing / creative"},
                {"id": "use_case_ai_training", "label": "AI training / ML"},
            ]
        out.append(q)
    if any(str((q or {}).get("id") or "") == "ask_gpu_preference" for q in out):
        out = append_gpu_disambiguation_question(out, query)
    return out[:3]


def apply_intent_specific_question_bank(
    questions: list[dict] | None,
    *,
    query: str | None,
    constraints: Dict[str, Any] | None,
) -> list[dict]:
    out = [dict(q) for q in (questions or []) if isinstance(q, dict)]
    if not out:
        return out
    flow = question_flow(query=query, constraints=constraints)
    if flow == "creator":
        out = append_gpu_disambiguation_question(
            out, query, use_case=str((constraints or {}).get("use_case") or ""))
    for q in out:
        qid = str(q.get("id") or "").strip().lower()
        if qid in {"ask_specs", "ask_requirements", "ask_system_requirements"} and flow in {"student", "office"}:
            q["text"] = "What matters most: lighter weight, longer battery life, larger screen/keyboard, or extra performance?"
            if not isinstance(q.get("options"), list):
                q["options"] = [
                    {"id": "priority_portability", "label": "Lightweight portability"},
                    {"id": "priority_battery", "label": "Long battery life"},
                    {"id": "priority_screen", "label": "Larger screen/keyboard"},
                    {"id": "priority_performance", "label": "More performance headroom"},
                ]
        if qid in {"ask_specs", "ask_requirements", "ask_system_requirements"} and flow == "creator":
            q["text"] = "For creator/engineering workloads, what minimums do you want for GPU/VRAM, RAM, and storage?"
        if qid == "ask_gpu_preference" and flow == "creator":
            q["text"] = "What matters more for creator workloads: dedicated GPU + VRAM headroom, or battery and lighter weight?"
    if flow in {"student", "office"}:
        rank = {
            "ask_specs": 0,
            "ask_requirements": 0,
            "ask_system_requirements": 0,
            "ask_budget": 1,
            "ask_budget_tier": 1,
            "ask_use_case": 2,
            "ask_university_subject": 2,
            "ask_high_school_activity": 2,
            "ask_corporate_work_type": 2,
            "ask_gaming_depth": 2,
            "ask_brand_pref": 3,
            "ask_brand": 3,
        }
    elif flow == "creator":
        rank = {
            "ask_gpu_preference": 0,
            "ask_specs": 1,
            "ask_requirements": 1,
            "ask_system_requirements": 1,
            "ask_use_case": 2,
            "ask_budget": 3,
            "ask_budget_tier": 3,
            "ask_brand_pref": 4,
            "ask_brand": 4,
        }
    else:
        rank = {}
    out = sorted(out, key=lambda q: rank.get(str(q.get("id") or "").strip().lower(), 9))
    return out[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# CORE framework + ADAPTER mappings — NQE selection → constraint application
# ═══════════════════════════════════════════════════════════════════════════════


def apply_nqe_selection_to_constraints(
    *,
    constraints: Dict[str, Any],
    nqe_question_id: str | None,
    nqe_option_id: str | None,
    nqe_option_label: str | None,
    nqe_option_value: str | None = None,
) -> Dict[str, Any]:
    qid = str(nqe_question_id or "").strip().lower()
    oid = str(nqe_option_id or "").strip().lower()
    lbl = str(nqe_option_label or "").strip().lower()
    val = str(nqe_option_value or "").strip().lower()
    applied: Dict[str, Any] = {}
    if not qid or not oid:
        return applied

    if qid == "ask_gpu_preference":
        if "without" in oid or "integrated" in oid or "without" in lbl:
            constraints["gpu_preference"] = "without_discrete"
            constraints["specs"] = [s for s in (constraints.get("specs") or []) if "gpu:discrete" not in str(s).lower()]
            applied["gpu_preference"] = "without_discrete"
        elif "with" in oid or "dedicated" in oid or "discrete" in oid or "rtx" in lbl or "radeon" in lbl:
            constraints["gpu_preference"] = "with_discrete"
            applied["gpu_preference"] = "with_discrete"
        elif "no_preference" in oid:
            constraints.pop("gpu_preference", None)
            applied["gpu_preference"] = "none"
        return applied

    if qid == "ask_budget":
        range_value = ""
        if oid == "budget_under_1000":
            range_value = "0-1000"
        elif oid == "budget_1000_1500":
            range_value = "1000-1500"
        elif oid == "budget_1500_2200":
            range_value = "1500-2200"
        elif oid == "budget_2200_plus":
            range_value = "2200+"
        elif re.search(r"\d", lbl):
            range_value = lbl.replace("$", "").replace(",", "").replace(" ", "")
        elif re.search(r"\d", val):
            range_value = val.replace("$", "").replace(",", "").replace(" ", "")
        if range_value.endswith("+"):
            try:
                constraints["budget_min"] = int(re.sub(r"[^\d]", "", range_value))
                constraints["budget_max"] = None
                applied["budget_min"] = constraints["budget_min"]
            except Exception:
                pass
        elif "-" in range_value:
            bits = [re.sub(r"[^\d]", "", x) for x in range_value.split("-", 1)]
            try:
                bmin = int(bits[0]) if bits and bits[0] else None
                bmax = int(bits[1]) if len(bits) > 1 and bits[1] else None
                if bmin is not None:
                    constraints["budget_min"] = bmin
                    applied["budget_min"] = bmin
                if bmax is not None:
                    constraints["budget_max"] = bmax
                    applied["budget_max"] = bmax
                    _bb = classify_budget_bracket(bmax)
                    if _bb:
                        constraints["budget_bracket"] = _bb
                        applied["budget_bracket"] = _bb
            except Exception:
                pass
        return applied

    if qid == "ask_use_case":
        mapping = {
            "use_case_student": ("high_school", ["student", "high_school"]),
            "use_case_business": ("office_general", ["office", "office_general"]),
            "use_case_gaming": ("gaming", ["gaming"]),
            "use_case_video_editing": ("content_creator", ["content_creator"]),
            "use_case_ai_training": ("ai_ml_workstation", ["ai_ml_workstation"]),
        }
        use_case, tags = mapping.get(oid, (None, None))
        if not use_case and val:
            if "gaming" in val:
                use_case, tags = ("gaming", ["gaming"])
            elif any(tok in val for tok in ("ai", "ml", "training", "cuda", "llm")):
                use_case, tags = ("ai_ml_workstation", ["ai_ml_workstation"])
            elif any(tok in val for tok in ("video", "editing", "creative", "render")):
                use_case, tags = ("content_creator", ["content_creator"])
            elif "high school" in val or "school" in val or "student" in val:
                use_case, tags = ("high_school", ["student", "high_school"])
            elif any(tok in val for tok in ("work", "business", "office")):
                use_case, tags = ("office_general", ["office", "office_general"])
        if use_case:
            constraints["use_case"] = use_case
            constraints["use_case_tags"] = tags
            applied["use_case"] = use_case
            applied["use_case_tags"] = tags
        return applied

    if qid == "ask_high_school_activity":
        hs_mapping = {
            "high_school_basic": ("high_school", ["student", "high_school"]),
            "gaming_light":      ("gaming",      ["gaming", "gaming_light"]),
            "content_creator":   ("content_creator", ["content_creator"]),
            "music_production":  ("music_production", ["music_production"]),
            "engineering_student": ("engineering_student", ["student", "engineering_student"]),
            "design_student":    ("design_student", ["student", "design_student"]),
        }
        _key = oid if oid in hs_mapping else (val if val in hs_mapping else None)
        if _key:
            _uc, _tags = hs_mapping[_key]
            constraints["use_case"] = _uc
            constraints["use_case_tags"] = _tags
            applied["use_case"] = _uc
            applied["use_case_tags"] = _tags
            if _key == "gaming_light":
                constraints["gpu_preference"] = "without_discrete"
                applied["gpu_preference"] = "without_discrete"
        return applied

    if qid == "ask_university_subject":
        uni_mapping = {
            "computer_science_student":  (["student", "computer_science_student"],  "with_discrete"),
            "engineering_student":        (["student", "engineering_student"],        "with_discrete"),
            "data_science_student":       (["student", "data_science_student"],       "with_discrete"),
            "design_student":             (["student", "design_student"],             "with_discrete"),
            "architecture_student":       (["student", "architecture_student"],       "with_discrete"),
            "medical_student":            (["student", "medical_student"],            None),
            "law_student":                (["student", "law_student"],                None),
            "university_general":         (["student", "university_general"],         None),
        }
        _key = oid if oid in uni_mapping else (val if val in uni_mapping else None)
        if _key:
            _tags, _gpu = uni_mapping[_key]
            constraints["use_case"] = _key
            constraints["use_case_tags"] = _tags
            applied["use_case"] = _key
            applied["use_case_tags"] = _tags
            if _gpu:
                constraints["gpu_preference"] = _gpu
                applied["gpu_preference"] = _gpu
        return applied

    if qid == "ask_corporate_work_type":
        corp_mapping = {
            "office_general":   ("office_general",   ["office", "office_general"]),
            "office_finance":   ("office_finance",   ["office", "office_finance"]),
            "office_executive": ("office_executive", ["office", "office_executive"]),
        }
        _key = oid if oid in corp_mapping else (val if val in corp_mapping else None)
        if _key:
            _uc, _tags = corp_mapping[_key]
            constraints["use_case"] = _uc
            constraints["use_case_tags"] = _tags
            applied["use_case"] = _uc
            applied["use_case_tags"] = _tags
        return applied

    if qid in ("ask_gaming_depth", "ask_gpu_preference") and qid == "ask_gaming_depth":
        gaming_gpu = {
            "gaming_light":       ("gaming", ["gaming", "gaming_light"],       "without_discrete"),
            "gaming_casual":      ("gaming", ["gaming", "gaming_casual"],       "with_discrete"),
            "gaming_competitive": ("gaming", ["gaming", "gaming_competitive"],  "with_discrete"),
            "gaming_aaa_heavy":   ("gaming", ["gaming", "gaming_aaa_heavy"],    "with_discrete"),
        }
        _key = oid if oid in gaming_gpu else (val if val in gaming_gpu else None)
        if _key:
            _uc, _tags, _gpu = gaming_gpu[_key]
            constraints["use_case"] = _uc
            constraints["use_case_tags"] = _tags
            constraints["gpu_preference"] = _gpu
            applied["use_case"] = _uc
            applied["use_case_tags"] = _tags
            applied["gpu_preference"] = _gpu
        return applied

    return applied
