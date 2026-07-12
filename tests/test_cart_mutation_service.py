"""C1 transactional cart-mutation service: propose → authorize (risk tier) → apply.

The proofs review-5 demanded: ALL-OR-NOTHING (a compound plan whose second op fails leaves the
first op un-applied), idempotent apply (double-submit returns the stored result, mutates once),
stale-cart CAS (a plan never applies to a cart that changed since proposal), tenant/uid scoping
on the plan artifact, and the undo stash on destructive applies."""
import json
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import src.app.services.cart_mutation_service as S
from src.app.domain.cart_mutation import (
    RISK_AUTO,
    RISK_CONFIRM,
    CartMutationPlan,
    CartOp,
    cart_content_hash,
    risk_tier,
)
from src.app.routers.cart import CartItemPayload, add_item, _get_or_create_cart
from src.app.security.auth import ROLE_OWNER


def _make_engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    schema_path = pathlib.Path("db/schema.sql")
    if schema_path.exists():
        with eng.connect() as conn:
            for stmt in [s.strip() for s in schema_path.read_text(encoding="utf-8").split(";") if s.strip()]:
                try:
                    conn.execute(text(stmt))
                except Exception:
                    pass
            conn.commit()
    else:
        import src.app.models.db as _dbmod
        _dbmod._ensure_minimal_sqlite_tables(eng)
    return eng


@pytest.fixture()
def wired():
    eng = _make_engine()
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass
    with eng.connect() as conn:
        for sku, name, stock in [("SKU-A", "Acme Alpha Unit", 100), ("SKU-B", "Bravo Unit", 100),
                                 ("SKU-C", "Charlie Unit", 100)]:
            pid = str(uuid.uuid4())
            conn.execute(text("INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                              "VALUES (:id, :sku, :name, 10000, 1)"),
                         {"id": pid, "sku": sku, "name": name})
            conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                              "VALUES (:id, :pid, :stock, 'default')"),
                         {"id": str(uuid.uuid4()), "pid": pid, "stock": stock})
        conn.commit()
    yield eng
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


def _cart(uid, *skus_qty):
    for sku, qty in skus_qty:
        add_item(CartItemPayload(uid=uid, sku=sku, quantity=qty), role=ROLE_OWNER)
    _, items, _ = _get_or_create_cart(uid)
    return items


def _skus(uid):
    _, items, _ = _get_or_create_cart(uid)
    return {it["sku"]: it["quantity"] for it in items}


# ── domain: risk tiers + content hash ────────────────────────────────────────────

def test_risk_tiers():
    one_remove = CartMutationPlan(ops=(CartOp("remove_items", ("A",)),))
    one_set = CartMutationPlan(ops=(CartOp("set_quantity", ("A",), 5),))
    assert risk_tier(one_remove) == RISK_AUTO and risk_tier(one_set) == RISK_AUTO
    assert risk_tier(CartMutationPlan(ops=(CartOp("clear_all"),))) == RISK_CONFIRM
    assert risk_tier(CartMutationPlan(ops=(CartOp("keep_only", ("A",)),))) == RISK_CONFIRM
    assert risk_tier(CartMutationPlan(ops=(CartOp("remove_items", ("A", "B")),))) == RISK_CONFIRM
    compound = CartMutationPlan(ops=(CartOp("remove_items", ("A",)), CartOp("set_quantity", ("B",), 2)))
    assert risk_tier(compound) == RISK_CONFIRM


def test_cart_content_hash_tracks_content():
    a = [{"sku": "X", "quantity": 1}, {"sku": "Y", "quantity": 2}]
    b = [{"sku": "Y", "quantity": 2}, {"sku": "X", "quantity": 1}]   # order-insensitive
    assert cart_content_hash(a) == cart_content_hash(b)
    assert cart_content_hash(a) != cart_content_hash([{"sku": "X", "quantity": 3},
                                                      {"sku": "Y", "quantity": 2}])


# ── propose / apply happy path ───────────────────────────────────────────────────

