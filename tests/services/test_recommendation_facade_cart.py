"""Facade cart-mutation serving (V2 cart milestone step 2) — the resolver detects + plans, the
guarded handlers execute, the facade shapes the payload. Flag-gated (RECOMMEND_CART_SERVE);
default off = the frontend regex serves, zero change."""
import json
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import src.app.services.recommendation_facade as F
from src.app.routers.cart import CartItemPayload, add_item
from src.app.security.auth import ROLE_OWNER
from src.app.services.recommendation_core.envelope import TurnEnvelope


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


def _seed(eng, rows):
    with eng.connect() as conn:
        for p in rows:
            pid = str(uuid.uuid4())
            conn.execute(text("INSERT OR IGNORE INTO products (id, sku, name, price_cents, active) "
                              "VALUES (:id, :sku, :name, :price, 1)"),
                         {"id": pid, "sku": p["sku"], "name": p["name"], "price": 10000})
            conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse) "
                              "VALUES (:id, :pid, :stock, 'default')"),
                         {"id": str(uuid.uuid4()), "pid": pid, "stock": int(p.get("stock", 100))})
        conn.commit()


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
    _seed(eng, [
        {"sku": "SKU-ENVY", "name": "HP Envy x360 14"},
        {"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13"},
        {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i"},
    ])
    yield eng
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


def _build_cart(uid):
    add_item(CartItemPayload(uid=uid, sku="SKU-ENVY", quantity=1), role=ROLE_OWNER)
    add_item(CartItemPayload(uid=uid, sku="SKU-TPAD", quantity=30), role=ROLE_OWNER)
    add_item(CartItemPayload(uid=uid, sku="SKU-IDEA", quantity=1), role=ROLE_OWNER)


def _env(uid, query, cart):
    return TurnEnvelope.from_suggest_params(query=query, uid=uid, tenant_id="t1", cart=cart)


def _fixed_llm(obj):
    return lambda _p, _t: json.dumps(obj)


_IDENTITY_TRACE = lambda payload, tid: payload   # noqa: E731


# ── the compound-edit screenshot, served end to end ──────────────────────────────

def test_serve_compound_edit(wired):
    uid = "u-facade-compound"
    _build_cart(uid)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1},
            {"sku": "SKU-TPAD", "name": "Lenovo ThinkPad L13", "quantity": 30},
            {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    llm = _fixed_llm({"ops": [
        {"action": "remove_items", "targets": ["HP Envy", "ThinkPad L13"]},
        {"action": "set_quantity", "targets": ["IdeaPad Slim 3i"], "quantity": 20},
    ], "confidence": 0.9})
    payload = F._serve_cart_mutation(_env(uid, "remove the envy and thinkpad, ideapad to 20", cart),
                                     role=ROLE_OWNER, with_trace=_IDENTITY_TRACE, llm_fn=llm)
    assert payload is not None
    assert payload["turn_intent"] == "CART_MUTATE"
    assert payload["cart_updated"] is True
    # cart actually mutated: only the IdeaPad remains, at qty 20
    remaining = {it["sku"]: it["quantity"] for it in payload["cart"]["items"]}
    assert remaining == {"SKU-IDEA": 20}
    assert not payload["cart_mutation"]["rejected"]
    assert "Done" in payload["assistant_message"]


# ── non-cart intent falls through ────────────────────────────────────────────────

def test_non_cart_intent_returns_none(wired):
    uid = "u-facade-search"
    _build_cart(uid)
    cart = [{"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(_env(uid, "show me cheaper laptops", cart),
                                     role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
                                     llm_fn=_fixed_llm({"ops": []}))
    assert payload is None   # empty plan → product routing


# ── ambiguity asks, never wipes ──────────────────────────────────────────────────

def test_ambiguous_target_asks_and_does_not_mutate(wired):
    uid = "u-facade-ambig"
    _build_cart(uid)
    cart = [{"sku": "SKU-ENVY", "name": "HP Envy x360 14", "quantity": 1},
            {"sku": "SKU-IDEA", "name": "Lenovo IdeaPad Slim 3i", "quantity": 1}]
    payload = F._serve_cart_mutation(
        _env(uid, "remove the dell", cart), role=ROLE_OWNER, with_trace=_IDENTITY_TRACE,
        llm_fn=_fixed_llm({"ops": [{"action": "remove_items", "targets": ["the Dell"]}]}))
    assert payload is not None
    assert payload["cart_updated"] is False
    assert payload["cart_mutation"]["needs_clarification"] is True
    assert "the Dell" in payload["cart_mutation"]["ambiguous"]
    # cart untouched — all three lines still present (never wiped on a guess)
    from src.app.routers.cart import _get_or_create_cart
    _, items, _ = _get_or_create_cart(uid)
    assert {it["sku"] for it in items} == {"SKU-ENVY", "SKU-TPAD", "SKU-IDEA"}


# ── the flag gate ────────────────────────────────────────────────────────────────

def test_cart_serving_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RECOMMEND_CART_SERVE", raising=False)
    assert F._cart_serving_enabled() is False


def test_cart_serving_flag_on(monkeypatch):
    monkeypatch.setenv("RECOMMEND_CART_SERVE", "1")
    assert F._cart_serving_enabled() is True
