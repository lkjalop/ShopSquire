import sqlite3
import pytest
from scripts.reconcile_demo_catalog_identities import apply_repairs


@pytest.fixture
def db():
    connection=sqlite3.connect(':memory:')
    connection.executescript('CREATE TABLE products(sku TEXT PRIMARY KEY,specs TEXT);'
        'CREATE TABLE stock(sku TEXT UNIQUE,quantity INTEGER);')
    connection.execute("INSERT INTO products VALUES ('OLD','{}')")
    connection.execute("INSERT INTO stock VALUES ('OLD',7)")
    connection.commit()
    yield connection
    connection.close()


def repair():return [{'old_sku':'OLD','new_sku':'NEW','new_category':'Desktop'}]


@pytest.mark.parametrize('conflict',['product','dependent','bound_effect'])
def test_identity_conflicts_preserve_all_original_rows(db,conflict):
    if conflict=='product':db.execute("INSERT INTO products VALUES ('NEW','{}')")
    elif conflict=='dependent':db.execute("INSERT INTO stock VALUES ('NEW',11)")
    else:
        db.execute('CREATE TABLE bound_effect(sku TEXT,payload_digest TEXT)')
        db.execute("INSERT INTO bound_effect VALUES ('OLD','immutable-receipt')")
    db.commit();before='\n'.join(db.iterdump())
    with pytest.raises(ValueError):apply_repairs(db,repair())
    assert '\n'.join(db.iterdump())==before


def test_unambiguous_demo_repair_preserves_quantities_and_is_replayable(db):
    counts=apply_repairs(db,repair())
    assert counts=={'products':1,'stock':1}
    assert db.execute('SELECT sku,quantity FROM stock').fetchall()==[('NEW',7)]
    assert apply_repairs(db,repair())=={}
