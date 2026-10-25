from scripts import benchmark_current_catalog_contracts as benchmark
from scripts import seed_electronics_shop as shop
from scripts.seed_inventory_from_txt import parse_inventory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import pytest


@pytest.mark.parametrize('category,handle', [
    ('laptop','el-6-6'), ('monitor','el-17-1'), ('bag','lb-15'),
    ('hard_drive','el-7-9-14-4'), ('router','el-12-1'), ('tablet','el-6-8'),
    ('headset','el-2-2-7'), ('printer','el-13-4'),
    ('all_in_one','el-6-12'), ('mini_pc','el-6-3'), ('desktop_tower','el-6-3'),
])
def test_source_category_is_enrolled_for_the_fixture_tenant_only(category,handle):
    from src.app.services.taxonomy_registry import classification_nodes_for_skus, sold_nodes
    engine=create_engine('sqlite://')
    with Session(engine) as db:
        row={'sku':'SOURCE-1','category':category,'price_cents':10000}
        shop.enrol_source_category(db,row,tenant_id='fixture-tenant')
        assert classification_nodes_for_skus(db,['SOURCE-1'],tenant_id='fixture-tenant')['SOURCE-1']==handle
        assert handle in sold_nodes(db,tenant_id='fixture-tenant')
        assert classification_nodes_for_skus(db,['SOURCE-1'],tenant_id='other-tenant')=={}
        # An unenrolled tenant is unknown, not an enrolled empty catalogue.
        assert sold_nodes(db,tenant_id='other-tenant') is None
    engine.dispose()


def test_held_or_unknown_source_category_cannot_enrol_taxonomy():
    engine=create_engine('sqlite://')
    with Session(engine) as db:
        assert shop.enrol_source_category(db,{'sku':'HELD','category':'laptop','price_cents':None},tenant_id='fixture') is False
        assert shop.enrol_source_category(db,{'sku':'UNKNOWN','category':'unrecognised','price_cents':100},tenant_id='fixture') is False
    engine.dispose()


def test_empty_brand_corpus_is_insufficient_not_a_passing_benchmark():
    facts = [dict(sku='unknown', name='Generic monitor', brand=None,
                  category='monitor', price_cents=10000, active=1)]
    def forbidden(*args, **kwargs):
        raise AssertionError('No retrieval case can be constructed')
    result = benchmark.evaluate(facts, forbidden)
    assert result['passed'] is False
    assert result['status'] == 'insufficient_data'
    assert result['median_ms'] is None
    assert result['cases'] == []


def test_benchmark_checks_every_repeat_and_case_insensitive_brands():
    facts = [dict(sku='a', name='ASUS A', brand='ASUS', category='laptop',
                  price_cents=50000, active=1),
             dict(sku='b', name='Asus B', brand='Asus', category='laptop',
                  price_cents=50000, active=1)]
    calls = []
    def retrieve(*args, **kwargs):
        calls.append(kwargs)
        return [{'sku':'a'}] if len(calls) == 1 else [{'sku':'a'}, {'sku':'b'}]
    result = benchmark.evaluate(facts, retrieve)
    assert len(result['cases']) == 2
    assert result['passed'] is False
    assert result['cases'][0]['missing'] == ['b']


def test_fixture_keeps_parsed_category_and_reviewed_title_brand():
    row = parse_inventory('Dell Example Laptop\nPrice: 1000')[0]
    unknown = parse_inventory('Unlisted Example Monitor\nPrice: 1000')[0]
    engine = create_engine('sqlite://')
    shop.Product.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE products ADD COLUMN brand TEXT'))
        connection.execute(text('ALTER TABLE products ADD COLUMN category TEXT'))
    with Session(engine) as db:
        product = shop.add_product(db, row)
        shop.add_product(db, unknown)
        assert product.specs['catalog_import']['fit_authority'] == 'none'
        db.commit()
    with engine.connect() as connection:
        records = {r.sku:r for r in connection.execute(text('SELECT sku, brand, category FROM products'))}
        assert records[row['sku']].category == 'laptop'
        assert records[row['sku']].brand == 'Dell'
        assert records[unknown['sku']].brand is None
    engine.dispose()


def test_legacy_import_persists_filter_metadata_and_is_idempotent(monkeypatch):
    from scripts import seed_inventory_from_txt as importer
    engine = create_engine('sqlite://')
    shop.Product.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE products ADD COLUMN brand TEXT'))
        connection.execute(text('ALTER TABLE products ADD COLUMN category TEXT'))
        connection.execute(text('CREATE TABLE inventory(id TEXT,product_id TEXT,stock INTEGER,warehouse TEXT,updated_at TEXT)'))
    monkeypatch.setattr(importer, '_write_svgs', lambda rows: 0)
    rows = parse_inventory('Dell Example Laptop\nPrice: 1000')
    with Session(engine) as db:
        assert importer.seed(db, rows)['inserted'] == 1
        assert importer.seed(db, rows)['inserted'] == 0
        record = db.execute(text('SELECT brand,category FROM products')).one()
        assert tuple(record) == ('Dell', 'laptop')
        assert db.execute(text('SELECT COUNT(*) FROM inventory')).scalar_one() == 1
    engine.dispose()
