import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.services.shop_operational_history import record_fixture_history, replay_history


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        yield db
    engine.dispose()


def fixture():
    return dict(
        id="fixture",
        simulation_only=True,
        effective_from="2026-09-26T00:00:00+00:00",
        locations=[dict(id="store", opening=10, sold=3, returned=1, reserved=2)],
    )


def test_history_replays_exact_balance_and_is_idempotent(db):
    for _ in range(2):
        record_fixture_history(db, tenant_id="synthetic-shop", sku="SKU", fixture=fixture())
    result = replay_history(db, tenant_id="synthetic-shop", sku="SKU", scenario_id="fixture")
    assert len(result["events"]) == 4
    assert result["locations"] == [dict(location_id="store", on_hand=8, reserved=2, available=6)]
    assert result["simulation_only"] is True
    assert result["commerce_authority"] == "none"
    assert (
        replay_history(db, tenant_id="synthetic-other", sku="SKU", scenario_id="fixture")["events"]
        == []
    )


def test_same_fixture_identity_cannot_rewrite_history(db):
    data = fixture()
    record_fixture_history(db, tenant_id="synthetic-shop", sku="SKU", fixture=data)
    data["locations"][0]["sold"] = 4
    with pytest.raises(ValueError, match="history_conflict"):
        record_fixture_history(db, tenant_id="synthetic-shop", sku="SKU", fixture=data)


@pytest.mark.parametrize(
    "changes", [dict(sold=11), dict(reserved=9), dict(sold=-1), dict(returned=True)]
)
def test_impossible_or_malformed_movements_leave_no_history(db, changes):
    data = fixture()
    data["locations"][0].update(changes)
    with pytest.raises(ValueError):
        record_fixture_history(db, tenant_id="synthetic-shop", sku="SKU", fixture=data)
    assert (
        replay_history(db, tenant_id="synthetic-shop", sku="SKU", scenario_id="fixture")["events"]
        == []
    )


def test_real_tenant_cannot_be_seeded(db):
    with pytest.raises(ValueError, match="synthetic"):
        record_fixture_history(db, tenant_id="customer", sku="SKU", fixture=fixture())
