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
