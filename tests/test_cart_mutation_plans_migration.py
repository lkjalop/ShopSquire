"""Validate 20260712_cart_mutation_plans (P0.4): creates cart_mutation_plans + indexes,
idempotent, drift-free vs the runtime _ensure_plans_table DDL, chains off the current head.
Also covers cleanup_plans retention."""
from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_MIG = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260712_cart_mutation_plans.py"


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig_cart_mutation_plans", _MIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_metadata(mig):
    assert mig.revision == "20260712_cart_mutation_plans"
    assert mig.down_revision == "20260711_taxonomy_grounding"   # chains off the current head


def test_upgrade_idempotent_creates_table_and_indexes(mig):
    eng = create_engine("sqlite://", future=True)
    for _ in range(2):  # idempotent
        with eng.begin() as conn:
            for s in mig.TABLE_STATEMENTS:
                conn.execute(text(s))
    insp = inspect(eng)
    assert "cart_mutation_plans" in insp.get_table_names()
    idx = {i["name"] for i in insp.get_indexes("cart_mutation_plans")}
    assert {"ix_cmp_owner_status", "ix_cmp_expires", "ix_cmp_trace"} <= idx


def test_migration_matches_runtime_ddl(mig):
    # runtime path
    runtime = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = runtime
    try:
        _dbmod.set_engine(runtime)
    except Exception:
        pass
    try:
        from src.app.services.cart_mutation_service import _ensure_plans_table
        _ensure_plans_table()
        # migration path
        migrated = create_engine("sqlite://", future=True)
        with migrated.begin() as conn:
            for s in mig.TABLE_STATEMENTS:
                conn.execute(text(s))
        ri, mi = inspect(runtime), inspect(migrated)
        assert ({c["name"] for c in ri.get_columns("cart_mutation_plans")}
                == {c["name"] for c in mi.get_columns("cart_mutation_plans")}), "column drift"
    finally:
        _dbmod.engine = orig
        try:
            _dbmod.set_engine(orig)
        except Exception:
            pass


def test_cleanup_plans_deletes_only_old_terminal(mig):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass
    try:
        from src.app.services import cart_mutation_service as S
        S._ensure_plans_table()
        from src.app.models.db import db_session
        with db_session() as db:
            # an OLD applied plan (delete), a FRESH applied plan (keep), an OLD proposed plan (keep — not terminal)
            for pid, status, applied_at in [
                ("old-applied", "applied", "2020-01-01 00:00:00"),
                ("new-applied", "applied", S._now().strftime(S._TS_FMT)),
                ("old-proposed", "proposed", "2020-01-01 00:00:00"),
            ]:
                db.execute(text(
                    "INSERT INTO cart_mutation_plans (id, tenant_id, uid, plan, risk, status, cart_hash, "
                    "cart_version, created_at, applied_at) VALUES (:id,'t','u','{}','auto',:st,'h',0,"
                    ":ca,:aa)"),
                    {"id": pid, "st": status, "ca": applied_at, "aa": applied_at})
            db.commit()
        deleted = S.cleanup_plans(older_than_days=7)
        assert deleted == 1
        assert S.get_plan("old-applied") is None
        assert S.get_plan("new-applied") is not None      # fresh terminal kept
        assert S.get_plan("old-proposed") is not None      # non-terminal kept
    finally:
        _dbmod.engine = orig
        try:
            _dbmod.set_engine(orig)
        except Exception:
            pass
