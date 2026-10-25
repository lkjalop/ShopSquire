import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.app.services.electronics_shop_scenario import seed_scenario
from src.app.services.inventory_transactions import ensure_tables, reserve, transition
from src.app.services.shop_operational_history import reconcile_inventory


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as session:
        seed_scenario(session, tenant_id='synthetic-shop', sku='SKU', retail_cents=100000)
        ensure_tables(session)
        yield session
    engine.dispose()


def report(db, tenant='synthetic-shop'):
    return reconcile_inventory(db, tenant_id=tenant, sku='SKU', scenario_id='electronics-shortfall-v1')


def test_operational_effects_reconcile_to_fixture_opening_history(db):
    reserve(db, tenant_id='synthetic-shop', reservation_id='order', sku='SKU', location_id='warehouse', quantity=4)
    transition(db, tenant_id='synthetic-shop', reservation_id='order', kind='ship', event_id='ship')
    for _ in range(2):
        transition(db, tenant_id='synthetic-shop', reservation_id='order', kind='return', event_id='return', quantity=1)
    result = report(db)
    assert result['consistent'] is True
    warehouse = next(r for r in result['locations'] if r['location_id']=='warehouse')
    assert warehouse['expected'] == {'on_hand':2, 'reserved':0, 'available':2}
    assert warehouse['effect_count'] == 3
    assert result['commerce_authority'] == 'none'


def test_stock_drift_is_reported_without_silently_rewriting_stock(db):
    db.execute(text("UPDATE inventory_level SET on_hand=99 WHERE location_id='warehouse'"))
    assert report(db)['consistent'] is False
    assert db.execute(text("SELECT on_hand FROM inventory_level WHERE location_id='warehouse'")).scalar()==99


def test_missing_stock_and_cross_tenant_baselines_cannot_appear_reconciled(db):
    db.execute(text("DELETE FROM inventory_level WHERE location_id='warehouse'"))
    assert report(db)['consistent'] is False
    with pytest.raises(ValueError, match='baseline_required'):
        report(db, tenant='another-tenant')


def test_receipts_and_both_transfer_legs_reconcile(db):
    from src.app.services.inventory_transactions import move_stock
    move_stock(db,tenant_id='synthetic-shop',source_reference='receipt:1',kind='receive',
        sku='SKU',destination_location='warehouse',quantity=7)
    move_stock(db,tenant_id='synthetic-shop',source_reference='transfer:1',kind='transfer',
        sku='SKU',source_location='warehouse',destination_location='store-a',quantity=4)
    result=report(db)
    assert result['consistent'] is True
    assert next(r for r in result['locations'] if r['location_id']=='warehouse')['expected']['on_hand']==8
    with pytest.raises(ValueError,match='transactional_inventory_exists'):
        seed_scenario(db,tenant_id='synthetic-shop',sku='SKU',retail_cents=100000)
