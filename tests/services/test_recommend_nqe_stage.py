"""recommend_nqe_stage service — the extracted NQE stage (core/adapter split, stage #3).

This is the first *inline-block* extraction from suggest() (it introduced RecommendStageState).
The full run_recommend_nqe_stage() needs the request context + hooks, so it's exercised via the
in-suite TestClient tests in test_recommend.py; here we lock the PURE ordering logic
(prioritize_domain_refinement_questions — the domain-refinement fix) and the re-export identity.
"""
from __future__ import annotations

from src.app.services.recommend_nqe_stage import (
    DOMAIN_REFINEMENT_QUESTION_IDS,
    RecommendNQEHooks,
    RecommendStageState,
    prioritize_domain_refinement_questions,
    refine_missing_fields_with_query_understanding,
    run_recommend_nqe_stage,
)
from src.app.services.query_understanding import build_query_understanding


def _ids(qs):
    return [q.get("id") for q in qs]


def test_domain_refinement_ranked_ahead_of_generic_use_case():
    # generic ask_use_case must not crowd out the specific domain question before the cap.
    out = prioritize_domain_refinement_questions(
        [{"id": "ask_use_case"}, {"id": "ask_university_subject"}, {"id": "ask_budget"}]
    )
    # guard (ask_budget) first, then domain, then generic use_case last.
    assert _ids(out) == ["ask_budget", "ask_university_subject", "ask_use_case"]


def test_no_domain_question_leaves_order_unchanged():
    items = [{"id": "ask_use_case"}, {"id": "ask_budget"}]
    assert _ids(prioritize_domain_refinement_questions(items)) == ["ask_use_case", "ask_budget"]


def test_empty_and_noise_inputs():
    assert prioritize_domain_refinement_questions(None) == []
    assert prioritize_domain_refinement_questions([]) == []
    # non-dict entries are dropped
    assert prioritize_domain_refinement_questions(["x", None, {"id": "ask_gaming_depth"}]) == [
        {"id": "ask_gaming_depth"}
    ]


def test_returns_copies_not_aliases():
    src = [{"id": "ask_corporate_work_type", "meta": 1}]
    out = prioritize_domain_refinement_questions(src)
    out[0]["meta"] = 999
    assert src[0]["meta"] == 1  # input not mutated


def test_domain_ids_cover_the_known_refinements():
    for qid in ("ask_high_school_activity", "ask_university_subject", "ask_corporate_work_type"):
        assert qid in DOMAIN_REFINEMENT_QUESTION_IDS


def test_stage_state_constructs_with_defaults():
    st = RecommendStageState(
        query="q", query_effective="q", uid="u", constraints={}, nlp={}, kv={},
        structured_state={}, payload={}, image_context={}, question_plan={},
        trace_id=None, flags={},
    )
    assert st.next_questions == [] and st.followup_explain is False


def test_query_understanding_suppresses_stale_missing_fields():
    qu = build_query_understanding(
        "asus gaming laptop under 1800",
        {"budget_max": 1800, "_inferred_image_brand": "asus", "use_case": "gaming"},
    )
    out = refine_missing_fields_with_query_understanding(
        ["budget", "use_case", "brand_preference", "specs"],
        qu,
    )
    assert out == ["specs"]


def test_query_understanding_refinement_does_not_add_new_missing_fields():
    qu = build_query_understanding("show me something", {})
    assert refine_missing_fields_with_query_understanding(["budget"], qu) == ["budget"]
    assert refine_missing_fields_with_query_understanding([], qu) == []


def test_v2_nqe_contracts_are_owned_by_the_stage_module():
    assert prioritize_domain_refinement_questions.__module__.endswith(
        "recommend_nqe_stage"
    )
    assert RecommendStageState.__module__.endswith("recommend_nqe_stage")
    assert RecommendNQEHooks.__module__.endswith("recommend_nqe_stage")
    assert run_recommend_nqe_stage.__module__.endswith("recommend_nqe_stage")


def test_persona_fallback_never_reasks_a_known_use_case():
    """The live complaint: the buyer clicked Gaming, yet low persona-confidence re-injected
    "what will you mostly do?". With use_case_known the fallback must not insert ask_use_case —
    and must STRIP one that is already present (empty list = nothing left to ask, which is correct)."""
    from src.app.services.recommend_nqe_helpers import apply_persona_confidence_fallback as fb

    qs = [{"id": "ask_budget", "text": "What's your budget?"}]
    # unknown use_case + low confidence → fallback inserts ask_use_case at the front (old behaviour)
    out = fb(qs, persona=None, persona_confidence=0.0)
    assert any(q["id"] == "ask_use_case" for q in out)
    # KNOWN use_case → never inserted, other questions untouched
    out2 = fb(qs, persona=None, persona_confidence=0.0, use_case_known=True)
    assert [q["id"] for q in out2] == ["ask_budget"]
    # KNOWN use_case strips a pre-existing ask_use_case too — even down to an empty list
    out3 = fb([{"id": "ask_use_case", "text": "?"}], persona=None, persona_confidence=0.0, use_case_known=True)
    assert out3 == []
