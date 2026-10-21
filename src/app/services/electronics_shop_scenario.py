"""Isolated portfolio fixture using existing commerce tables; never an effect permit.

The caller owns the transaction. Seeding explicitly resets this synthetic scenario's
stock; it is not an inventory-sync operation and must not run during a buyer journey.
"""
from datetime import datetime
from pathlib import Path
import hashlib
import json

from sqlalchemy import text, inspect

from src.app.services import commerce_catalog, supplier_catalog


def _scenario():
    return json.loads((Path(__file__).resolve().parents[3] / 'config/electronics_shop_scenario.json').read_text(encoding='utf-8'))


def seed_scenario(db, *, tenant_id, sku, retail_cents):
    if not tenant_id.startswith('synthetic-'):
        raise ValueError('synthetic tenant required')
    if not sku or type(retail_cents) is not int or retail_cents <= 0:
        raise ValueError('exact sku and positive integer retail cents required')
    for table in ('inventory_reservation','inventory_stock_movement'):
        if inspect(db.connection()).has_table(table):
            transactional = db.execute(text(f'SELECT 1 FROM {table} '
                'WHERE tenant_id=:tenant AND sku=:sku LIMIT 1'), {'tenant':tenant_id, 'sku':sku}).first()
            if transactional:
                raise ValueError('transactional_inventory_exists: use a new isolated scenario database')
    fixture = _scenario()
    from src.app.services.shop_operational_history import record_fixture_history
    record_fixture_history(db,tenant_id=tenant_id,sku=sku,fixture=fixture)
    source = 'simulation:' + fixture['id']
    supplier_catalog.ensure_tables(db)
    for location in fixture['locations']:
        on_hand = location['opening'] - location['sold'] + location['returned']
        if not commerce_catalog.upsert_inventory(db, tenant_id=tenant_id, sku=sku,
                location_id=location['id'], on_hand=on_hand, reserved=location['reserved'], source=source):
            raise RuntimeError('scenario_inventory_write_failed')
    if not commerce_catalog.upsert_price(db, tenant_id=tenant_id, sku=sku,
            list_cents=retail_cents, currency=fixture['currency'], source=source,
            valid_from=fixture['effective_from'], valid_to=fixture['effective_to']):
        raise RuntimeError('scenario_price_write_failed')
    identity = hashlib.sha256(f'{tenant_id}:{sku}:{source}'.encode()).hexdigest()
    supplier_id = 'simulation-' + identity[:24]
    supplier = fixture['supplier']
    cost = retail_cents * supplier['cost_basis_points_of_retail'] // 10000
    params = dict(id=identity, tenant=tenant_id, sku=sku, supplier=supplier_id,
                  cost=cost, currency=fixture['currency'], start=fixture['effective_from'],
                  end=fixture['effective_to'], source=source, provenance=json.dumps(fixture))
    db.execute(text("INSERT INTO suppliers (id,name) VALUES (:id,:name) ON CONFLICT(id) DO NOTHING"),
               {'id': supplier_id, 'name': supplier['name']})
    existing = db.execute(text('SELECT 1 FROM supplier_products WHERE supplier_id=:s AND sku=:k'),
                          dict(s=supplier_id,k=sku)).first()
    if existing is None:
        supplier_catalog._insert_supplier_product(db, dict(s=supplier_id,k=sku,moq=supplier['moq'],
            mov=0,lt=None,rg='AU',ot=0,pb=json.dumps(supplier['price_breaks']),cs='simulation'))
    db.execute(text("""INSERT INTO supplier_offer
        (id,tenant_id,supplier_id,sku,cost_kind,purchase_unit_cost_cents,landed_unit_cost_cents,
         currency,tax_basis,effective_from,effective_to,source_system,source_record_id,
         provenance_json,confidence,simulation_only,status)
        VALUES (:id,:tenant,:supplier,:sku,'demo_estimate',:cost,:cost,:currency,'simulation',
         :start,:end,:source,:id,:provenance,0,1,'active')
        ON CONFLICT(id) DO UPDATE SET purchase_unit_cost_cents=excluded.purchase_unit_cost_cents,
         landed_unit_cost_cents=excluded.landed_unit_cost_cents,provenance_json=excluded.provenance_json
        """), params)
    return dict(tenant_id=tenant_id, sku=sku, simulation_only=True, source=source)


def assess_request(db, *, tenant_id, sku, quantity, now):
    """Read-only scenario assessment. Future deliveries are never current stock."""
    if not tenant_id.startswith('synthetic-') or type(quantity) is not int or quantity <= 0:
        raise ValueError('synthetic tenant and positive integer quantity required')
    if now.tzinfo is None:
        raise ValueError('timezone-aware decision time required')
    stock = commerce_catalog.batch_available(db, [sku], tenant_id=tenant_id)
    if sku not in stock:
        raise ValueError('scenario_stock_unknown')
    price_row = db.execute(text("""SELECT list_cents,valid_from,valid_to FROM price_book_entry
        WHERE tenant_id=:tenant AND sku=:sku AND channel='default' AND currency='AUD'"""),
        dict(tenant=tenant_id,sku=sku)).one_or_none()
    price = None
    if price_row and datetime.fromisoformat(price_row[1]) <= now < datetime.fromisoformat(price_row[2]):
        price = price_row[0]
    shortfall = max(0, quantity - stock[sku])
    offers = []
    offer = supplier_catalog.best_supplier_cost(db, sku, tenant_id=tenant_id, as_of=now)
    if offer and offer['simulation_only'] and shortfall:
        terms = offer['provenance_chain']['supplier']
        capacity = terms['available_now'] + terms['later_quantity']
        order_quantity = min(max(shortfall, terms['moq']), capacity)
        discount = max([0] + [b['discount_pct'] for b in terms['price_breaks'] if order_quantity >= b['min_qty']])
        unit = offer['unit_cost_cents'] * (100 - discount) // 100
        offers.append(dict(supplier_id=offer['supplier_id'], order_quantity=order_quantity,
                           unit_cost_cents=unit, order_cost_cents=unit * order_quantity,
                           available_now=min(order_quantity, terms['available_now']),
                           later_quantity=max(0, order_quantity - terms['available_now']),
                           uncovered_shortfall=max(0, shortfall - order_quantity),
                           later_arrival=terms['later_arrival'], simulation_only=True))
    payload = dict(tenant_id=tenant_id, sku=sku, quantity=quantity, retail_unit_cents=price,
                   available=stock[sku], supplier_offers=offers)
    return dict(payload, shortfall=shortfall, retail_total_cents=price * quantity if price is not None else None,
                stock_snapshot_time=_scenario()['effective_from'],
                request_digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest(),
                delivery_status='unconfirmed', commerce_authority='none', simulation_only=True)
