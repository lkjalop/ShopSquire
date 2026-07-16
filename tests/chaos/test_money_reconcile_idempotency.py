"""P0-1 (test-anchored roadmap 2026-07-16): `reconcile_refund` must be idempotent under
at-least-once re-drive.

BUG (verified): `_handle_payment_outbox_job('reconcile_refund')` commits the `refund_settled`
ledger append (`_ledger_txn_for_intent`, commit=True) BEFORE running `settle_submitted_for_intent`
in a SEPARATE session. If settle throws, the job is marked failed and re-driven -> `refund_settled`
is appended a SECOND time -> `refund_state.settled_cents` double-counts. A doubled `captured_cents`
via the same mechanism is the direction that LOOSENS the refund cap.

DONE = this test goes from RED (settled_cents == 10000) to GREEN (== 5000) with append+settle made
atomic (one transaction), and the existing money suite stays green.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client_on(engine):
    import src.app.models.db as db_module
    original = db_module.engine
    db_module.set_engine(engine)
    from src.app.routers import payments, orders
    app = FastAPI()
    app.include_router(orders.router)
    app.include_router(payments.router)
    return TestClient(app, raise_server_exceptions=False), db_module, original


def test_reconcile_refund_idempotent_across_settle_failure(monkeypatch, tmp_path):
    import src.app.routers.payments as payments
    import src.app.services.refund_execution as refund_execution
    from src.app.services.payment_ledger import refund_state, record_txn, KIND_REFUND_APPROVED

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'reconcile.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    intent = "pi_reconcile"
    try:
        with db_module.db_session() as db:
            db.execute(text(
                "INSERT INTO orders (id,status,total_cents,currency,stripe_intent_id) "
                "VALUES ('ORD-RC','paid',5000,'USD','pi_reconcile')"))
            db.commit()
            record_txn(db, order_id="ORD-RC", kind=KIND_REFUND_APPROVED, intent_id=intent,
                       amount_cents=5000, commit=True)

        # settle throws on the FIRST attempt (job fails -> re-driven), no-ops on the second.
        calls = {"n": 0}

        def flaky_settle(db, *, intent_id, provider_ref=None, commit=True):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient settle failure")
            return 0  # the ledger `refund_settled` append is what we are testing, not the FSM

        monkeypatch.setattr(refund_execution, "settle_submitted_for_intent", flaky_settle)

        payload = {"intent_id": intent, "amount_cents": 5000, "provider_ref": "re_x"}
        with pytest.raises(RuntimeError):
            payments._handle_payment_outbox_job("reconcile_refund", payload)   # attempt 1: settle throws
        payments._handle_payment_outbox_job("reconcile_refund", payload)       # attempt 2: re-drive

        with db_module.db_session() as db:
            state = refund_state(db, "ORD-RC")
        assert state["settled_cents"] == 5000, (
            f"refund_settled double-counted across re-drive: settled_cents={state['settled_cents']} "
            "(expected 5000) — the append committed before settle and re-ran on retry.")
    finally:
        db_module.set_engine(original)


def test_reconcile_refund_idempotent_across_full_success_redrive(monkeypatch, tmp_path):
    """P0-1c: a reconcile_refund job that FULLY succeeded (append+settle committed) but whose
    completion-marking then failed is re-driven with the SAME provider_ref. The refund_settled
    append must be deduped on provider_ref — distinct partial refunds still append, but the same
    refund does not double-count. DONE = settled_cents == 5000 across two full deliveries."""
    import src.app.routers.payments as payments
    from src.app.services.payment_ledger import refund_state, record_txn, KIND_REFUND_APPROVED

    import src.app.services.refund_execution as refund_execution
    monkeypatch.setattr(refund_execution, "settle_submitted_for_intent",
                        lambda db, *, intent_id, provider_ref=None, commit=True: 0)  # FSM no-op; test the ledger

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'fullredrive.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    intent = "pi_fullredrive"
    try:
        with db_module.db_session() as db:
            db.execute(text(
                "INSERT INTO orders (id,status,total_cents,currency,stripe_intent_id) "
                "VALUES ('ORD-FR','paid',5000,'USD','pi_fullredrive')"))
            db.commit()
            record_txn(db, order_id="ORD-FR", kind=KIND_REFUND_APPROVED, intent_id=intent,
                       amount_cents=5000, commit=True)

        payload = {"intent_id": intent, "amount_cents": 5000, "provider_ref": "re_full1"}
        payments._handle_payment_outbox_job("reconcile_refund", payload)   # full success
        payments._handle_payment_outbox_job("reconcile_refund", payload)   # re-drive, same ref

        with db_module.db_session() as db:
            state = refund_state(db, "ORD-FR")
        assert state["settled_cents"] == 5000, (
            f"refund_settled double-counted on a full-success re-drive: "
            f"settled_cents={state['settled_cents']} (expected 5000).")
    finally:
        db_module.set_engine(original)


def test_payment_succeeded_ledger_append_is_idempotent_on_redrive(monkeypatch, tmp_path):
    """The money agent's BIGGEST risk: a `ledger_payment_succeeded` job re-driven after its
    completion-marking failed appends `payment_succeeded` a SECOND time -> captured_cents inflated,
    which LOOSENS the refund cap (refundable = captured - approved). The at-least-once ledger append
    must be idempotent per (intent, kind). DONE = captured_cents == 5000 across two deliveries."""
    import src.app.routers.payments as payments
    from src.app.services.payment_ledger import refund_state

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'succeeded.sqlite'}", future=True)
    client, db_module, original = _client_on(engine)
    intent = "pi_succeeded"
    try:
        with db_module.db_session() as db:
            db.execute(text(
                "INSERT INTO orders (id,status,total_cents,currency,stripe_intent_id) "
                "VALUES ('ORD-PS','paid',5000,'USD','pi_succeeded')"))
            db.commit()

        payload = {"intent_id": intent}
        payments._handle_payment_outbox_job("ledger_payment_succeeded", payload)   # first delivery
        payments._handle_payment_outbox_job("ledger_payment_succeeded", payload)   # re-drive (dup)

        with db_module.db_session() as db:
            state = refund_state(db, "ORD-PS")
        assert state["captured_cents"] == 5000, (
            f"payment_succeeded double-counted: captured_cents={state['captured_cents']} (expected "
            "5000) — a re-driven job appended it twice, inflating the refund cap.")
    finally:
        db_module.set_engine(original)
