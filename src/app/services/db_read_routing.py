from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine


_READ_ENGINE = None


def _get_read_engine():
    global _READ_ENGINE
    if _READ_ENGINE is not None:
        return _READ_ENGINE
    url = os.getenv("READ_REPLICA_URL")
    if not url:
        _READ_ENGINE = get_engine()
        return _READ_ENGINE
    try:
        _READ_ENGINE = create_engine(url, pool_pre_ping=True, future=True)
    except Exception:
        _READ_ENGINE = get_engine()
    return _READ_ENGINE


def replica_lag_seconds() -> float | None:
    eng = _get_read_engine()
    try:
        with eng.connect() as conn:
            # Postgres replay lag; returns NULL on primary.
            row = conn.execute(
                text("SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp()))")
            ).fetchone()
            if not row:
                return None
            val = row[0]
            if val is None:
                return 0.0
            return float(val)
    except Exception:
        return None


def choose_read_engine(read_class: str = "timeline"):
    if read_class in ("strong", "tx"):
        return get_engine()
    lag = replica_lag_seconds()
    max_lag = float(os.getenv("READ_REPLICA_MAX_LAG_SECONDS", "2.0"))
    if lag is not None and lag > max_lag:
        return get_engine()
    return _get_read_engine()


@contextmanager
def read_session(read_class: str = "timeline"):
    eng = choose_read_engine(read_class=read_class)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    s = SessionLocal()
    try:
        yield s
    finally:
        try:
            s.close()
        except Exception:
            pass
