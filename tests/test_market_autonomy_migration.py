"""Validate the 20260626_market_autonomy migration: its DDL creates the expected tables, is
idempotent (safe to re-apply over runtime-created tables), and downgrades cleanly.

The full `alembic upgrade head` can't run on SQLite (earlier revisions need pgvector/Postgres), so we
apply THIS migration's statement lists directly to a fresh SQLite engine — the statements are the
same CREATE ... IF NOT EXISTS DDL the services emit, so this proves prod-parity without a DB.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

_MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260626_market_autonomy_tables.py"

_EXPECTED_TABLES = {
    "market_signal", "market_finding", "human_feedback", "shadow_action",
    "contact_consent", "contact_event", "contact_audit", "experiment_ops_heartbeat",
    "experiment_run", "experiment_assignment", "experiment_result",
}


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig_market_autonomy", _MIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(conn, statements):
    for stmt in statements:
        conn.execute(text(stmt))


def test_migration_metadata(mig):
    assert mig.revision == "20260626_market_autonomy"
    assert mig.down_revision == "20260625_attribution"  # chains off the single existing head
    assert len(mig.TABLE_STATEMENTS) == 11


def test_upgrade_creates_all_tables_and_is_idempotent(mig):
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)
    present = set(inspect(eng).get_table_names())
    assert _EXPECTED_TABLES <= present, f"missing: {_EXPECTED_TABLES - present}"
    # re-apply: IF NOT EXISTS makes the migration safe over already-runtime-created tables
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)
    assert _EXPECTED_TABLES <= set(inspect(eng).get_table_names())


def test_indexes_created(mig):
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)
    insp = inspect(eng)
    sig_idx = {i["name"] for i in insp.get_indexes("market_signal")}
    assert "ix_market_signal_dedup" in sig_idx
    # the dedup index is the per-tenant uniqueness guard
    assert next(i for i in insp.get_indexes("market_signal") if i["name"] == "ix_market_signal_dedup")["unique"]


def test_downgrade_drops_tables(mig):
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
    with eng.begin() as conn:
        for tbl in mig._DROP_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
    remaining = _EXPECTED_TABLES & set(inspect(eng).get_table_names())
    assert remaining == set(), f"downgrade left tables behind: {remaining}"


def _runtime_engine():
    """Build a SQLite db by calling every service ensure_* (the runtime path)."""
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    from src.app.services import contact_governance, experiments, human_feedback, market_signal, shadow_actions
    from src.app.services.experiment_ops import _ensure_heartbeat
    from src.app.services.market_analysis import ensure_finding_table
    market_signal.ensure_table(s)
    ensure_finding_table(s)
    human_feedback.ensure_table(s)
    shadow_actions.ensure_table(s)
    contact_governance.ensure_tables(s)
    _ensure_heartbeat(s)
    experiments.ensure_tables(s)
    s.commit()
    return eng


def _migration_engine(mig):
    eng = create_engine("sqlite://", future=True)
    with eng.begin() as conn:
        _apply(conn, mig.TABLE_STATEMENTS)
        _apply(conn, mig.INDEX_STATEMENTS)
    return eng


def _schema(eng):
    """{table: ({columns}, {(index_name, unique)})} for the adaptive-growth tables."""
    insp = inspect(eng)
    out = {}
    for t in _EXPECTED_TABLES:
        if not insp.has_table(t):
            continue
        cols = {c["name"] for c in insp.get_columns(t)}
        idx = {(i["name"], bool(i["unique"])) for i in insp.get_indexes(t)}
        out[t] = (cols, idx)
    return out


def test_migration_ddl_matches_runtime_tables(mig):
    """The migration must create EXACTLY what the services create at runtime — same tables, COLUMNS,
    and INDEXES (incl. uniqueness). Comparing only table names would miss a column/index drift such as
    the per-event index-drop the runtime no longer does."""
    runtime = _schema(_runtime_engine())
    migrated = _schema(_migration_engine(mig))
    assert set(runtime) == set(migrated) == _EXPECTED_TABLES
    for t in _EXPECTED_TABLES:
        r_cols, r_idx = runtime[t]
        m_cols, m_idx = migrated[t]
        assert r_cols == m_cols, f"{t}: column drift runtime={r_cols} migration={m_cols}"
        assert r_idx == m_idx, f"{t}: index drift runtime={r_idx} migration={m_idx}"
