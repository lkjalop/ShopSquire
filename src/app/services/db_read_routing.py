from __future__ import annotations

import os
from contextlib import contextmanager
from threading import RLock

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import create_runtime_engine, get_engine


_READ_ENGINE = None
_READ_ENGINE_URL: str | None = None
_READ_ENGINE_GUARD = RLock()


def _get_read_engine():
    global _READ_ENGINE, _READ_ENGINE_URL
    url = os.getenv("READ_REPLICA_URL")
    with _READ_ENGINE_GUARD:
        if url and _READ_ENGINE is not None and _READ_ENGINE_URL == url:
            return _READ_ENGINE
        previous, previous_url = _READ_ENGINE, _READ_ENGINE_URL
        try:
            replacement = create_runtime_engine(url) if url else None
        except Exception:
            replacement = None
        # Only a successfully created replica is owned by this cache. The
        # current primary is borrowed from its request/application owner.
        _READ_ENGINE = replacement
        _READ_ENGINE_URL = url if replacement is not None else None
        if previous is not None and previous_url is not None and previous is not replacement:
            try:
                previous.dispose()
            except Exception:
                pass
        return replacement if replacement is not None else get_engine()


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
    if not os.getenv("READ_REPLICA_URL"):
        return _get_read_engine()
    lag = replica_lag_seconds()
    max_lag = float(os.getenv("READ_REPLICA_MAX_LAG_SECONDS", "2.0"))
    if lag is None or lag > max_lag:
        return get_engine()
    return _get_read_engine()


@contextmanager
def read_session(read_class: str = "timeline"):
    eng = choose_read_engine(read_class=read_class)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=eng, future=True)
    s = SessionLocal()
    try:
        from src.app.platform.tenant_session import bind_session_tenant
        bind_session_tenant(s)
        yield s
    finally:
        try:
            s.close()
        except Exception:
            pass
