import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine, db_session, upsert, _build_upsert_sql


def test_upsert_sql_builder_postgres_contains_on_conflict():
    stmt, params = _build_upsert_sql(
        "postgresql",
        "sample",
        {"id": "x", "a": 1, "b": True},
        ["id"],
    )
    s = str(stmt)
    assert "ON CONFLICT (id)" in s
    assert "DO UPDATE SET" in s
    assert params["id"] == "x" and params["a"] == 1 and params["b"] is True


def test_upsert_sqlite_executes_and_replaces():
    eng = create_engine("sqlite://", future=True)
    set_engine(eng)
    # Ensure table exists
    with db_session() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS u_test (id TEXT PRIMARY KEY, v TEXT, active INTEGER)"
            )
        )
        db.commit()
    # Insert then replace
    with db_session() as db:
        upsert(db, "u_test", {"id": "A", "v": "one", "active": True}, ["id"])
        upsert(db, "u_test", {"id": "A", "v": "two", "active": False}, ["id"])
        row = db.execute(text("SELECT v, active FROM u_test WHERE id = 'A'"))
        r = row.fetchone()
        assert r is not None
        # active stored as integer in SQLite; our wrappers normalize when mapping rows
        assert r[0] == "two"
    # Engine restoration is handled globally by _restore_db_engine in conftest.py