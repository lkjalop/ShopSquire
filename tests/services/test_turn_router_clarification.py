import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import route_turn


@pytest.fixture()
def db():
    session = sessionmaker(bind=create_engine("sqlite://"))()
    session.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, "
        "name TEXT NOT NULL, price_cents INT NOT NULL, currency TEXT NOT NULL "
        "DEFAULT 'USD', image_url TEXT, specs TEXT, product_type TEXT, brand TEXT, "
        "category TEXT, attributes TEXT, active INTEGER DEFAULT 1, updated_at TEXT "
        "DEFAULT CURRENT_TIMESTAMP)"
    ))
    session.execute(
        text(
            "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
            "('p1','LAP-1','Engineering Laptop',209900,:specs,'Asus')"
        ),
        {"specs": json.dumps({"ram_gb": 32, "gpu_vram_gb": 12})},
    )
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification

    add_sold_node(session, node_handle="el-6-6")
    upsert_classification(
        session, sku="LAP-1", node_handle="el-6-6", source="test", status="approved",
    )
    yield session
    session.close()


def _pending_session():
    return {
        "pending_clarification": {
            "version": 2,
            "state": "active",
            "question_id": "software_or_standard",
            "question": "Which software and version must be supported?",
            "original_query": "Recommend a laptop for a mechanical digital twin.",
            "desired_outcome": "resolve software compatibility",
            "external_research_consent": True,
            "semantic_context": {
                "desired_outcome": "qualify a portable workstation for a mechanical digital twin",
                "catalog_authority": "blocked",
                "concepts": [
                    {
                        "concept_id": "digital-twin",
                        "text": "mechanical digital twin",
                        "status": "unresolved",
                        "material": True,
                    }
                ],
                "questions": [
                    {
                        "question_id": "software_or_standard",
                        "question": "Which software and version must be supported?",
                    }
                ],
                "state_prevented": ["catalog_recommendation", "supplier_rfq"],
            },
        }
    }


def test_free_text_answer_is_classified_against_pending_material_question(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="Siemens NX 2025 running locally",
        uid="buyer-1",
        tenant_id="default",
        session=_pending_session(),
    )

    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "requirements": {},
            "workload_entities": [
                {"kind": "software", "name": "Siemens NX 2025"},
            ],
            "clarification_relation": "answer",
            "confidence": 0.94,
        }),
    )

    assert decision.clarification_relation == "answer"
    assert decision.workload_entities == (("software", "Siemens NX 2025"),)
    assert decision.model_proposal["clarification_relation"] == "answer"


def test_bounded_research_consent_cannot_supersede_retained_workload(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="You may research approved official sources for the workload requirements.",
        uid="buyer-consent",
        tenant_id="default",
        session={
            **_pending_session(),
            "semantic_resolution": _pending_session()["pending_clarification"]["semantic_context"],
        },
        external_research_consent=True,
    )

    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "clarification_relation": "supersede",
            "confidence": 0.81,
        }),
    )

    assert decision.semantic_proposal["proposal_origin"] == "persisted"
    assert "mechanical digital twin" in decision.semantic_proposal["desired_outcome"]
    assert decision.semantic_proposal["persisted_case_blocker"] is True
    assert decision.clarification_relation == "answer"


def test_generic_model_placeholder_falls_back_to_buyer_grounded_purpose(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="Please recommend a laptop for simulating a digital twin for maintenance of mechanical machines.",
        uid="buyer-placeholder",
        tenant_id="default",
    )
    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "confidence": 0.82,
            "semantic_proposal": {
                "desired_outcome": "what I need",
                "concepts": [{"text": "what I need", "status": "unresolved", "material": True}],
                "evidence_questions": [],
                "proposed_action": "research_then_clarify",
                "confidence": 0.8,
            },
        }),
    )

    assert decision.semantic_proposal["proposal_origin"] in {
        "deterministic_fallback", "coverage_abstention",
    }
    assert "digital twin" in decision.semantic_proposal["desired_outcome"].lower()
    assert "what i need" not in decision.semantic_proposal["concepts"][0]["text"].lower()


