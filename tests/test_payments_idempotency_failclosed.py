"""Payments idempotency must fail CLOSED (B2).

If the idempotency check cannot be verified (DB error), the money path must reject the request as a
possible duplicate (caller -> 409, no charge) instead of failing open and risking a double charge.
"""
from __future__ import annotations

from src.app.routers import payments


def test_no_key_allows():
    # No idempotency key -> caller did not request idempotency -> proceed.
    assert payments._idempotent("payment_intent", None) is True


def test_db_error_fails_closed(monkeypatch):
    class _BoomDB:
        def execute(self, *a, **k):
            raise RuntimeError("db down")
        def commit(self):
            pass
        def rollback(self):
            pass

    class _BoomSession:
        def __enter__(self):
            return _BoomDB()
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(payments, "db_session", lambda: _BoomSession())
    # Cannot verify -> must reject (False), not allow (True).
    assert payments._idempotent("payment_intent", "key-123") is False
