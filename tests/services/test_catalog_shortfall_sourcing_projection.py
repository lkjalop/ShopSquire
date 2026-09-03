import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.orm import Base, ProductConfiguration
from src.app.routers.shopping_cases import (
    _case_budget_cents,
    _catalog_shortfall_alternative,
)


def _db():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE conversation_case_state ("
            "id TEXT PRIMARY KEY, tenant_id TEXT, case_id TEXT, version INTEGER, state_json JSON)"
        ))
    return sessionmaker(bind=engine, future=True)()


def test_shortfall_uses_revision_bound_budget_and_records_alternative_gap():
    db = _db()
    state = {
        "procurement_case_state": {
            "budget": {"amount_minor": 250_000, "currency": "AUD", "scope": "total"},
        },
    }
    db.execute(text(
        "INSERT INTO conversation_case_state(id,tenant_id,case_id,version,state_json) "
        "VALUES ('state-1','default','case-1',2,:state)"
    ), {"state": json.dumps(state)})
    db.add(ProductConfiguration(
        tenant_id="default", sku="ALT-1", title="Nearest workstation",
        configuration_hash="hash-1", price_cents=300_000, currency="AUD",
    ))
    db.commit()

    budget = _case_budget_cents(db, tenant_id="default", case_id="case-1")
    alternative, gap = _catalog_shortfall_alternative(
        db, tenant_id="default",
        exclusion={"sku": "ALT-1", "reason": "verified_hard_failure"},
        budget_cents=budget,
    )

    assert budget == 250_000
    assert gap == 50_000
    assert alternative == {
        "sku": "ALT-1",
        "reason": "verified_hard_failure",
        "status": "not_qualified_or_unavailable",
        "title": "Nearest workstation",
        "price_cents": 300_000,
        "currency": "AUD",
    }
