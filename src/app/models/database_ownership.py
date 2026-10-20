"""Explicit database ownership for background work and its nested services."""
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy.engine import Engine


_OWNER: ContextVar[Engine | None] = ContextVar('shopsquire_database_owner', default=None)


def current_database_engine() -> Engine | None:
    return _OWNER.get()


@contextmanager
def database_owner(engine: Engine):
    if not isinstance(engine, Engine):
        raise TypeError('An explicit SQLAlchemy database owner is required')
    token = _OWNER.set(engine)
    try:
        yield
    finally:
        _OWNER.reset(token)
