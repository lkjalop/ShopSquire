"""Reviewed supplier lead-time evidence is advisory and owned by one case."""

from datetime import timedelta

import pytest
from sqlalchemy import text

import tests.services.test_supplier_enquiry_journey as shared_fixtures
from tests.services.test_supplier_enquiry_journey import sent, quote

from src.app.services import supplier_enquiry_journey as journey
from src.app.services.market_intelligence_agent import gather_market_context

db = shared_fixtures.db


def reviewed(db, *, quantity=None):
    row, _ = sent(db)
    from src.app.services.market_analysis import ensure_finding_table

    ensure_finding_table(db)
    terms = quote()
    # The native workflow clock is fixed; consumer validity uses current time.
    from datetime import datetime, timezone

    clock = datetime.now(timezone.utc)
    terms["expires_at"] = (clock + timedelta(hours=1)).isoformat()
    if quantity is not None:
        terms["quantity"] = quantity
    # Keep current reservations valid at the consumer's real wall clock.
    db.execute(
        text("UPDATE inventory_reservation SET expires_at=:expiry"),
        dict(expiry=(clock + timedelta(hours=1)).isoformat()),
    )
    reply = journey.receive(
        db,
        tenant_id="shop",
        enquiry_id=row["id"],
        message_id="current-quote",
        sender_ref="fictional-distributor",
        terms=terms,
        now=clock,
    )
    journey.review(
        db,
        tenant_id="shop",
        enquiry_id=row["id"],
        reply_id=reply["id"],
        reviewer_principal="bob-key",
        now=clock,
    )
    db.commit()
    return row, reply


def ask(db, **changes):
    params = dict(
        query="Market intelligence: what are the supplier lead times?",
        tenant_id="shop",
        result_skus=["SKU"],
        force=True,
        include_graph=False,
        case_id="case",
        case_revision=2,
    )
    params.update(changes)
    return gather_market_context(db, **params)


def test_owned_reviewed_quote_supplies_cited_lead_time_without_wholesale_prices(db):
    _, reply = reviewed(db)
    result = ask(db)
    assert result["delivery_status"] == "available"
    assert result["market_evidence"]["citations"][0]["source_record_id"] == reply["id"]
    assert "5 days" in result["market_evidence"]["findings"][0]["summary"]
    assert "quoted" in result["market_evidence"]["findings"][0]["summary"].lower()
    assert "700" not in result["narration_note"]


@pytest.mark.parametrize(
    "changes",
    [
        dict(tenant_id="foreign"),
        dict(case_id="other"),
        dict(case_revision=3),
        dict(case_id=None, case_revision=None),
        dict(result_skus=["OTHER"]),
    ],
)
def test_quote_cannot_escape_its_case_revision_tenant_or_sku(db, changes):
    reviewed(db)
    result = ask(db, **changes)
    assert result["delivery_status"] == "blocked"
    assert result["market_evidence"]["citations"] == []


def test_expired_or_unreviewed_quote_never_becomes_a_lead_time_answer(db):
    _, reply = reviewed(db)
    db.execute(
        text("UPDATE supplier_enquiry_reply SET status='review_required' WHERE id=:id"),
        {"id": reply["id"]},
    )
    db.commit()
    assert ask(db)["delivery_status"] == "blocked"


def test_partial_quantity_quote_is_an_explicitly_partial_answer(db):
    reviewed(db, quantity=1)
    result = ask(db)
    assert result["delivery_status"] == "partial"
    assert result["delivery_reason"] == "partial_quantity_coverage"
    assert "1 units" in result["market_evidence"]["findings"][0]["summary"]
