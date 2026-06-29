"""Phase 3 — procurement notifications: the operator's unseen feed (write / read / mark-seen)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment.notifications import (
    list_notifications, mark_seen, notify, unseen_count)


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_notify_then_read_unseen_then_mark_seen(db):
    a = notify(db, kind="cases_materialized", summary="2 sourcing case(s) created.", ref="order-1")
    b = notify(db, kind="supplier_oob", summary="Supplier x reported out_of_stock.", ref="x.example")
    assert a and b
    assert unseen_count(db) == 2

    unseen = list_notifications(db, unseen_only=True)
    assert {n["id"] for n in unseen} == {a, b}
    assert unseen[0]["summary"]  # newest first, populated

    # mark ONE seen → unseen drops to 1
    assert mark_seen(db, ids=[a]) == 1
    assert unseen_count(db) == 1
    assert {n["id"] for n in list_notifications(db, unseen_only=True)} == {b}

    # mark ALL seen → 0
    assert mark_seen(db) == 1
    assert unseen_count(db) == 0
    # the full feed still lists them (seen=True), newest first
    assert len(list_notifications(db)) == 2


def test_notify_blank_summary_is_noop(db):
    assert notify(db, kind="x", summary="") is None
    assert unseen_count(db) == 0
