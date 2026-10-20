import json
import pytest
from tests.services.test_turn_router_clarification import db, _pending_session
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import route_turn


@pytest.mark.parametrize("relation", ["answer", "supersede"])
@pytest.mark.parametrize(
    "query",
    [
        "Mostly small PLC models, but occasionally a large factory model.",
        "Usually small scenes, with occasionally complex assemblies.",
    ],
)
def test_scale_refinement_is_not_replaced_by_a_contradictory_model(db, relation, query):
    session = _pending_session()
    session["pending_clarification"].update(
        question_id="performance_target",
        question="What workload or model scale and time-to-result target should define acceptable performance?",
    )
    d = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query=query, buyer_query=query, uid="scale-owner", tenant_id="default", session=session
        ),
        llm_fn=lambda *_: json.dumps(
            {
                "lane": "SEARCH",
                "handle": "el-6-6",
                "requirements": {},
                "subject_action": "switch",
                "clarification_relation": relation,
                "confidence": 0.95,
            }
        ),
    )
    assert d.subject_action == "continue", (d.subject_action, d.clarification_relation)
    assert d.clarification_relation == "answer"
    assert d.model_proposal["subject_action"] == "switch"
    assert d.model_proposal["clarification_relation"] == relation
    assert "subject_action:clamped" in d.authorization_changes
    assert d.semantic_proposal["persisted_case_blocker"] is True


@pytest.mark.parametrize("relation", ["answer", "supersede"])
def test_explicit_replacement_survives_a_pending_scale_question(db, relation):
    query = "Actually replace that workload with Baldur's Gate 3."
    session = _pending_session()
    session["pending_clarification"].update(
        question_id="performance_target",
        question="What workload or model scale and time-to-result target should define acceptable performance?",
    )
    d = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query=query, buyer_query=query, uid="scale-owner", tenant_id="default", session=session
        ),
        llm_fn=lambda *_: json.dumps(
            {
                "lane": "SEARCH",
                "handle": "el-6-6",
                "requirements": {},
                "subject_action": "switch",
                "clarification_relation": relation,
                "confidence": 0.95,
            }
        ),
    )
    assert d.subject_action == "switch"


@pytest.mark.parametrize(
    "question_updates",
    [
        {"expires_at": 1},
        {"expires_at": "invalid"},
        {"expires_at": float("nan")},
        {"state": "expired"},
        {"question_id": "software_or_standard"},
        {"question_id": "external_research_consent", "answer_mode": "enum"},
    ],
)
def test_scale_fragment_cannot_consume_an_unrelated_or_expired_question(db, question_updates):
    session = _pending_session()
    session["pending_clarification"].update(question_id="performance_target")
    session["pending_clarification"].update(question_updates)
    query = "Mostly small PLC models, but occasionally a large factory model."
    d = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query=query, buyer_query=query, uid="scale-owner", tenant_id="default", session=session
        ),
        llm_fn=lambda *_: json.dumps(
            {
                "lane": "SEARCH",
                "handle": "el-6-6",
                "requirements": {},
                "subject_action": "switch",
                "clarification_relation": "supersede",
                "confidence": 0.95,
            }
        ),
    )
    assert d.clarification_relation != "answer"
    assert d.model_proposal["subject_action"] == "switch"
