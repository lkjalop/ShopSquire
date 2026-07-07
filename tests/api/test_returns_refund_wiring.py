"""P1 wiring: a return claim now closes the loop to the GOVERNED refund rail.

- auto_approve + corroborated paid order  -> refund REQUEST opened on the payment ledger (human still approves)
- auto_approve without a purchase record  -> DOWNGRADED to require_human (no order, no auto-refund)
- one open request per order preserved through the extracted service
"""
from __future__ import annotations

import json
import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.utils import default_headers


def _mk_client(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/returns-wire.sqlite"
    from src.app.main import create_app
    app = create_app()
    return TestClient(app, headers=default_headers())


def _seed_purchase(uid: str, sku: str, total_cents: int = 199900, status: str = "paid") -> str:
    from src.app.models.db import db_session
    oid = f"ORD-{uuid.uuid4().hex[:8]}"
    did = f"D-{uuid.uuid4().hex[:8]}"
    with db_session() as db:
        db.execute(text("INSERT INTO products (sku, name, price_cents) VALUES (:s, :n, :p)"),
                   {"s": sku, "n": "Alpha X1 Laptop", "p": total_cents})
        db.execute(text("INSERT INTO draft_orders (id, customer_id, line_items, status) "
                        "VALUES (:d, :u, :li, 'committed')"),
                   {"d": did, "u": uid, "li": json.dumps([{"sku": sku, "quantity": 1}])})
        db.execute(text("INSERT INTO orders (id, draft_order_id, customer_id, total_cents, currency, status) "
                        "VALUES (:o, :d, :u, :t, 'USD', :st)"),
                   {"o": oid, "d": did, "u": uid, "t": total_cents, "st": status})
        db.commit()
    return oid


def _refund_requested_rows(order_id: str):
    from src.app.models.db import db_session
    with db_session() as db:
        try:
            return db.execute(text("SELECT amount_cents FROM payment_transactions "
                                   "WHERE order_id = :o AND kind = 'refund_requested'"),
                              {"o": order_id}).fetchall()
        except Exception:
            return []


def test_auto_approve_opens_governed_refund_request(tmp_path):
    client = _mk_client(tmp_path)
    uid, sku = "buyer-wire-1", "LAP-WIRE-1"
    oid = _seed_purchase(uid, sku)

    r = client.post("/api/v1/returns/submit", json={"sku": sku, "uid": uid, "description": "stopped working"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "auto_approve", body["score"]
    # the loop is CLOSED: a refund request now exists on the governed ledger (approval still human)
    assert body["refund"] and body["refund"]["ok"] is True, body.get("refund")
    assert body["refund"]["order_id"] == oid
    assert body["refund"]["approval_required"] is True
    rows = _refund_requested_rows(oid)
    assert len(rows) == 1 and int(rows[0][0]) == 199900   # full refundable (no claimed value in body)
    # corroboration recorded the canonical order (the old order_items-only path was silently dead)
    # second claim on the same order cannot double-open a request
    r2 = client.post("/api/v1/returns/submit", json={"sku": sku, "uid": uid, "description": "again"})
    assert r2.status_code == 200
    b2 = r2.json()
    assert b2["mode"] == "require_human"          # downgraded — refund_request_already_open
    assert len(_refund_requested_rows(oid)) == 1  # still exactly one


def test_no_purchase_record_downgrades_auto_approve(tmp_path):
    client = _mk_client(tmp_path)
    r = client.post("/api/v1/returns/submit",
                    json={"sku": "LAP-NOORDER", "uid": "buyer-no-order", "description": "want refund"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "require_human"        # base 10 + no_matching_order 15 = 25 < 30, but NO order -> no auto-refund
    assert body["refund"] is None
    sigs = [s.get("signal") for s in body["score"].get("signals", [])]
    assert "auto_approve_downgraded" in sigs


def test_clamp_amount_to_refundable(tmp_path):
    _mk_client(tmp_path)  # bootstraps schema on the tmp DB
    from src.app.models.db import db_session
    from src.app.services.refund_requests import create_refund_request
    uid, sku = "buyer-clamp", "LAP-CLAMP"
    oid = _seed_purchase(uid, sku, total_cents=50000)
    with db_session() as db:
        res = create_refund_request(db, order_id=oid, amount_cents=999999, reason="t",
                                    actor_type="agent", actor_id="test", clamp=True)
    assert res["ok"] is True and res["amount_cents"] == 50000
