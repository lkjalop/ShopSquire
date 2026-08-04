from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.routers.ui_storefront import _store_currency
from tests.utils import default_headers


def _seed_product():
    currency = _store_currency()
    with db_session() as db:
        db.execute(
            text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active, updated_at) "
                "VALUES ('p1', 'SKU-UI', 'UI Laptop', 129900, :currency, :specs, true, CURRENT_TIMESTAMP)"
            ),
            {
                "currency": currency,
                "specs": '{"graphics":"Intel Iris","wifi":"Wi-Fi 6","ports":["1 x HDMI","2 x USB-C"],"ram_gb":16,"storage":"512GB","cpu":"Intel Core i5","rating":4.4,"shipping_days":3}',
            },
        )
        db.execute(
            text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse, updated_at) VALUES ('inv1','p1', 4, 'default', CURRENT_TIMESTAMP)")
        )
        db.commit()


def _client() -> TestClient:
    return TestClient(create_app(), headers=default_headers())


def test_storefront_cards_include_specs():
    client = _client()
    _seed_product()
    r = client.get("/ui/storefront")
    assert r.status_code == 200
    html = r.text
    assert "GPU" in html or "Graphics" in html
    assert "Wi-Fi" in html
    assert "Ports" in html


def test_product_detail_shows_features():
    client = _client()
    _seed_product()
    r = client.get("/ui/product/SKU-UI")
    assert r.status_code == 200
    html = r.text
    assert "Intel Iris" in html
    assert "Wi-Fi 6" in html
    assert "Ports" in html


def test_forensics_console_route_exists():
    r = _client().get("/ui/forensics")
    assert r.status_code == 200
    assert "Forensics Console" in r.text
