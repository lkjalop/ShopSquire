"""P0-1 money-path concurrency guards — deterministic regression tests for the CAS/idempotency
pattern propagated across the refund + inventory rails. These pin the invariants a true race would
exploit (double-credit, double-open, double-approve) without needing real thread interleaving:
each fix's correctness envelope is exercised via the read-check + atomic-claim path.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _db(tmp_path):
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path/'money.sqlite'}")
    return sessionmaker(bind=eng)()


# ── P0-1e: inventory release is idempotent (no double-credit) ──────────────────

def test_release_inventory_credits_stock_exactly_once(tmp_path):
    from src.app.services.inventory_guard import (reserve_inventory_for_order,
                                                  release_inventory_for_order)
    db = _db(tmp_path)
    db.execute(text("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT)"))
    db.execute(text("CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT, stock INT, "
                    "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    db.execute(text("INSERT INTO products (id, sku) VALUES ('p1','SKU-1')"))
    db.execute(text("INSERT INTO inventory (id, product_id, stock) VALUES ('i1','p1',10)"))
    db.commit()

    ok, _ = reserve_inventory_for_order(db, order_id="O1", line_items=[{"sku": "SKU-1", "quantity": 3}])
    db.commit()
    assert ok
    assert db.execute(text("SELECT stock FROM inventory WHERE id='i1'")).scalar() == 7

    # release TWICE — the second must be a no-op (the CAS claim already flipped the reservation)
    release_inventory_for_order(db, order_id="O1"); db.commit()
    release_inventory_for_order(db, order_id="O1"); db.commit()
    assert db.execute(text("SELECT stock FROM inventory WHERE id='i1'")).scalar() == 10  # not 13
    db.close()


# ── P0-1f: refund slot lock is single-winner ──────────────────────────────────

def test_reserve_refund_slot_single_winner(tmp_path):
    from src.app.services.payment_ledger import reserve_refund_slot
    db = _db(tmp_path)
    assert reserve_refund_slot(db, "refund:appr:O9:0") is True     # first wins
    db.commit()
    assert reserve_refund_slot(db, "refund:appr:O9:0") is False    # same slot → rejected
    db.commit()
    assert reserve_refund_slot(db, "refund:appr:O9:1") is True     # next index → fresh slot
    db.commit()
    assert reserve_refund_slot(db, "") is False                    # empty token never reserves
    db.close()


# ── refund_state exposes the counts the slot lock keys on ──────────────────────

def test_refund_state_exposes_request_and_approval_counts(tmp_path):
    from src.app.services import payment_ledger as L
    db = _db(tmp_path)
    L.ensure_table(db)
    L.record_txn(db, order_id="O2", kind=L.KIND_PAYMENT_SUCCEEDED, amount_cents=5000, commit=True)
    L.record_txn(db, order_id="O2", kind=L.KIND_REFUND_REQUESTED, amount_cents=2000, commit=True)
    st = L.refund_state(db, "O2")
    assert st["requests"] == 1 and st["approvals"] == 0 and st["open_request"] is True
    L.record_txn(db, order_id="O2", kind=L.KIND_REFUND_APPROVED, amount_cents=2000, commit=True)
    st = L.refund_state(db, "O2")
    assert st["requests"] == 1 and st["approvals"] == 1 and st["open_request"] is False
    db.close()
