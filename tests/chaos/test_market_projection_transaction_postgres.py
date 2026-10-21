"""Real PostgreSQL projection reads must fit within the caller's one lease."""
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.chaos.test_request_database_owner_postgres import native_owners
from src.app.services.market_projection import load_projection_inputs


@pytest.mark.parametrize('optional', [False, True])
def test_projection_preserves_pending_business_with_a_single_native_connection(native_owners, optional):
    parent = native_owners[0]
    with parent.connect() as connection:
        schema = connection.scalar(text('SELECT current_schema()'))
    assert re.fullmatch(r'request_owner_[a-f0-9]{32}', schema)
    engine = create_engine(parent.url, pool_size=1, max_overflow=0, pool_timeout=0.2,
                           connect_args={'connect_timeout': 3, 'options': f'-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000'})
    try:
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE pending_business(value INTEGER)'))
            if optional:
                connection.execute(text('CREATE TABLE sales_metrics(sku TEXT,quantity INTEGER,event_time TEXT)'))
                connection.execute(text('CREATE TABLE inventory_atp_fact(tenant_id TEXT,sku TEXT,location_id TEXT,on_hand_quantity INTEGER,committed_quantity INTEGER,confirmed_quantity INTEGER,observed_at TEXT,source_system TEXT,confidence REAL,source_record_id TEXT,status TEXT)'))
                connection.execute(text('CREATE TABLE fulfillment_case(id TEXT,tenant_id TEXT)'))
                connection.execute(text('CREATE TABLE fulfillment_case_version(case_id TEXT,state_json TEXT,valid_from TEXT)'))
        with Session(engine) as db:
            db.execute(text('INSERT INTO pending_business VALUES (29)'))
            lease = db.connection()
            loaded = load_projection_inputs(db, tenant_id='default')
            assert loaded['sales'] == loaded['inventory'] == loaded['cases'] == []
            assert db.connection() is lease and lease.in_transaction()
            assert db.scalar(text('SELECT value FROM pending_business')) == 29
            with parent.connect() as observer:
                assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
            db.rollback()
        with engine.connect() as observer:
            assert observer.scalar(text('SELECT COUNT(*) FROM pending_business')) == 0
    finally:
        engine.dispose()
