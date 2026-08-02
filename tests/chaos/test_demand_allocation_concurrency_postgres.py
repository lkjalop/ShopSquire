"""PostgreSQL certification for the shadow demand allocator.

SQLite contract tests prove arithmetic; only PostgreSQL can prove the pool-row lock prevents
double allocation under simultaneous buyer commitments. Set TEST_POSTGRES_URL to run.
"""
from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.demand_allocation import allocate_committed, record_demand, upsert_supply_snapshot


@pytest.fixture()
def postgres_sessions():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL is required for real PostgreSQL concurrency tests")
    admin = create_engine(url, future=True)
    if admin.dialect.name != "postgresql":
        pytest.skip("TEST_POSTGRES_URL must point to PostgreSQL")
    schema = f"demand_race_{uuid.uuid4().hex[:12]}"
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"}, future=True)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as db:
        db.execute(text("""CREATE TABLE demand_commitment (
          id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,case_id TEXT,
          buyer_ref_hash TEXT,sku TEXT NOT NULL,uom TEXT NOT NULL,destination_id TEXT NOT NULL,
          stage TEXT NOT NULL,quantity INTEGER NOT NULL,priority_tier INTEGER NOT NULL,required_by TEXT,
          created_at TEXT NOT NULL,updated_at TEXT NOT NULL,fulfillment_location_id TEXT,
          UNIQUE(tenant_id,idempotency_key))"""))
        db.execute(text("""CREATE TABLE supply_allocation_pool (
          tenant_id TEXT,sku TEXT,uom TEXT,location_id TEXT,atp_quantity INTEGER,snapshot_version TEXT,
          observed_at TEXT,expires_at TEXT,source_id TEXT,source_authority TEXT,completeness TEXT,
          source_observation_id TEXT,PRIMARY KEY(tenant_id,sku,uom,location_id))"""))
        db.execute(text("""CREATE TABLE demand_allocation (
          id TEXT PRIMARY KEY,tenant_id TEXT,demand_id TEXT,sku TEXT,uom TEXT,location_id TEXT,
          quantity INTEGER,status TEXT,created_at TEXT,released_at TEXT,
          UNIQUE(tenant_id,demand_id,location_id))"""))
        db.execute(text("""CREATE TABLE temporal_dependency (
          id TEXT PRIMARY KEY,tenant_id TEXT,source_type TEXT,source_id TEXT,source_version TEXT,
          derived_type TEXT,derived_id TEXT,status TEXT,created_at TEXT,invalidated_at TEXT,
          invalidation_reason TEXT,
          UNIQUE(tenant_id,source_type,source_id,source_version,derived_type,derived_id))"""))
    try:
        yield sessions
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def test_eight_simultaneous_allocators_cannot_exceed_atp(postgres_sessions):
    with postgres_sessions.begin() as db:
        for index in range(8):
            record_demand(
                db, tenant_id="t1", idempotency_key=f"order-{index}", sku="SKU-1",
                quantity=2, destination_id="SYD", stage="committed", priority_tier=50,
                fulfillment_location_id="SYD",
            )
        upsert_supply_snapshot(
            db, tenant_id="t1", sku="SKU-1", uom="each", location_id="SYD",
            atp_quantity=9, snapshot_version="v1", observed_at="2026-08-02T00:00:00Z",
            source_id="wms", source_authority="authoritative", completeness="source_supplied",
            source_observation_id="obs-v1",
        )

    barrier = threading.Barrier(8)

    def contender():
        barrier.wait(timeout=10)
        with postgres_sessions() as db:
            outcome = allocate_committed(db, tenant_id="t1", sku="SKU-1", location_id="SYD")
            db.commit()
            return outcome

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = [future.result(timeout=30) for future in [pool.submit(contender) for _ in range(8)]]

    with postgres_sessions() as db:
        allocated = int(db.execute(text(
            "SELECT COALESCE(SUM(quantity),0) FROM demand_allocation WHERE status='allocated'"
        )).scalar_one())
        duplicate_locations = int(db.execute(text(
            "SELECT COUNT(*) FROM (SELECT demand_id,location_id FROM demand_allocation "
            "GROUP BY demand_id,location_id HAVING COUNT(*) > 1) duplicates"
        )).scalar_one())
    assert allocated == 9
    assert duplicate_locations == 0
    assert all(outcome["conservation_ok"] for outcome in outcomes)
