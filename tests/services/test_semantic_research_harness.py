"""Metamorphic coverage for model-led interpretation and bounded research planning."""

import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope


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
    session.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p1','LAP-1','General Laptop',149900,'{}','Example')"
    ))
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification

    add_sold_node(session, node_handle="el-6-6")
    upsert_classification(
        session, sku="LAP-1", node_handle="el-6-6", source="test", status="approved",
    )
    yield session
    session.close()


@pytest.mark.parametrize(
    ("query", "buyer_span"),
    [
        ("Find a laptop for an unfamiliar vibration-analysis workflow.", "vibration-analysis workflow"),
        ("I need a computer for a new protein-folding simulation.", "protein-folding simulation"),
        ("Recommend equipment for an unknown architectural daylight model.", "architectural daylight model"),
        ("Find a workstation for a proprietary media-rendering pipeline.", "media-rendering pipeline"),
        ("I need hardware for an unfamiliar geospatial reconstruction job.", "geospatial reconstruction job"),
    ],
)
def test_ambiguous_domains_share_one_research_first_contract(db, query, buyer_span):
    model_calls = []

    def interpret(_prompt, _timeout):
        model_calls.append(True)
        return json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "confidence": 0.84,
            "semantic_proposal": {
                "desired_outcome": "qualify a suitable product",
                "concepts": [{
                    "text": buyer_span,
                    "query_span": buyer_span,
                    "normalized_label": "specialized compute workload",
                    "status": "unresolved",
                    "material": True,
                }],
                "evidence_questions": [{
                    "question_id": "performance_target",
                    "question": "What verified compatibility and performance target is required?",
                    "purpose": "resolve_performance_target",
                    "material": True,
                }],
                "proposed_action": "research_then_clarify",
                "confidence": 0.84,
            },
        })

    response = recommend_turn(
        db,
        TurnEnvelope.from_suggest_params(query=query, uid="harness-user", currency="USD"),
        llm_fn=interpret,
    )

    assert model_calls == [True]
    assert response.products == []
    assert response.extras["slate_disposition"] == "clear"
    assert response.clarify[0]["id"] == "external_research_consent"
    plan = response.extras["plan"]["research_plan"]
    assert plan["subject_spans"] == [buyer_span]
    assert plan["interpretation_origin"] == "model"
    assert plan["max_provider_fanout"] <= 3
    assert "provider_id" not in json.dumps(plan)


def test_clause_reordering_preserves_authorization_result(db):
    queries = [
        "Find a laptop for an unfamiliar vibration-analysis workflow.",
        "For an unfamiliar vibration-analysis workflow, find a laptop.",
    ]
    outputs = []

    for query in queries:
        response = recommend_turn(
            db,
            TurnEnvelope.from_suggest_params(query=query, uid=query, currency="USD"),
            llm_fn=lambda _prompt, _timeout: json.dumps({
                "lane": "SEARCH",
                "handle": "el-6-6",
                "confidence": 0.82,
                "semantic_proposal": {
                    "desired_outcome": "qualify a suitable product",
                    "concepts": [{
                        "text": "vibration-analysis workflow",
                        "query_span": "vibration-analysis workflow",
                        "status": "unresolved",
                        "material": True,
                    }],
                    "evidence_questions": [],
                    "proposed_action": "research_then_clarify",
                    "confidence": 0.82,
                },
            }),
        )
        outputs.append((
            response.extras["semantic_resolution"]["catalog_authority"],
            response.extras["slate_disposition"],
            response.clarify[0]["id"],
        ))

    assert outputs[0] == outputs[1] == (
        "blocked", "clear", "external_research_consent",
    )
