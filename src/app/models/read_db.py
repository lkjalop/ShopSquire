"""Explicit, lazily-created read-only database boundary.

Callers must opt into this dependency. Transactional routes continue to import
``get_db`` from ``src.app.models.db`` and therefore can never be redirected to
an asynchronous replica by deployment configuration alone.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Generator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.app.models.db import create_runtime_engine


_lock = threading.Lock()
_engine: Engine | None = None
_url: str | None = None


def _configured_read_url() -> str:
    return str(os.getenv("DATABASE_READ_URL") or os.getenv("DATABASE_URL") or "").strip()


def get_read_engine() -> Engine:
    """Return the explicitly configured analytics/read engine.

    PostgreSQL connections are placed in read-only mode at checkout. Absence of
    ``DATABASE_READ_URL`` deliberately uses the primary URL, still read-only,
    so development and non-replica production profiles keep the same contract.
    """

    global _engine, _url
    url = _configured_read_url()
    if not url:
        raise RuntimeError("DATABASE_READ_URL_or_DATABASE_URL_required")
    if _engine is not None and _url == url:
        return _engine
    with _lock:
        if _engine is not None and _url == url:
            return _engine
        engine = create_runtime_engine(url)
        if engine.dialect.name == "postgresql":

            @event.listens_for(engine, "checkout")
            def _enforce_read_only(dbapi_connection, _record, _proxy) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("SET default_transaction_read_only = on")
                finally:
                    cursor.close()

        _engine = engine
        _url = url
        return engine


def get_read_db() -> Generator[Session, None, None]:
    """FastAPI dependency for endpoints classified as replica-safe."""

    factory = sessionmaker(bind=get_read_engine(), autoflush=False, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def reset_read_engine_for_tests() -> None:
    global _engine, _url
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _url = None
