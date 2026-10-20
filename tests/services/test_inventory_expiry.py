from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from tests.services.test_inventory_transactions import engine, stock
from src.app.services import inventory_transactions as inventory

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


def reserve(db, **changes):
    return inventory.reserve(db, **{**dict(tenant_id='shop', reservation_id='r1', sku='SKU',
        location_id='store', quantity=10, expires_at=NOW+timedelta(minutes=30), now=NOW), **changes})


def test_expiry_releases_once_and_shipping_cannot_bypass_it(engine):
    with Session(engine) as db:
        reserve(db); db.commit()
        assert inventory.expire_due(db, tenant_id='shop', now=NOW)==[]
        due=NOW+timedelta(minutes=30)
        with pytest.raises(ValueError, match='reservation_expired'):
            inventory.transition(db, tenant_id='shop', reservation_id='r1', kind='ship', event_id='ship', now=due)
        assert stock(db)==(15,10,5)
        assert len(inventory.expire_due(db, tenant_id='shop', now=due))==1
        assert inventory.expire_due(db, tenant_id='shop', now=due)==[]
        assert stock(db)==(15,0,15)
        assert db.execute(text("SELECT COUNT(*) FROM inventory_effect_event WHERE kind='expire'")).scalar()==1


def test_expiry_scope_rollback_and_bounded_batch(engine):
    with Session(engine) as db:
        reserve(db); db.commit()
        due=NOW+timedelta(hours=1)
        assert inventory.expire_due(db, tenant_id='other', now=due)==[]
        inventory.expire_due(db, tenant_id='shop', now=due)
        db.rollback()
        assert stock(db)==(15,10,5)
        for invalid in (0, -1, True, 1001):
            with pytest.raises(ValueError): inventory.expire_due(db, tenant_id='shop', now=due, limit=invalid)


def test_expiry_is_bound_to_request_and_requires_aware_time(engine):
    with Session(engine) as db:
        reserve(db)
        with pytest.raises(ValueError, match='reservation_conflict'):
            inventory.reserve(db,tenant_id='shop',reservation_id='r1',sku='SKU',location_id='store',
                quantity=10,expires_at=NOW+timedelta(hours=1),now=NOW)
        with pytest.raises(ValueError, match='timezone'):
            inventory.expire_due(db,tenant_id='shop',now=NOW.replace(tzinfo=None))
        assert stock(db)==(15,10,5)


def test_confirmed_shipment_replay_survives_expiry_and_is_not_released(engine):
    with Session(engine) as db:
        reserve(db)
        args=dict(tenant_id='shop',reservation_id='r1',kind='ship',event_id='ship')
        inventory.transition(db,**args,now=NOW)
        assert inventory.transition(db,**args,now=NOW+timedelta(hours=1))['status']=='shipped'
        assert inventory.expire_due(db,tenant_id='shop',now=NOW+timedelta(hours=1))==[]
        assert stock(db)==(5,0,5)


def test_concurrent_expiry_workers_release_each_hold_once(engine):
    from concurrent.futures import ThreadPoolExecutor
    with Session(engine) as db:
        reserve(db); db.commit()
    def worker(_):
        with Session(engine) as db:
            rows=inventory.expire_due(db,tenant_id='shop',now=NOW+timedelta(hours=1))
            db.commit()
            return len(rows)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker,[1,2]))==[0,1]
    with Session(engine) as db:
        assert stock(db)==(15,0,15)


def test_batch_limit_and_invalid_new_deadline(engine):
    with Session(engine) as db:
        with pytest.raises(ValueError,match='future_reservation_expiry_required'):
            reserve(db,expires_at=NOW)
        assert stock(db)==(15,0,15)
        reserve(db,quantity=1)
        reserve(db,reservation_id='r2',quantity=1)
        due=NOW+timedelta(hours=1)
        assert len(inventory.expire_due(db,tenant_id='shop',now=due,limit=1))==1
        assert stock(db)==(15,1,14)
        assert len(inventory.expire_due(db,tenant_id='shop',now=due,limit=1))==1
        assert stock(db)==(15,0,15)


@pytest.mark.parametrize('other_kind',['ship','cancel'])
def test_expiry_races_cannot_release_or_ship_a_hold_twice(engine,other_kind):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    with Session(engine) as db:
        reserve(db);db.commit()
    barrier=Barrier(2)
    def worker(kind):
        with Session(engine) as db:
            barrier.wait(timeout=5)
            try:
                inventory.transition(db,tenant_id='shop',reservation_id='r1',kind=kind,
                    event_id='race:'+kind,now=NOW+timedelta(hours=1))
                db.commit();return True
            except ValueError:
                db.rollback();return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(worker,['expire',other_kind]))
    assert sum(results)==1
    with Session(engine) as db:
        assert stock(db)==(15,0,15)
        assert db.execute(text("SELECT COUNT(*) FROM inventory_effect_event WHERE kind IN ('expire','cancel','ship')")).scalar_one()==1
