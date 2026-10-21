"""Explicit database ownership for requests, background work and nested services."""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.engine import Engine


_OWNER: ContextVar[Engine | None] = ContextVar('shopsquire_database_owner', default=None)
_REQUEST_OWNER_REQUIRED: ContextVar[bool] = ContextVar('shopsquire_request_database_required', default=False)


class RequestDatabaseUnavailable(RuntimeError):
    """An inbound request has no valid database owner; global fallback is denied."""


def current_database_engine() -> Engine | None:
    engine = _OWNER.get()
    if engine is None and _REQUEST_OWNER_REQUIRED.get():
        raise RequestDatabaseUnavailable('database_owner_unavailable')
    return engine


@contextmanager
def request_database_owner(engine):
    """Clear inherited owners and require the serving app's explicit engine.

    A request without an engine can still serve a response which never accesses
    the database. Its getters cannot silently read another application's data.
    """
    owner_token = _OWNER.set(engine if isinstance(engine, Engine) else None)
    required_token = _REQUEST_OWNER_REQUIRED.set(True)
    try:
        yield
    finally:
        _REQUEST_OWNER_REQUIRED.reset(required_token)
        _OWNER.reset(owner_token)


@contextmanager
def database_owner(engine: Engine):
    if not isinstance(engine, Engine):
        raise TypeError('An explicit SQLAlchemy database owner is required')
    token = _OWNER.set(engine)
    try:
        yield
    finally:
        _OWNER.reset(token)
