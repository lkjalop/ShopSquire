"""Validate the 20260627_support_objection migration: table created, idempotent, drift-free, chains off
the competitor head (keeping a single alembic head)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

_MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260627_support_objection.py"
_EXPECTED = {"support_objection"}


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig_support_objection", _MIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _apply(conn, statements):
    for s in statements:
        conn.execute(text(s))


def test_metadata(mig):
    assert mig.revision == "20260627_support_objection"
    assert mig.down_revision == "20260627_competitor_observation"


def test_upgrade_idempotent(mig):
    eng = create_engine("sqlite://", future=True)
    for _ in range(2):
        with eng.begin() as conn:
            _apply(conn, mig.TABLE_STATEMENTS)
            _apply(conn, mig.INDEX_STATEMENTS)
    assert _EXPECTED <= set(inspect(eng).get_table_names())


def test_migration_matches_runtime(mig):
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.app.services import support_objection_source as so

    runtime = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=runtime, future=True)()
    so.ensure_table(s)
    s.commit()
    migrated = create_engine("sqlite://", future=True)
    with migrated.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)
    ri, mi = inspect(runtime), inspect(migrated)
    for t in _EXPECTED:
        assert {c["name"] for c in ri.get_columns(t)} == {c["name"] for c in mi.get_columns(t)}, f"{t} drift"
