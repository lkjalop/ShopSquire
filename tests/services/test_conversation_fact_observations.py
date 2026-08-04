import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from src.app.models.db import set_engine
from src.app.services.conversation_fact_observations import (
    extract_conversation_facts,
    record_conversation_fact_observations,
)


def _schema(engine):
    with engine.begin() as db:
        db.execute(text("""
            CREATE TABLE conversation_fact_observation (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject_ref TEXT NOT NULL,
                session_id TEXT, source_message_id TEXT NOT NULL, trace_id TEXT,
                category TEXT NOT NULL, normalized_value_json TEXT NOT NULL,
                source_excerpt TEXT NOT NULL, provenance_json TEXT NOT NULL,
                confidence REAL NOT NULL, authority TEXT NOT NULL, status TEXT NOT NULL,
                observed_at TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE (tenant_id, source_message_id, category, normalized_value_json)
            )
        """))
        db.execute(text("""
            CREATE TABLE party (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, display_name TEXT
            )
        """))
        db.execute(text(
            "INSERT INTO party (id, tenant_id, display_name) VALUES ('p1', 't1', 'Authority')"
        ))


def test_extracts_bounded_commercial_fact_vocabulary():
    facts = extract_conversation_facts(
        "We need 25 laptops every month, no Dell or HP. Budget AUD 30000. "
        "Pack of 5, deliver by 30 September, payment terms Net 30."
    )
    categories = {fact.category for fact in facts}
    assert {
        "stated_requirement",
        "brand_exclusion",
        "budget",
        "pack_uom_preference",
        "delivery_requirement",
        "payment_term_request",
        "recurring_use_case",
    } <= categories
    budget = next(fact for fact in facts if fact.category == "budget")
    assert budget.value == {
        "amount": "30000",
        "currency": "AUD",
        "scope": "unspecified",
    }


def test_persists_provenance_expiry_and_never_mutates_party():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _schema(engine)
    set_engine(engine)
    observed = datetime(2026, 7, 28, tzinfo=timezone.utc)
    first = record_conversation_fact_observations(
        tenant_id="t1",
        subject_ref="buyer-hash",
        session_id="s1",
        source_message_id="m1",
        trace_id="trace-1",
        message="Our budget is USD 5000 and we need 10 units.",
        observed_at=observed,
    )
    assert first
    duplicate = record_conversation_fact_observations(
        tenant_id="t1",
        subject_ref="buyer-hash",
        session_id="s1",
        source_message_id="m1",
        trace_id="trace-1",
        message="Our budget is USD 5000 and we need 10 units.",
        observed_at=observed,
    )
    assert all(item["duplicate"] for item in duplicate)
    with engine.connect() as db:
        rows = db.execute(text(
            "SELECT provenance_json, authority, observed_at, expires_at "
            "FROM conversation_fact_observation"
        )).fetchall()
        party = db.execute(text("SELECT display_name FROM party WHERE id='p1'")).scalar_one()
    assert party == "Authority"
    assert all(row[1] == "observation_only" for row in rows)
    assert all(json.loads(row[0])["source_message_id"] == "m1" for row in rows)
    assert all(row[3] > row[2] for row in rows)


def test_ambiguous_dollar_is_not_promoted_to_authoritative_currency():
    facts = extract_conversation_facts("Budget up to $2,000.")
    budget = next(fact for fact in facts if fact.category == "budget")
    assert budget.value["currency"] == "AMBIGUOUS_DOLLAR"
    assert budget.confidence < 0.9
