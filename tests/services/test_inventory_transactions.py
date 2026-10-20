from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.app.services.commerce_catalog import upsert_inventory
from src.app.services.inventory_transactions import ensure_tables, reserve, transition


@pytest.fixture
def engine(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'stock.sqlite3'),connect_args={'timeout':10})
    with Session(engine) as db:
        ensure_tables(db)
        upsert_inventory(db,tenant_id='shop',sku='SKU',location_id='store',on_hand=15,reserved=0)
        db.commit()
    yield engine
    engine.dispose()


def hold(db,identity='r1',quantity=10):
    return reserve(db,tenant_id='shop',reservation_id=identity,sku='SKU',location_id='store',quantity=quantity)


def action(db,kind,key,quantity=None):
    return transition(db,tenant_id='shop',reservation_id='r1',kind=kind,event_id=key,quantity=quantity)


def stock(db):
    return tuple(db.execute(text("SELECT on_hand,reserved,available FROM inventory_level WHERE tenant_id='shop'")).one())


def test_reservation_cancel_replay_and_identity_conflict(engine):
    with Session(engine) as db:
        hold(db); hold(db)
        assert stock(db)==(15,10,5)
        with pytest.raises(ValueError,match='conflict'):hold(db,quantity=9)
        assert stock(db)==(15,10,5)
        action(db,'cancel','cancel-1'); action(db,'cancel','cancel-1')
        assert stock(db)==(15,0,15)
        assert hold(db)['status']=='cancelled'
        assert stock(db)==(15,0,15)


def test_ship_partial_returns_and_duplicate_return(engine):
    with Session(engine) as db:
        hold(db); action(db,'ship','ship-1')
        assert stock(db)==(5,0,5)
        action(db,'return','return-1',3); action(db,'return','return-1',3)
        assert stock(db)==(8,0,8)
        with pytest.raises(ValueError): action(db,'return','return-2',8)
        assert stock(db)==(8,0,8)
        action(db,'return','return-2',7)
        assert stock(db)==(15,0,15)


def test_caller_rollback_reverts_reservation_and_stock(engine):
    with Session(engine) as db:
        hold(db)
        db.rollback()
        assert stock(db)==(15,0,15)
        assert db.execute(text('SELECT COUNT(*) FROM inventory_reservation')).scalar_one()==0


def test_concurrent_buyers_cannot_oversell(engine):
    def worker(identity):
        with Session(engine) as db:
            try:
                hold(db,identity)
                db.commit()
                return True
            except ValueError:
                db.rollback()
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker,['r1','r2']))==[False,True]
    with Session(engine) as db: assert stock(db)==(15,10,5)


@pytest.mark.parametrize('quantity',[0,-1,True,1.5])
def test_invalid_quantity_cannot_change_stock(engine,quantity):
    with Session(engine) as db:
        with pytest.raises(ValueError): hold(db,quantity=quantity)
        assert stock(db)==(15,0,15)


def test_other_tenant_and_changed_replay_payload_cannot_mutate(engine):
    with Session(engine) as db:
        hold(db)
        with pytest.raises(ValueError):
            transition(db,tenant_id='other',reservation_id='r1',kind='ship',event_id='ship-1')
        action(db,'ship','ship-1')
        with pytest.raises(ValueError,match='conflict'):action(db,'return','ship-1',3)
        assert stock(db)==(5,0,5)
