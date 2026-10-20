"""Canonical inventory conservation on an explicitly isolated PostgreSQL database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier, Condition, get_ident
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.app.services import inventory_transactions as inventory
from src.app.services.commerce_catalog import upsert_inventory


@pytest.fixture
def stock_engine():
    value = os.getenv("TEST_POSTGRES_URL")
    if not value:
        pytest.skip("TEST_POSTGRES_URL is required for isolated inventory concurrency")
    url = make_url(value)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"127.0.0.1", "localhost"}
    assert (url.database or "").startswith("shopsquire_cert_")
    admin = create_engine(url)
    schema = "inventory_" + uuid4().hex
    with admin.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    try:
        with Session(engine) as db:
            inventory.ensure_tables(db)
            for tenant in ("shop", "other"):
                for location in ("a", "b"):
                    assert upsert_inventory(db, tenant_id=tenant, sku="SKU", location_id=location,
                                            on_hand=15, reserved=0)
            db.commit()
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def balances(db):
    return [tuple(row) for row in db.execute(text(
        "SELECT tenant_id,location_id,on_hand,reserved,available FROM inventory_level "
        "ORDER BY tenant_id,location_id"))]


def race(count, work):
    barrier = Barrier(count)

    def contender(index):
        barrier.wait(timeout=10)
        return work(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(contender, i) for i in range(count)]
        return [future.result(timeout=30) for future in futures]


def hold(db, identity="hold", **changes):
    return inventory.reserve(db, **{**dict(tenant_id="shop", reservation_id=identity,
        sku="SKU", location_id="a", quantity=3), **changes})


def test_eight_buyers_cannot_oversell_or_touch_other_stock(stock_engine):
    def reserve(index):
        with Session(stock_engine) as db:
            try:
                hold(db, "buyer-" + str(index))
                db.commit()
                return True
            except ValueError:
                db.rollback()
                return False

    assert race(8, reserve).count(True) == 5
    with Session(stock_engine) as db:
        assert balances(db) == [("other", "a", 15, 0, 15), ("other", "b", 15, 0, 15),
                                ("shop", "a", 15, 15, 0), ("shop", "b", 15, 0, 15)]
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_reservation")) == 5
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_effect_event")) == 5


@pytest.mark.parametrize("kind", ["cancel", "ship"])
def test_same_effect_replay_changes_stock_once(stock_engine, kind):
    with Session(stock_engine) as db:
        hold(db)
        db.commit()

    def transition(_):
        with Session(stock_engine) as db:
            result = inventory.transition(db, tenant_id="shop", reservation_id="hold",
                                          kind=kind, event_id="same-effect")
            db.commit()
            return result["status"]

    assert len(set(race(4, transition))) == 1
    with Session(stock_engine) as db:
        row = next(row for row in balances(db) if row[:2] == ("shop", "a"))
        assert row[2:] == ((15, 0, 15) if kind == "cancel" else (12, 0, 12))
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_effect_event WHERE kind=:kind"),
                         {"kind": kind}) == 1


@pytest.mark.parametrize("opponent", ["ship", "cancel"])
def test_expiry_race_has_one_stock_effect(stock_engine, opponent):
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    with Session(stock_engine) as db:
        hold(db, expires_at=now + timedelta(minutes=1), now=now)
        db.commit()

    def transition(index):
        kind = ("expire", opponent)[index]
        with Session(stock_engine) as db:
            try:
                inventory.transition(db, tenant_id="shop", reservation_id="hold", kind=kind,
                                     event_id=kind, now=now + timedelta(minutes=2))
                db.commit()
                return True
            except ValueError:
                db.rollback()
                return False

    assert race(2, transition).count(True) == 1
    with Session(stock_engine) as db:
        assert next(row[2:] for row in balances(db) if row[:2] == ("shop", "a")) == (15, 0, 15)
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_effect_event WHERE kind<>'reserve'")) == 1


def test_failed_transfer_and_caller_rollback_preserve_every_location(stock_engine):
    with Session(stock_engine) as db:
        before = balances(db)
        with pytest.raises(ValueError, match="stock_unavailable"):
            inventory.move_stock(db, tenant_id="shop", source_reference="bad", kind="transfer",
                                 sku="SKU", source_location="a", destination_location="missing", quantity=5)
        assert balances(db) == before
        inventory.move_stock(db, tenant_id="shop", source_reference="good", kind="transfer",
                             sku="SKU", source_location="a", destination_location="b", quantity=5)
        db.rollback()
        assert balances(db) == before
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_stock_movement")) == 0


def test_opposite_transfers_complete_without_database_deadlock(stock_engine, monkeypatch):
    original = inventory._stock
    first_updates = set()
    condition = Condition()

    def overlap_first_updates(*args, **kwargs):
        result = original(*args, **kwargs)
        identity = get_ident()
        with condition:
            if identity not in first_updates:
                first_updates.add(identity)
                condition.notify_all()
                # Correct lock ordering serializes these writes. A bounded wait
                # still exposes a cycle when each worker holds a different row.
                condition.wait_for(lambda: len(first_updates) == 2, timeout=0.5)
        return result

    monkeypatch.setattr(inventory, "_stock", overlap_first_updates)

    def transfer(index):
        source, destination = (("a", "b"), ("b", "a"))[index]
        with Session(stock_engine) as db:
            inventory.move_stock(db, tenant_id="shop", source_reference="transfer-" + str(index),
                                 kind="transfer", sku="SKU", source_location=source,
                                 destination_location=destination, quantity=5)
            db.commit()

    race(2, transfer)
    with Session(stock_engine) as db:
        assert all(row[2:] == (15, 0, 15) for row in balances(db))
        assert db.scalar(text("SELECT COUNT(*) FROM inventory_stock_movement")) == 2
