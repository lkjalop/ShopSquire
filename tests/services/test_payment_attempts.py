"""Money-P0 M1 — durable payment_attempts + orphan reconciliation (GPT-5.6 #3).

Proves the association-integrity outbox: an intent whose order-association write was LOST (the
orphan-charge failure) is recoverable from the attempt row.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services import payment_attempts as PA


def _db(tmp_path):
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path/'attempts.sqlite'}")
    db = sessionmaker(bind=eng)()
    db.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, stripe_intent_id TEXT, "
                    "updated_at TEXT)"))
    # the payment ledger table the reconciler writes into
    from src.app.services.payment_ledger import ensure_table as _ensure_ledger
    _ensure_ledger(db)
    db.commit()
    return db


def test_open_attempt_records_reserved_before_provider(tmp_path):
    db = _db(tmp_path)
    aid = PA.open_attempt(db, order_id="O1", provider="stripe", amount_cents=5000,
                          currency="USD", idempotency_key="K1")
    row = db.execute(text("SELECT order_id, state, provider_ref FROM payment_attempts WHERE id=:i"),
                     {"i": aid}).fetchone()
    assert row[0] == "O1" and row[1] == PA.STATE_RESERVED and row[2] is None
    db.close()


def test_state_transitions(tmp_path):
    db = _db(tmp_path)
    aid = PA.open_attempt(db, order_id="O2", provider="stripe", amount_cents=100, idempotency_key="K2")
    PA.mark_provider_created(db, aid, provider_ref="pi_abc", order_id="O2")
    assert db.execute(text("SELECT state, provider_ref FROM payment_attempts WHERE id=:i"),
                      {"i": aid}).fetchone() == (PA.STATE_PROVIDER_CREATED, "pi_abc")
    PA.mark_associated(db, aid)
    assert db.execute(text("SELECT state FROM payment_attempts WHERE id=:i"), {"i": aid}).scalar() == PA.STATE_ASSOCIATED
    db.close()


def test_reconcile_repairs_orphan_association(tmp_path):
    # THE orphan case: Stripe made the intent (attempt=provider_created with order_id+ref) but the
    # order-association write was lost — the order has no stripe_intent_id. Reconcile must re-apply it.
    db = _db(tmp_path)
    db.execute(text("INSERT INTO orders (id, stripe_intent_id) VALUES ('O3', NULL)"))
    aid = PA.open_attempt(db, order_id="O3", provider="stripe", amount_cents=7000, idempotency_key="K3")
    PA.mark_provider_created(db, aid, provider_ref="pi_orphan", order_id="O3")
    db.commit()

    out = PA.reconcile_orphans(db)
    assert out["repaired"] == 1
    # order now linked, attempt associated, a ledger intent_created row exists
    assert db.execute(text("SELECT stripe_intent_id FROM orders WHERE id='O3'")).scalar() == "pi_orphan"
    assert db.execute(text("SELECT state FROM payment_attempts WHERE id=:i"), {"i": aid}).scalar() == PA.STATE_ASSOCIATED
    n = db.execute(text("SELECT COUNT(*) FROM payment_transactions WHERE order_id='O3' AND intent_id='pi_orphan'")).scalar()
    assert n == 1

    # idempotent: a second reconcile repairs nothing (already associated / already linked)
    out2 = PA.reconcile_orphans(db)
    assert out2["repaired"] == 0
    assert db.execute(text("SELECT COUNT(*) FROM payment_transactions WHERE order_id='O3'")).scalar() == 1
    db.close()


def test_reconcile_skips_already_linked_orders(tmp_path):
    # an attempt whose order already carries the intent must not double-write the ledger.
    db = _db(tmp_path)
    db.execute(text("INSERT INTO orders (id, stripe_intent_id) VALUES ('O4', 'pi_done')"))
    aid = PA.open_attempt(db, order_id="O4", provider="stripe", amount_cents=100, idempotency_key="K4")
    PA.mark_provider_created(db, aid, provider_ref="pi_done", order_id="O4")
    db.commit()
    out = PA.reconcile_orphans(db)
    assert out["repaired"] == 0   # order already linked → no new ledger row
    assert db.execute(text("SELECT COUNT(*) FROM payment_transactions WHERE order_id='O4'")).scalar() == 0
    db.close()
