"""C2 integration: the confirm-card apply endpoint + the chat short-circuit helper.

Proves the two seams the frontend depends on:
  • POST /api/v1/cart/mutations/{plan_id}/apply — applied, then already_applied on a
    double-submit (the SSE-abort/retry class NEVER mutates twice), 404 on unknown plan,
    403 masked as scope rules require.
  • chat._cart_mutation_short_circuit — forwards cart_mutation/cart/cart_updated (incl. the
    confirmation-card fields) verbatim and skips the product machinery.
"""
import json
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from tests.utils import default_headers


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
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DISABLE_UI_ROUTES", "1")
    eng = _make_engine()
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    try:
        _dbmod.set_engine(eng)
    except Exception:
        pass
    with eng.connect() as conn:
        pid = str(uuid.uuid4())
        conn.execute(text("INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                          "VALUES (:id, 'SKU-EP', 'Endpoint Test Unit', 9900, 1)"), {"id": pid})
        conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                          "VALUES (:id, :pid, 50, 'default')"), {"id": str(uuid.uuid4()), "pid": pid})
        conn.commit()
    from src.app.main import create_app
    app = create_app()
    app.state.engine = eng
    with TestClient(app, headers=default_headers(), raise_server_exceptions=False) as c:
        yield c
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


def _propose(uid):
    from src.app.domain.cart_mutation import CartMutationPlan, CartOp
    from src.app.routers.cart import CartItemPayload, add_item, _get_or_create_cart
    from src.app.security.auth import ROLE_OWNER
    from src.app.services.cart_mutation_service import propose_plan
    add_item(CartItemPayload(uid=uid, sku="SKU-EP", quantity=2), role=ROLE_OWNER)
    _, items, _ = _get_or_create_cart(uid)
    plan = CartMutationPlan(ops=(CartOp("set_quantity", ("SKU-EP",), 5),), confidence=0.9)
    return propose_plan(tenant_id="default", uid=uid, plan=plan, cart_items=items)


def test_apply_endpoint_idempotent_double_submit(client):
    uid = "ep-user-1"
    prop = _propose(uid)
    body = {"uid": uid}   # tenant comes from X-Tenant-Id header (default), not the body (#5)
    first = client.post(f"/api/v1/cart/mutations/{prop['plan_id']}/apply", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "applied"
    # the SSE-abort/retry class: an identical second submit MUST NOT mutate again
    second = client.post(f"/api/v1/cart/mutations/{prop['plan_id']}/apply", json=body)
    assert second.status_code == 200
    assert second.json()["status"] == "already_applied"
    cart = client.get("/api/v1/cart", params={"uid": uid}).json()
    line = next(it for it in cart["items"] if it["sku"] == "SKU-EP")
    assert int(line["quantity"]) == 5


def test_apply_unknown_plan_404(client):
    r = client.post("/api/v1/cart/mutations/cmp-nope/apply", json={"uid": "u"})
    assert r.status_code == 404


def test_apply_wrong_tenant_header_forbidden(client):
    # review-6 #5: a plan proposed under the default tenant cannot be applied by a request whose
    # X-Tenant-Id header names a different tenant — and the tenant can't be forced via the body.
    uid = "ep-user-tenant"
    prop = _propose(uid)   # proposed under tenant 'default'
    r = client.post(f"/api/v1/cart/mutations/{prop['plan_id']}/apply",
                    json={"uid": uid}, headers={"X-Tenant-Id": "other-tenant"})
    assert r.status_code == 403
    # the cart was not mutated
    cart = client.get("/api/v1/cart", params={"uid": uid}).json()
    assert next(it for it in cart["items"] if it["sku"] == "SKU-EP")["quantity"] == 2


def test_get_plan_scope_mismatch_reads_404(client):
    uid = "ep-user-2"
    prop = _propose(uid)
    ok = client.get(f"/api/v1/cart/mutations/{prop['plan_id']}", params={"uid": uid})
    assert ok.status_code == 200 and ok.json()["risk"] == "auto"
    other = client.get(f"/api/v1/cart/mutations/{prop['plan_id']}", params={"uid": "someone-else"})
    assert other.status_code == 404          # plan ids must not leak cart contents


# ── the chat short-circuit helper (extracted for exactly this test) ──────────────

def _suggest_cart_payload(**over):
    base = {
        "assistant_message": "Just to confirm — empty your whole cart?",
        "cart_mutation": {"applied": [], "rejected": [], "ambiguous": [],
                          "needs_clarification": False, "needs_confirmation": True,
                          "plan_id": "cmp-abc123", "risk": "confirm",
                          "ops": [{"action": "clear_all", "target_skus": []}],
                          "expires_at": "2099-01-01 00:00:00"},
        "cart_updated": False,
        "decision_trace_id": "tid-cc-1",
        "execution_mode": "v2_served",
        "execution_lane": "CART_MUTATE",
        "action_executed": False,
        "timing_breakdown": {
            "route_total_ms": 1200.0,
            "finalization_ms": 12.5,
        },
    }
    base.update(over)
    return base


def test_chat_short_circuit_forwards_confirmation_card():
    from src.app.routers.chat import _cart_mutation_short_circuit
    out = _cart_mutation_short_circuit(_suggest_cart_payload(), q="clear my cart", uid="u", db=None)
    assert out is not None
    assert out["turn_intent"] == "CART_MUTATE" and out["products"] == []
    cm = out["cart_mutation"]
    assert cm["needs_confirmation"] is True and cm["plan_id"] == "cmp-abc123"
    assert cm["ops"][0]["action"] == "clear_all"
    assert out["cart_updated"] is False
    assert out["trace_id"] == "tid-cc-1"
    assert out["timing_breakdown"] == {
        "route_total_ms": 1200.0,
        "finalization_ms": 12.5,
    }
    assert out["execution_mode"] == "v2_served"
    assert out["execution_lane"] == "CART_MUTATE"
    assert out["action_executed"] is False


def test_chat_short_circuit_forwards_explicit_budget_memory():
    from src.app.routers.chat import _cart_mutation_short_circuit
    out = _cart_mutation_short_circuit(
        _suggest_cart_payload(),
        q="Make it 50 and set the total budget to AUD 110,000.",
        uid="u",
        db=None,
    )

    assert out["confirmed_slots"]["budget_scope"] == "total"
    assert out["confirmed_slots"]["total_budget_cents"] == 11_000_000


def test_chat_short_circuit_forwards_applied_cart():
    from src.app.routers.chat import _cart_mutation_short_circuit
    out = _cart_mutation_short_circuit(
        _suggest_cart_payload(cart_mutation={"applied": [{"action": "set_quantity", "sku": "X", "quantity": 5}],
                                             "rejected": [], "ambiguous": [], "needs_clarification": False},
                              cart_updated=True, cart={"items": [{"sku": "X", "quantity": 5}]}),
        q="set x to 5", uid="u", db=None)
    assert out["cart_updated"] is True
    assert out["cart"]["items"][0]["quantity"] == 5


def test_chat_short_circuit_ignores_normal_search():
    from src.app.routers.chat import _cart_mutation_short_circuit
    assert _cart_mutation_short_circuit({"products": [{"sku": "A"}]}, q="laptops", uid="u", db=None) is None
    assert _cart_mutation_short_circuit(None, q="laptops", uid="u", db=None) is None