def test_propose_then_apply_single_set(wired):
    uid = "u-happy"
    items = _cart(uid, ("SKU-A", 1), ("SKU-B", 1))
    plan = CartMutationPlan(ops=(CartOp("set_quantity", ("SKU-A",), 7),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items, query="set A to 7")
    assert prop["risk"] == RISK_AUTO
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "applied"
    assert _skus(uid) == {"SKU-A": 7, "SKU-B": 1}
    assert S.get_plan(prop["plan_id"])["status"] == "applied"


def test_apply_is_idempotent(wired):
    uid = "u-idem"
    items = _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("set_quantity", ("SKU-A",), 3),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    first = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    second = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert first["status"] == "applied"
    assert second["status"] == "already_applied"     # double-submit (SSE retry class) = no-op
    assert second["applied"] == first["applied"]
    assert _skus(uid) == {"SKU-A": 3}


# ── the atomicity proof (review-5 #5) ────────────────────────────────────────────

def test_all_or_nothing_compound_failure_applies_nothing(wired):
    uid = "u-atomic"
    items = _cart(uid, ("SKU-A", 1), ("SKU-B", 1))
    # remove A would succeed; set B to 600 fails the line gate → the WHOLE plan must abort
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A",)),
                                 CartOp("set_quantity", ("SKU-B",), 600)), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "rejected"
    assert out["error"]["error"] == "quantity_out_of_range"
    assert _skus(uid) == {"SKU-A": 1, "SKU-B": 1}    # A NOT removed — nothing applied


def test_remove_of_absent_sku_rejects_whole_plan(wired):
    uid = "u-absent"
    items = _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A", "SKU-NOPE")),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "rejected" and out["error"]["error"] == "target_not_in_cart"
    assert _skus(uid) == {"SKU-A": 1}


# ── stale-cart CAS (review-5 #5 concurrency) ─────────────────────────────────────

def test_stale_cart_refused(wired):
    uid = "u-stale"
    items = _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A",)),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    # the cart changes AFTER the proposal (stepper / another tab)
    add_item(CartItemPayload(uid=uid, sku="SKU-B", quantity=1), role=ROLE_OWNER)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "stale_cart"
    assert _skus(uid) == {"SKU-A": 1, "SKU-B": 1}    # untouched
    assert S.get_plan(prop["plan_id"])["status"] == "stale_cart"


# ── scoping + expiry (review-5 #4) ───────────────────────────────────────────────

def test_tenant_or_uid_mismatch_forbidden(wired):
    uid = "u-scope"
    items = _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A",)),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    assert S.apply_plan(prop["plan_id"], tenant_id="t2", uid=uid)["status"] == "forbidden"
    assert S.apply_plan(prop["plan_id"], tenant_id="t1", uid="someone-else")["status"] == "forbidden"
    assert _skus(uid) == {"SKU-A": 1}


def test_expired_plan_refused(wired):
    uid = "u-expired"
    items = _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A",)),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    from src.app.models.db import db_session
    with db_session() as db:
        db.execute(text("UPDATE cart_mutation_plans SET expires_at = '2020-01-01 00:00:00' "
                        "WHERE id = :id"), {"id": prop["plan_id"]})
        db.commit()
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "expired"
    assert _skus(uid) == {"SKU-A": 1}


# ── undo stash on destructive apply (review-5 gap #3) ────────────────────────────

class _Redis:
    def __init__(self): self.store = {}
    def setex(self, k, ttl, v): self.store[k] = v


def test_clear_all_stashes_undo(wired):
    uid = "u-undo"
    items = _cart(uid, ("SKU-A", 2), ("SKU-B", 1))
    plan = CartMutationPlan(ops=(CartOp("clear_all"),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    r = _Redis()
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid, redis=r)
    assert out["status"] == "applied"
    assert _skus(uid) == {}
    from src.app.routers.cart import _undo_key
    snap = json.loads(r.store[_undo_key(uid)])
    assert {(i["sku"], i["quantity"]) for i in snap["items"]} == {("SKU-A", 2), ("SKU-B", 1)}


def test_unknown_plan_not_found(wired):
    assert S.apply_plan("cmp-nope", tenant_id="t1", uid="u")["status"] == "not_found"
