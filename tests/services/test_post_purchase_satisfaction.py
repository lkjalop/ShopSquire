from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.models.orm import CommercialOutcomeRecord, PostPurchaseSatisfactionRecord
from src.app.services.post_purchase_satisfaction import (
    SatisfactionSubmission,
    record_post_purchase_satisfaction,
)


NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def _db(status="delivered"):
    engine = create_engine("sqlite:///:memory:")
    CommercialOutcomeRecord.__table__.create(engine)
    PostPurchaseSatisfactionRecord.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE orders (
              id TEXT PRIMARY KEY, tenant_id TEXT, total_cents INTEGER,
              currency TEXT, status TEXT, trace_id TEXT
            )
        """))
    db = Session(engine)
    db.execute(text("""
        INSERT INTO orders (id, tenant_id, total_cents, currency, status, trace_id)
        VALUES ('order-1', 'portfolio', 100000, 'AUD', :status, 'case-1')
    """), {"status": status})
    db.commit()
    return db


def _submission():
    return SatisfactionSubmission(
        submission_id="satisfaction-0001", rating=4,
        fulfilled_as_expected=True, would_recommend=True,
        reason_codes=("fit", "delivery", "fit"),
    )


def test_affirmative_satisfaction_is_typed_deduplicated_and_linked():
    db = _db()
    first = record_post_purchase_satisfaction(
        db, tenant_id="portfolio", order_id="order-1",
        submission=_submission(), actor_class="human_operator",
        source_authority="authenticated_role:owner", observed_at=NOW,
    )
    replay = record_post_purchase_satisfaction(
        db, tenant_id="portfolio", order_id="order-1",
        submission=_submission(), actor_class="human_operator",
        source_authority="authenticated_role:owner", observed_at=NOW,
    )
    assert first.id == replay.id
    assert first.reason_codes_json == ["delivery", "fit"]
    outcome = db.execute(text("""
        SELECT outcome_type, trace_id FROM commercial_outcomes
        WHERE tenant_id='portfolio'
    """)).fetchone()
    assert tuple(outcome) == ("satisfaction_recorded", "case-1")


def test_satisfaction_is_not_inferred_before_delivery_or_across_tenants():
    db = _db(status="paid")
    with pytest.raises(ValueError, match="requires_delivered"):
        record_post_purchase_satisfaction(
            db, tenant_id="portfolio", order_id="order-1",
            submission=_submission(), actor_class="human_operator",
            source_authority="authenticated_role:owner", observed_at=NOW,
        )
    with pytest.raises(ValueError, match="order_not_found"):
        record_post_purchase_satisfaction(
            db, tenant_id="other", order_id="order-1",
            submission=_submission(), actor_class="human_operator",
            source_authority="authenticated_role:owner", observed_at=NOW,
        )
