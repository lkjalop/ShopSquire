from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from src.app.models.db import db_session, get_engine


def _is_postgres() -> bool:
    try:
        eng = get_engine()
        return str(getattr(getattr(eng, "dialect", None), "name", "")).lower() == "postgresql"
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_postgres() or str(os.getenv("ENABLE_DB_MATRIX", "0")).strip().lower() not in ("1", "true", "yes", "on"),
    reason="Postgres/Timescale matrix requires postgres engine + ENABLE_DB_MATRIX=1",
)


def test_postgres_source_of_truth_connectivity():
    with db_session() as db:
        one = db.execute(text("SELECT 1")).scalar()
        assert int(one or 0) == 1


def test_timescale_extension_and_time_bucket_or_skip():
    with db_session() as db:
        has_ext = bool(
            db.execute(text("SELECT 1 FROM pg_catalog.pg_extension WHERE extname='timescaledb'")).fetchone()
        )
        if not has_ext:
            pytest.skip("timescaledb_extension_not_installed")
        row = db.execute(text("SELECT time_bucket('1 day', now())")).fetchone()
        assert row is not None

