from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.models.orm import Base, CommercialOutcomeRecord
from src.app.services.commercial_outcome_ledger import (
    project_realized_commercial_outcomes,
    record_commercial_outcome,
    record_order_transition_outcome,
)


NOW = datetime(2026, 8, 18, 7, 0, tzinfo=timezone.utc)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_settled_purchase_and_return_are_distinct_observed_outcomes():
    db = _db()
    common = {
        "db": db, "tenant_id": "portfolio", "order_id": "order-1",
        "trace_id": "case-1", "observed_at": NOW, "effective_at": NOW,
        "amount_cents": 120_000, "currency": "AUD",
        "line_items": [{"sku": "LAP-1", "quantity": 2, "price_cents": 60_000}],
    }
    record_commercial_outcome(
        **common, outcome_id="order-1:paid", outcome_type="payment_settled",
        source_authority="authenticated_payment_transition",
    )
    record_commercial_outcome(
        **common, outcome_id="order-1:returned", outcome_type="returned",
        source_authority="authenticated_order_transition",
    )
    result = project_realized_commercial_outcomes(
        db, tenant_id="portfolio", trace_id="case-1",
    )
    assert result["settled_purchase_count"] == 1
    assert result["settled_value_by_currency"] == {"AUD": 120_000}
    assert [row["type"] for row in result["outcomes"]] == ["payment_settled", "returned"]
    assert result["causal_claim_authority"] is False


def test_outcome_is_idempotent_and_strips_unapproved_fields():
    db = _db()
    kwargs = dict(
        tenant_id="portfolio", outcome_id="order-2:created", order_id="order-2",
        outcome_type="order_created", source_authority="authenticated_checkout",
        line_items=[{
            "sku": "LAP-2", "quantity": 1, "price_cents": 50_000,
            "buyer_email": "must-not-persist@example.test",
        }], observed_at=NOW,
    )
    first = record_commercial_outcome(db, **kwargs)
    replay = record_commercial_outcome(db, **kwargs)
    assert replay.id == first.id
    assert first.line_items_json == [{"sku": "LAP-2", "quantity": 1, "price_cents": 50_000}]


def test_amount_without_currency_fails_closed():
    db = _db()
    with pytest.raises(ValueError, match="amount_and_currency"):
        record_commercial_outcome(
            db, tenant_id="portfolio", outcome_id="order-3:paid", order_id="order-3",
            outcome_type="payment_settled", source_authority="payment", amount_cents=10,
            observed_at=NOW,
        )


def test_committed_order_transition_projects_server_prices_without_pii():
    engine = create_engine("sqlite:///:memory:")
    CommercialOutcomeRecord.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE draft_orders (
              id TEXT PRIMARY KEY, line_items JSON
            )
        """))
        connection.execute(text("""
            CREATE TABLE orders (
              id TEXT PRIMARY KEY, draft_order_id TEXT, tenant_id TEXT,
              trace_id TEXT, total_cents INTEGER, currency TEXT
            )
        """))
        connection.execute(text("""
            INSERT INTO draft_orders (id, line_items)
            VALUES ('draft-1', :line_items)
        """), {"line_items": '[{"sku":"LAP-1","quantity":2,"price_cents":60000}]'})
        connection.execute(text("""
            INSERT INTO orders (
              id, draft_order_id, tenant_id, trace_id, total_cents, currency
            ) VALUES (
              'order-4', 'draft-1', 'portfolio', 'case-4', 120000, 'AUD'
            )
        """))
    db = Session(engine)
    record_order_transition_outcome(db, order_id="order-4", status="paid")
    result = project_realized_commercial_outcomes(
        db, tenant_id="portfolio", trace_id="case-4",
    )
    assert result["settled_value_by_currency"] == {"AUD": 120_000}
    assert result["outcomes"][0]["line_items"] == [
        {"sku": "LAP-1", "quantity": 2, "price_cents": 60_000},
    ]
