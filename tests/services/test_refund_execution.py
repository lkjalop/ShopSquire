"""Money-P0 M3 — refund execution states + idempotent retry (GPT-5.6 #6).

Proves a failed provider refund is RETRYABLE (was raise-and-forget; re-approve returned
no_open_refund_request), and that the retry reuses the same provider key (no double refund).
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services import refund_execution as RX


def _db(tmp_path):
    return sessionmaker(bind=create_engine(f"sqlite+pysqlite:///{tmp_path/'rx.sqlite'}"))()


def test_open_execution_is_unique_per_key(tmp_path):
    db = _db(tmp_path)
    a = RX.open_execution(db, order_id="O1", approval_index=0, amount_cents=5000, currency="USD",
                          intent_id="pi_1", idempotency_key="refund:O1:0")
    b = RX.open_execution(db, order_id="O1", approval_index=0, amount_cents=5000, currency="USD",
                          intent_id="pi_1", idempotency_key="refund:O1:0")   # same key → same row
    assert a == b
    assert db.execute(text("SELECT COUNT(*) FROM refund_executions")).scalar() == 1
    assert db.execute(text("SELECT state FROM refund_executions WHERE id=:i"), {"i": a}).scalar() == RX.STATE_PENDING
    db.close()


def test_failed_then_retried_settles_with_same_key(tmp_path):
    db = _db(tmp_path)
    RX.open_execution(db, order_id="O2", approval_index=0, amount_cents=3000, currency="USD",
                      intent_id="pi_2", idempotency_key="refund:O2:0")
    seen_keys = []

    def failing(intent, amount, key):
        seen_keys.append(key)
        raise RuntimeError("provider down")

    out = RX.execute_pending(db, refund_fn=failing)
    assert out["failed"] == 1 and out["settled"] == 0
    assert db.execute(text("SELECT state FROM refund_executions WHERE order_id='O2'")).scalar() == RX.STATE_FAILED

    def ok(intent, amount, key):
        seen_keys.append(key)
        return {"id": "re_123", "status": "succeeded"}

    out2 = RX.execute_pending(db, refund_fn=ok)     # retry the failed one
    assert out2["settled"] == 1
    row = db.execute(text("SELECT state, provider_ref FROM refund_executions WHERE order_id='O2'")).fetchone()
    assert row[0] == RX.STATE_SETTLED and row[1] == "re_123"
    assert seen_keys == ["refund:O2:0", "refund:O2:0"]     # SAME key on both attempts → no double refund
    db.close()


def test_settled_execution_is_not_retried(tmp_path):
    db = _db(tmp_path)
    eid = RX.open_execution(db, order_id="O3", approval_index=0, amount_cents=100, currency="USD",
                            intent_id="pi_3", idempotency_key="refund:O3:0")
    RX.mark_settled(db, eid, provider_ref="re_done")
    calls = {"n": 0}
    RX.execute_pending(db, refund_fn=lambda *a: (calls.__setitem__("n", calls["n"] + 1), {"id": "x"})[1])
    assert calls["n"] == 0   # settled → never re-issued
    db.close()


def test_demo_intent_is_not_executed(tmp_path):
    db = _db(tmp_path)
    RX.open_execution(db, order_id="O4", approval_index=0, amount_cents=100, currency="USD",
                      intent_id="pi_demo_abc", idempotency_key="refund:O4:0")
    out = RX.execute_pending(db, refund_fn=lambda *a: {"id": "x"})
    assert out["checked"] == 0   # demo intent excluded (no provider charge to refund)
    db.close()
