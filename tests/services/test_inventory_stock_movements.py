from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.services.test_inventory_transactions import engine
from src.app.services.commerce_catalog import upsert_inventory
from src.app.services import inventory_transactions as inventory


def move(db, **changes):
    return inventory.move_stock(db, **{**dict(tenant_id='shop',source_reference='receipt:1',
        sku='SKU',destination_location='store',quantity=4,kind='receive',source_location=None),**changes})


def balances(db):
    return [tuple(row) for row in db.execute(text("SELECT location_id,on_hand,reserved,available FROM inventory_level WHERE tenant_id='shop' ORDER BY location_id"))]


def test_receipt_replay_conflict_and_caller_rollback(engine):
    with Session(engine) as db:
        first=move(db);assert move(db)==first
        assert balances(db)==[('store',19,0,19)]
        with pytest.raises(ValueError,match='conflict'):move(db,quantity=5)
        db.rollback()
        assert balances(db)==[('store',15,0,15)]
        assert db.execute(text('SELECT COUNT(*) FROM inventory_stock_movement')).scalar_one()==0


def test_transfer_is_atomic_and_cannot_move_reserved_stock(engine):
    with Session(engine) as db:
        upsert_inventory(db,tenant_id='shop',sku='SKU',location_id='warehouse',on_hand=0,reserved=0)
        db.commit()
        inventory.reserve(db,tenant_id='shop',reservation_id='hold',sku='SKU',location_id='store',quantity=12)
        with pytest.raises(ValueError):move(db,kind='transfer',source_location='store',destination_location='warehouse')
        assert balances(db)==[('store',15,12,3),('warehouse',0,0,0)]
        move(db,kind='transfer',source_location='store',destination_location='warehouse',quantity=3)
        assert balances(db)==[('store',12,12,0),('warehouse',3,0,3)]
        assert db.execute(text('SELECT COUNT(*) FROM inventory_stock_movement')).scalar_one()==1


def test_missing_destination_cannot_lose_source_units(engine):
    with Session(engine) as db:
        with pytest.raises(ValueError):move(db,kind='transfer',source_location='store',destination_location='missing')
        assert balances(db)==[('store',15,0,15)]
        with pytest.raises(ValueError):move(db,tenant_id='other')
        assert balances(db)==[('store',15,0,15)]


def test_concurrent_transfers_cannot_oversell(engine):
    with Session(engine) as db:
        upsert_inventory(db,tenant_id='shop',sku='SKU',location_id='warehouse',on_hand=0,reserved=0)
        db.commit()
    def worker(ref):
        with Session(engine) as db:
            try:
                move(db,source_reference=ref,kind='transfer',source_location='store',destination_location='warehouse',quantity=10)
                db.commit();return True
            except ValueError:
                db.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker,['transfer:a','transfer:b']))==[False,True]
    with Session(engine) as db:
        assert balances(db)==[('store',5,0,5),('warehouse',10,0,10)]
