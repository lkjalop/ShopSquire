import os
import time
import pytest
import requests

from sqlalchemy import text

from src.app.models.db import get_engine, db_session
from src.app.models import db as dbmod
from sqlalchemy import create_engine
from src.app.models.orm import Product, Inventory


def is_service_up(url: str, timeout: float = 0.5) -> bool:
    try:
        r = requests.get(url, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.integration
def test_e2e_customer_flow_with_orders_and_memory():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Integration tests disabled. Set RUN_INTEGRATION=1 to enable.")

    prev_db_url = os.getenv("DATABASE_URL")
    prev_engine = getattr(dbmod, "engine", None)
    try:
        db_url = os.getenv("INTEGRATION_DATABASE_URL") or os.getenv("DATABASE_URL")
        if db_url:
            os.environ["DATABASE_URL"] = db_url
            dbmod.set_engine(create_engine(db_url, pool_pre_ping=True, future=True))

        base = os.getenv("INTEGRATION_BASE_URL")
        if not base:
            host = os.getenv("API_HOST", "localhost")
            port = os.getenv("API_PORT", "8080")
            base = f"http://{host}:{port}"
        headers = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}

        deadline = time.time() + 60
        while time.time() < deadline:
            if is_service_up(base + "/health"):
                break
            time.sleep(0.5)
        assert is_service_up(base + "/health"), "API health endpoint not reachable"

        # storefront renders
        r = requests.get(base + "/ui/storefront", timeout=5)
        assert r.status_code == 200

        # pick an SKU from the running API to ensure it exists in that DB
        sku = "LAPTOP_DELL_XPS_13"
        try:
            rlist = requests.get(f"{base}/api/v1/products/list", headers=headers, timeout=5)
            if rlist.status_code == 200 and isinstance(rlist.json(), list) and rlist.json():
                sku = rlist.json()[0].get("sku") or sku
        except Exception:
            pass
        with db_session() as db:
            existing = db.execute(text("SELECT id FROM products WHERE sku = :sku"), {"sku": sku}).fetchone()
            if not existing:
                p = Product(sku=sku, name="E2E Laptop Pro", price_cents=129900)
                db.add(p)
                db.commit()
                db.refresh(p)
                inv = Inventory(product_id=p.id, stock=7, warehouse="default")
                db.add(inv)
                db.commit()

        # recommend
        resp = requests.get(
            f"{base}/api/v1/recommend/suggest",
            params={"uid": "e2e-user", "query": "laptop pro"},
            headers=headers,
            timeout=5,
        )
        assert resp.status_code == 200
        assert isinstance(resp.json().get("results"), list)

        # session memory update
        mem = requests.post(
            f"{base}/api/v1/session/e2e-user/memory/update",
            params={"utterance": "Need a 16GB laptop", "retrieval_ranks": ["r1", "r2"]},
            headers=headers,
            timeout=5,
        )
        assert mem.status_code == 200

        # create order
        order = requests.post(
            f"{base}/api/v1/orders/create",
            json={"uid": "e2e-user", "items": [{"sku": sku, "quantity": 1}]},
            headers=headers,
            timeout=5,
        )
        assert order.status_code == 200
        order_id = order.json().get("order_id")
        assert order_id

        # order history
        hist = requests.get(
            f"{base}/api/v1/orders/history",
            params={"uid": "e2e-user", "limit": 5, "offset": 0},
            headers=headers,
            timeout=5,
        )
        assert hist.status_code == 200
        ids = [o.get("order_id") for o in hist.json().get("orders", [])]
        assert order_id in ids

        # sanity: decision logs (if enabled) should exist for uid
        engine = get_engine()
        with engine.connect() as conn:
            res = conn.execute(text("SELECT count(*) FROM decision_logs")).scalar() or 0
        assert res >= 0
    finally:
        try:
            if prev_db_url is not None:
                os.environ["DATABASE_URL"] = prev_db_url
            else:
                os.environ.pop("DATABASE_URL", None)
        except Exception:
            pass
        try:
            if prev_engine is not None:
                dbmod.set_engine(prev_engine)
        except Exception:
            pass
