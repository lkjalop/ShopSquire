"""Validate the 20260626_catalog_entities migration: creates product + variant + external_ref,
idempotent, drift-free vs the runtime DDL, chains off the commerce-catalog head."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

_MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260626_catalog_entities.py"
_EXPECTED = {"product", "variant", "external_ref"}


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig_catalog_entities", _MIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _apply(conn, statements):
    for s in statements:
        conn.execute(text(s))


def test_metadata(mig):
    assert mig.revision == "20260626_catalog_entities"
    assert mig.down_revision == "20260626_commerce_catalog"


def test_upgrade_creates_tables_idempotent(mig):
    eng = create_engine("sqlite://", future=True)
    for _ in range(2):
        with eng.begin() as conn:
            _apply(conn, mig.TABLE_STATEMENTS)
            _apply(conn, mig.INDEX_STATEMENTS)
    assert _EXPECTED <= set(inspect(eng).get_table_names())


def test_migration_matches_runtime(mig):
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.app.services import catalog_entities as ce

    runtime = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=runtime, future=True)()
    ce.ensure_tables(s)
    s.commit()

    migrated = create_engine("sqlite://", future=True)
    with migrated.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)

    ri, mi = inspect(runtime), inspect(migrated)
    for t in _EXPECTED:
        assert {c["name"] for c in ri.get_columns(t)} == {c["name"] for c in mi.get_columns(t)}, f"{t} column drift"


def test_downgrade_drops(mig):
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
    with eng.begin() as conn:
        for t in mig._DROP_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {t}"))
    assert not (_EXPECTED & set(inspect(eng).get_table_names()))
