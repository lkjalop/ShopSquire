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
    run_recommend_nqe_stage,
)


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


def test_router_reexports_same_objects():
    from src.app.routers import recommend as r

    assert r.prioritize_domain_refinement_questions is prioritize_domain_refinement_questions
    assert r.RecommendStageState is RecommendStageState
    assert r.RecommendNQEHooks is RecommendNQEHooks
    assert r.run_recommend_nqe_stage is run_recommend_nqe_stage
