from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.commerce_catalog import batch_available
from src.app.services.electronics_shop_scenario import seed_scenario, assess_request


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_existing_inventory_service_sees_repeatable_tenant_scoped_stock(db):
    for _ in range(2):
        seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    assert batch_available(db, ['existing-sku'], tenant_id='synthetic-shop') == {'existing-sku': 15}
    assert batch_available(db, ['existing-sku'], tenant_id='other') == {}
    from src.app.services.shop_operational_history import replay_history
    history=replay_history(db,tenant_id='synthetic-shop',sku='existing-sku',scenario_id='electronics-shortfall-v1')
    assert sum(row['available'] for row in history['locations'])==15
    assert sum(row['on_hand'] for row in history['locations'])==17


def test_quantity_expansion_recomputes_shortfall_without_authorizing_effect(db):
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    args = dict(tenant_id='synthetic-shop', sku='existing-sku', now=datetime(2026,9,26,tzinfo=timezone.utc))
    before = assess_request(db, quantity=30, **args)
    after = assess_request(db, quantity=40, **args)
    assert (before['shortfall'], after['shortfall']) == (15, 25)
    assert after['retail_total_cents'] == 4000000
    assert before['request_digest'] != after['request_digest']
    assert after['commerce_authority'] == 'none'
    assert after['delivery_status'] == 'unconfirmed'


def test_expired_quote_does_not_support_new_purchase(db):
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    result = assess_request(db, tenant_id='synthetic-shop', sku='existing-sku', quantity=30,
                            now=datetime(2026,9,28,tzinfo=timezone.utc))
    assert result['supplier_offers'] == []


def test_larger_quantity_discount_is_not_claimed_as_lower_total_cost(db):
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    args = dict(tenant_id='synthetic-shop', sku='existing-sku', now=datetime(2026,9,26,tzinfo=timezone.utc))
    a = assess_request(db, quantity=30, **args)['supplier_offers'][0]
    b = assess_request(db, quantity=40, **args)['supplier_offers'][0]
    assert b['unit_cost_cents'] < a['unit_cost_cents']
    assert b['order_cost_cents'] > a['order_cost_cents']


def test_scenario_rejects_non_synthetic_tenant(db):
    with pytest.raises(ValueError, match='synthetic'):
        seed_scenario(db, tenant_id='customer', sku='existing-sku', retail_cents=100000)


def test_migrated_supplier_identity_schema_is_supported(db):
    db.execute(text('CREATE TABLE supplier_products (id TEXT PRIMARY KEY NOT NULL, supplier_id TEXT NOT NULL, sku TEXT NOT NULL)'))
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    assert db.execute(text('SELECT COUNT(*) FROM supplier_products')).scalar_one() == 1


def test_supplier_cannot_offer_more_than_its_total_simulated_capacity(db):
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    result = assess_request(db,tenant_id='synthetic-shop',sku='existing-sku',quantity=100,
                            now=datetime(2026,9,26,tzinfo=timezone.utc))
    offer = result['supplier_offers'][0]
    assert offer['order_quantity'] == 25
    assert offer['uncovered_shortfall'] == 60
    assert offer['available_now'] + offer['later_quantity'] == 25


def test_reseeding_cannot_erase_transactional_stock(db):
    from src.app.services.inventory_transactions import ensure_tables, reserve
    seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    ensure_tables(db)
    reserve(db, tenant_id='synthetic-shop', sku='existing-sku', location_id='warehouse',
            reservation_id='order-1', quantity=2)
    with pytest.raises(ValueError, match='transactional_inventory_exists'):
        seed_scenario(db, tenant_id='synthetic-shop', sku='existing-sku', retail_cents=100000)
    assert batch_available(db, ['existing-sku'], tenant_id='synthetic-shop')['existing-sku'] == 13
