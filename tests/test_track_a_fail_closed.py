"""Track A (2026-07-13) — the fail-CLOSED behaviours that replaced the verified fail-OPEN bugs.
These lock in that a DB/infra error on a security/money decision now fails SAFE, not silently clean."""
import pytest


def test_record_txn_raises_on_write_failure():
    """A2: the payment ledger is the refund-fold source of truth — a lost write must RAISE (fail
    closed), not return None. So the refund-approval path can't proceed un-recorded."""
    from src.app.services.payment_ledger import record_txn

    class _BoomDB:
        def execute(self, *a, **k):
            raise RuntimeError("ledger table unreachable")
        def commit(self):
            pass
    with pytest.raises(Exception):
        record_txn(_BoomDB(), order_id="o1", kind="refund_approved", amount_cents=1000, commit=True)


def test_forced_reauth_fails_closed_on_db_error(monkeypatch):
    """A1: if the forced-reauth flag table can't be read, require reauth (return True) rather than
    silently letting a possibly-flagged user through."""
    import src.app.routers.auth as auth

    class _BoomCtx:
        def __enter__(self):
            raise RuntimeError("db down")
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(auth, "db_session", lambda *a, **k: _BoomCtx())
    assert auth._is_forced_reauth(user_id="u1") is True             # fail CLOSED
    assert auth._is_forced_reauth(email="a@b.com") is True


def test_is_https_fails_secure_on_error():
    """A5: if scheme can't be determined, assume https so the Secure cookie flag is kept."""
    import src.app.routers.auth as auth

    class _BadReq:
        @property
        def headers(self):
            raise RuntimeError("no headers")
    assert auth._is_https_request(_BadReq()) is True                # fail SECURE


def test_fraud_score_flags_degraded_on_check_failure(monkeypatch):
    """A3/A4: when a DB-backed fraud check can't run, the response carries degraded=True + a
    signal (routes to review) with reduced confidence — never a silent pristine score."""
    import src.app.routers.fraud as fraud

    class _BoomCtx:
        def __enter__(self):
            raise RuntimeError("fraud tables down")
        def __exit__(self, *a):
            return False
    monkeypatch.setattr(fraud, "db_session", lambda *a, **k: _BoomCtx())
    out = fraud.score({"image_phash": "abc123", "customer_id": "c1"}, role="owner")
    assert out["degraded"] is True
    assert out["confidence"] <= 0.4
    assert any("unavailable" in s.get("signal", "") for s in out["top_signals"]
               if isinstance(s, dict))
