"""R10.2 step 2 — cart identity is (tenant_id, customer_id). The cross-tenant isolation proofs:
the SAME uid under two tenants gets two DIFFERENT carts; reads/mutations under one tenant can
never see or touch the other's; the request ContextVar (X-Tenant-Id → middleware) and the
explicit tenant arg resolve identically; single-tenant callers (no header, no arg) keep exactly
today's behavior via 'default'."""
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.platform.tenant_context import (
    current_tenant_id,
    reset_active_tenant_id,
    set_active_tenant_id,
)
from src.app.routers.cart import _get_or_create_cart, _load_cart_row, _save_cart


def _make_engine():
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    schema_path = pathlib.Path("db/schema.sql")
    with eng.connect() as conn:
        for stmt in [s.strip() for s in schema_path.read_text(encoding="utf-8").split(";") if s.strip()]:
            try:
                conn.execute(text(stmt))
            except Exception:
                pass
        conn.commit()
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
    yield eng
    _dbmod.engine = orig
    try:
        _dbmod.set_engine(orig)
    except Exception:
        pass


def test_same_uid_two_tenants_two_carts(wired):
    uid = f"u-{uuid.uuid4().hex[:8]}"
    cart_t1, _, _ = _get_or_create_cart(uid, tenant_id="t1")
    cart_t2, _, _ = _get_or_create_cart(uid, tenant_id="t2")
    assert cart_t1 != cart_t2                                  # distinct carts per tenant
    # a write under t1 is INVISIBLE under t2
    _save_cart(cart_t1, [{"sku": "SKU-A", "quantity": 3}])
    _, items_t1, _ = _get_or_create_cart(uid, tenant_id="t1")
    _, items_t2, _ = _get_or_create_cart(uid, tenant_id="t2")
    assert items_t1 == [{"sku": "SKU-A", "quantity": 3}]
    assert items_t2 == []


def test_load_cart_row_scoped_by_tenant(wired):
    uid = f"u-{uuid.uuid4().hex[:8]}"
    cart_t1, _, _ = _get_or_create_cart(uid, tenant_id="t1")
    _save_cart(cart_t1, [{"sku": "SKU-B", "quantity": 1}])
    from src.app.models.db import db_session
    with db_session() as db:
        cid1, items1, _ = _load_cart_row(db, uid, tenant_id="t1")
        cid2, items2, _ = _load_cart_row(db, uid, tenant_id="t2")
    assert cid1 == cart_t1 and items1 and items1[0]["sku"] == "SKU-B"
    assert cid2 is None and items2 == []                       # t2 sees NO cart, not t1's


def test_contextvar_resolves_like_explicit_arg(wired):
    uid = f"u-{uuid.uuid4().hex[:8]}"
    token = set_active_tenant_id("t9")
    try:
        assert current_tenant_id() == "t9"
        cart_ctx, _, _ = _get_or_create_cart(uid)              # no arg → ContextVar
    finally:
        reset_active_tenant_id(token)
    cart_arg, _, _ = _get_or_create_cart(uid, tenant_id="t9")  # explicit arg
    assert cart_ctx == cart_arg                                # one identity, two entry forms
    assert current_tenant_id() == "default"                    # reset restored the default


def test_no_header_no_arg_is_default_tenant(wired):
    """Single-tenant deployments (no X-Tenant-Id anywhere) keep today's behavior exactly."""
    uid = f"u-{uuid.uuid4().hex[:8]}"
    cart_plain, _, _ = _get_or_create_cart(uid)
    cart_default, _, _ = _get_or_create_cart(uid, tenant_id="default")
    assert cart_plain == cart_default
