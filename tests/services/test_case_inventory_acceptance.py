import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.app.models.orm import Base, ShoppingCase
from src.app.services.electronics_shop_scenario import seed_scenario
from src.app.services.inventory_transactions import ensure_tables
from src.app.services.case_inventory_acceptance import accept_request, release_holds


@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ensure_tables(db)
        seed_scenario(db,tenant_id='synthetic-shop',sku='SKU',retail_cents=100000)
        db.add(ShoppingCase(case_id='case',tenant_id='synthetic-shop',uid='buyer',revision=1))
        db.commit()
        yield db
    engine.dispose()


def accept(db, **overrides):
    return accept_request(db,**{**dict(tenant_id='synthetic-shop',case_id='case',uid='buyer',
        expected_revision=1,sku='SKU',quantity=30,idempotency_key='accept-first'),**overrides})


def test_acceptance_and_amendment_replace_holds_atomically(db):
    first=accept(db)
    db.commit()
    assert (first['case_revision'],first['held_quantity'],first['shortfall'])==(2,15,15)
    assert accept(db)==first
    second=accept(db,expected_revision=2,quantity=40,idempotency_key='accept-second')
    db.commit()
    assert (second['case_revision'],second['held_quantity'],second['shortfall'])==(3,15,25)
    assert db.execute(text("SELECT SUM(quantity) FROM inventory_reservation WHERE status='reserved'")).scalar()==15
    assert db.execute(text("SELECT SUM(quantity) FROM inventory_reservation WHERE status='cancelled'")).scalar()==15


def test_accepted_holds_have_persisted_deadlines_and_expiry_reconciles(db):
    from datetime import datetime, timedelta, timezone
    from src.app.services.inventory_transactions import expire_due
    from src.app.services.shop_operational_history import reconcile_inventory
    now=datetime(2026,9,29,tzinfo=timezone.utc)
    accept(db,now=now)
    deadlines=db.execute(text('SELECT expires_at FROM inventory_reservation')).scalars().all()
    assert deadlines and all(datetime.fromisoformat(value)==now+timedelta(minutes=30) for value in deadlines)
    expire_due(db,tenant_id='synthetic-shop',now=now+timedelta(minutes=30))
    assert db.execute(text('SELECT SUM(available) FROM inventory_level')).scalar()==15
    assert reconcile_inventory(db,tenant_id='synthetic-shop',sku='SKU',scenario_id='electronics-shortfall-v1')['consistent']


@pytest.mark.parametrize('changes',[{'quantity':40},{'uid':'other'},{'sku':'other'},{'expected_revision':2}])
def test_changed_replay_or_wrong_buyer_is_rejected(db,changes):
    accept(db)
    db.commit()
    with pytest.raises(ValueError):accept(db,**changes)


def test_rollback_restores_revision_holds_and_selection(db):
    accept(db)
    db.rollback()
    assert db.execute(text("SELECT revision FROM shopping_cases WHERE case_id='case'")).scalar()==1
    assert db.execute(text('SELECT COUNT(*) FROM inventory_reservation')).scalar()==0
    assert db.execute(text('SELECT COUNT(*) FROM shopping_case_fulfillment_selections')).scalar()==0


def test_stale_revision_cannot_replace_holds(db):
    accept(db)
    db.commit()
    with pytest.raises(ValueError,match='revision'):
        accept(db,quantity=40,idempotency_key='new-command')
    assert db.execute(text("SELECT SUM(quantity) FROM inventory_reservation WHERE status='reserved'")).scalar()==15


def test_explicit_release_advances_revision_and_cannot_release_twice(db):
    accept(db);db.commit()
    assert release_holds(db,tenant_id='synthetic-shop',case_id='case',uid='buyer',expected_revision=2)['released_quantity']==15
    db.commit()
    with pytest.raises(ValueError,match='revision'):
        release_holds(db,tenant_id='synthetic-shop',case_id='case',uid='buyer',expected_revision=2)
    assert db.execute(text('SELECT SUM(available) FROM inventory_level')).scalar()==15
