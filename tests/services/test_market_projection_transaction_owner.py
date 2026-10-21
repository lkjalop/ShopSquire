"""Projection reads preserve the caller's transaction and connection lease."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import create_runtime_engine
from src.app.services.market_projection import load_projection_inputs


@pytest.mark.parametrize('backend', ['static', 'wal'])
@pytest.mark.parametrize('tenant,optional', [('default', False), ('default', True), ('tenant-owned', False), ('tenant-owned', True)])
def test_projection_read_preserves_pending_caller_work(tmp_path, backend, tenant, optional):
    engine = (create_engine('sqlite://', poolclass=StaticPool)
              if backend == 'static' else create_runtime_engine('sqlite:///' + (tmp_path / 'owned.sqlite3').as_posix()))
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE pending_business(value INTEGER)'))
            if optional:
                connection.execute(text('CREATE TABLE sales_metrics(sku TEXT,quantity INTEGER,event_time TEXT)'))
                connection.execute(text('CREATE TABLE inventory_atp_fact(tenant_id TEXT,sku TEXT,location_id TEXT,on_hand_quantity INTEGER,committed_quantity INTEGER,confirmed_quantity INTEGER,observed_at TEXT,source_system TEXT,confidence REAL,source_record_id TEXT,status TEXT)'))
                connection.execute(text('CREATE TABLE fulfillment_case(id TEXT,tenant_id TEXT)'))
                connection.execute(text('CREATE TABLE fulfillment_case_version(case_id TEXT,state_json TEXT,valid_from TEXT)'))
        with Session(engine) as db:
            db.execute(text('INSERT INTO pending_business VALUES (17)'))
            lease = db.connection()
            loaded = load_projection_inputs(db, tenant_id=tenant)
            assert loaded['sales'] == loaded['inventory'] == loaded['cases'] == []
            assert db.connection() is lease and lease.in_transaction()
            assert db.scalar(text('SELECT value FROM pending_business')) == 17
            db.rollback()
        with engine.connect() as observer:
            assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
    finally:
        engine.dispose()


def test_projection_read_does_not_borrow_a_second_connection(tmp_path):
    engine = create_engine('sqlite:///' + (tmp_path / 'single-lease.sqlite3').as_posix(),
                          pool_size=1, max_overflow=0, pool_timeout=0.2)
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE pending_business(value INTEGER)'))
        with Session(engine) as db:
            db.execute(text('INSERT INTO pending_business VALUES (23)'))
            loaded = load_projection_inputs(db, tenant_id='default')
            assert loaded['sales'] == []
            assert db.scalar(text('SELECT value FROM pending_business')) == 23
            db.rollback()
        with engine.connect() as observer:
            assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
    finally:
        engine.dispose()
