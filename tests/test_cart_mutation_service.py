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


@pytest.fixture(autouse=True)
def _tenant_ctx():
    """R10.2: plans here are proposed/applied as tenant 't1' — set the request ContextVar the
    way the middleware does so the handler-built carts live under the SAME tenant (pre-R10.2
    the mismatch was invisible because cart identity ignored tenant)."""
    from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
    tok = set_active_tenant_id("t1")
    yield
    reset_active_tenant_id(tok)


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
    replacement = CartMutationPlan(ops=(CartOp(
        "replace_item", ("A",), 2, replacement_sku="B", budget_max_cents=20000),))
    assert risk_tier(replacement) == RISK_CONFIRM
    sourcing_increase = CartMutationPlan(ops=(CartOp(
        "set_quantity", ("A",), 25, previous_quantity=10, allow_sourcing=True),))
    assert risk_tier(sourcing_increase) == RISK_CONFIRM


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


def test_set_quantity_preserves_whole_order_budget_at_apply_time(wired):
    uid = "u-budget-set"
    items = _cart(uid, ("SKU-A", 1), ("SKU-B", 1))
    plan = CartMutationPlan(ops=(CartOp(
        "set_quantity", ("SKU-A",), 2,
        budget_max_cents=20_000, unit_price_cents=10_000,
    ),), confidence=0.9)
    prop = S.propose_plan(
        tenant_id="t1", uid=uid, plan=plan, cart_items=items,
        query="add one A but keep the same $200 total budget",
    )

    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)

    assert out["status"] == "rejected"
    assert out["error"]["error"] == "total_budget_exceeded"
    assert out["error"]["proposed_total_cents"] == 30_000
    assert _skus(uid) == {"SKU-A": 1, "SKU-B": 1}


def test_replace_item_applies_atomically_and_respects_total_budget(wired):
    uid = "u-replace"
    items = _cart(uid, ("SKU-A", 4))
    plan = CartMutationPlan(ops=(CartOp(
        "replace_item", ("SKU-A",), 2,
        replacement_sku="SKU-B", budget_max_cents=20000),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items,
                          query="replace A with B and keep the total under $200")

    assert prop["risk"] == RISK_CONFIRM
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "applied"
    assert _skus(uid) == {"SKU-B": 2}
    assert out["applied"] == [{"action": "replace_item", "sku": "SKU-A",
                                "replacement_sku": "SKU-B", "quantity": 2}]


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


# ── P0.2: one-transaction versioned CAS (review-6 #2/#3/#4) ──────────────────────

def _cart_version(uid):
    from src.app.models.db import db_session
    from src.app.routers.cart import _load_cart_row
    with db_session() as db:
        _, _, v = _load_cart_row(db, uid)
    return v


def test_apply_bumps_cart_version(wired):
    uid = "u-ver"
    _cart(uid, ("SKU-A", 1))
    v0 = _cart_version(uid)
    plan = CartMutationPlan(ops=(CartOp("set_quantity", ("SKU-A",), 4),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=[])
    assert S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)["status"] == "applied"
    assert _cart_version(uid) == v0 + 1        # the versioned CAS incremented the token


def test_stepper_between_propose_and_apply_wins_no_lost_write(wired):
    # THE lost-write case (review-6 #3): a stepper edit lands after propose; apply must refuse
    # (stale), and the stepper's change must survive — never clobbered.
    uid = "u-race"
    _cart(uid, ("SKU-A", 1), ("SKU-B", 1))
    plan = CartMutationPlan(ops=(CartOp("remove_items", ("SKU-A",)),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=[])
    # stepper bumps SKU-B to 5 (a direct handler write → version++)
    from src.app.routers.cart import CartItemPayload, set_item_quantity
    set_item_quantity("SKU-B", CartItemPayload(uid=uid, sku="SKU-B", quantity=5), role=ROLE_OWNER)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "stale_cart"
    assert _skus(uid) == {"SKU-A": 1, "SKU-B": 5}     # A NOT removed, stepper's 5 survives


def test_midtransaction_raise_rolls_back_atomically(wired, monkeypatch):
    # review-6 #2: a raise mid-apply must roll back EVERYTHING — cart unchanged AND the plan
    # returns to 'proposed' (not wedged in 'applying'), so it stays retryable.
    uid = "u-rollback"
    _cart(uid, ("SKU-A", 2))
    plan = CartMutationPlan(ops=(CartOp("set_quantity", ("SKU-A",), 5),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=[])
    import src.app.routers.cart as _cartmod
    monkeypatch.setattr(_cartmod, "_save_cart_versioned",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "error"
    assert _skus(uid) == {"SKU-A": 2}                 # cart unchanged (rolled back)
    assert S.get_plan(prop["plan_id"])["status"] == "proposed"   # NOT wedged in 'applying'


def test_stale_does_not_stash_undo(wired):
    uid = "u-noundo"
    _cart(uid, ("SKU-A", 1))
    plan = CartMutationPlan(ops=(CartOp("clear_all"),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=[])
    from src.app.routers.cart import CartItemPayload, add_item
    add_item(CartItemPayload(uid=uid, sku="SKU-B", quantity=1), role=ROLE_OWNER)  # version++
    r = _Redis()
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid, redis=r)
    assert out["status"] == "stale_cart"
    from src.app.routers.cart import _undo_key
    assert _undo_key(uid) not in r.store              # nothing changed → no undo snapshot


# ── clear_previous: SERVER-authoritative carried set from per-line added_at (C2) ─

def test_clear_previous_removes_only_old_lines(wired):
    uid = "u-prev-server"
    _cart(uid, ("SKU-A", 1), ("SKU-B", 1))
    # backdate SKU-A's added_at beyond the carried threshold (1h) — an earlier session's line
    from datetime import datetime, timedelta
    from src.app.routers.cart import _get_or_create_cart, _save_cart
    cart_id, items, _ = _get_or_create_cart(uid)
    for it in items:
        if it["sku"] == "SKU-A":
            it["added_at"] = (datetime.utcnow() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    _save_cart(cart_id, items)
    _, items, _ = _get_or_create_cart(uid)
    plan = CartMutationPlan(ops=(CartOp("clear_previous"),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "applied"
    assert out["applied"][0] == {"action": "clear_previous", "skus": ["SKU-A"]}
    assert _skus(uid) == {"SKU-B": 1}          # this-session line kept


def test_clear_previous_without_stamps_rejects_not_wipes(wired):
    uid = "u-prev-nostamp"
    from src.app.routers.cart import _get_or_create_cart, _save_cart
    cart_id, _, _ = _get_or_create_cart(uid)
    _save_cart(cart_id, [{"sku": "SKU-A", "quantity": 1}, {"sku": "SKU-B", "quantity": 2}])
    _, items, _ = _get_or_create_cart(uid)
    plan = CartMutationPlan(ops=(CartOp("clear_previous"),), confidence=0.9)
    prop = S.propose_plan(tenant_id="t1", uid=uid, plan=plan, cart_items=items)
    out = S.apply_plan(prop["plan_id"], tenant_id="t1", uid=uid)
    assert out["status"] == "rejected" and out["error"]["error"] == "carried_set_unknown"
    assert _skus(uid) == {"SKU-A": 1, "SKU-B": 2}   # never guess-then-wipe