def test_structured_semantic_case_survives_when_pending_question_record_is_absent(db):
    semantic = _pending_session()["pending_clarification"]["semantic_context"]
    envelope = TurnEnvelope.from_suggest_params(
        query="Actually reduce it by 10 units.",
        uid="buyer-retained-case",
        tenant_id="default",
        session={"semantic_resolution": semantic, "accepted_constraints": {"quantity": 30}},
    )
    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "FILTER",
            "clarification_relation": "supersede",
            "confidence": 0.8,
        }),
    )

    assert "mechanical digital twin" in decision.semantic_proposal["desired_outcome"]
    assert decision.semantic_proposal["proposal_origin"] == "persisted"


def test_missing_pending_relation_gets_one_bounded_model_repair(db):
    responses = iter([
        json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "requirements": {},
            "workload_entities": [
                {"kind": "workflow", "name": "mechanical maintenance simulation"},
            ],
            "confidence": 0.91,
        }),
        json.dumps({"clarification_relation": "answer"}),
    ])
    calls = []

    def model(prompt, _timeout):
        calls.append(prompt)
        return next(responses)

    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query=(
                "Recommend a laptop for a mechanical digital twin. Buyer clarification "
                "to 'Which software and version must be supported?': the workflow runs "
                "locally for engineering simulation and 3D visualisation."
            ),
            uid="buyer-1",
            tenant_id="default",
            session=_pending_session(),
            external_research_consent=True,
        ),
        llm_fn=model,
    )

    assert len(calls) == 2
    assert "CLARIFICATION RELATION REPAIR" in calls[1]
    assert decision.clarification_relation == "answer"


def test_model_timeout_cannot_drop_pending_semantic_authority(db):
    decision = route_turn(
        db,
        TurnEnvelope.from_suggest_params(
            query=(
                "Recommend a laptop for a mechanical digital twin. Buyer clarification "
                "to 'Which software and version must be supported?': the workflow runs "
                "locally for engineering simulation and 3D visualisation."
            ),
            uid="buyer-1",
            tenant_id="default",
            session=_pending_session(),
            external_research_consent=True,
        ),
        llm_fn=lambda _prompt, _timeout: (_ for _ in ()).throw(TimeoutError()),
    )

    assert decision.source == "fallback:model_unavailable"
    assert decision.node_handle is None
    assert decision.semantic_proposal["persisted_case_blocker"] is True
    assert decision.semantic_proposal["concepts"][0]["text"] == "mechanical digital twin"


def test_answer_without_new_semantic_proposal_inherits_blocked_case_authority(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="Siemens NX 2025 running locally",
        uid="buyer-1",
        tenant_id="default",
        session=_pending_session(),
        external_research_consent=True,
    )

    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "requirements": {},
            "clarification_relation": "answer",
            "confidence": 0.94,
        }),
    )

    assert decision.semantic_proposal["validation"] == "valid"
    assert decision.semantic_proposal["desired_outcome"].startswith("qualify a portable workstation")
    assert decision.semantic_proposal["concepts"][0]["text"] == "mechanical digital twin"
    assert decision.semantic_proposal["persisted_case_blocker"] is True


def test_sparse_pronoun_proposal_cannot_replace_active_blocked_concept(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="Reduce it by 10, but it is not powerful enough for what I need.",
        uid="buyer-1",
        tenant_id="default",
        session=_pending_session(),
        external_research_consent=True,
    )

    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "PROCUREMENT",
            "handle": None,
            "clarification_relation": "answer",
            "semantic_proposal": {
                "desired_outcome": "what I need",
                "concepts": [{
                    "text": "what I need",
                    "status": "unresolved",
                    "material": True,
                    "interpretations": [],
                }],
                "evidence_questions": [],
                "proposed_action": "research_then_clarify",
                "confidence": 0.9,
            },
            "confidence": 0.9,
        }),
    )

    assert decision.semantic_proposal["proposal_origin"] == "persisted"
    assert decision.semantic_proposal["concepts"][0]["text"] == "mechanical digital twin"


def test_replacement_objective_supersedes_pending_question(db):
    envelope = TurnEnvelope.from_suggest_params(
        query="Forget that. I need office chairs instead.",
        uid="buyer-1",
        tenant_id="default",
        session=_pending_session(),
    )

    decision = route_turn(
        db,
        envelope,
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "requirements": {},
            "subject_action": "switch",
            "clarification_relation": "supersede",
            "confidence": 0.95,
        }),
    )

    assert decision.clarification_relation == "supersede"
    assert decision.subject_action == "switch"
