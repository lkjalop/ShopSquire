"""An owned browser backend must not replace the parent pytest runtime."""
import sqlite3

import pytest

from tests.owned_security_runtime import _owned_runtime


def _browser_runtime(pytestconfig, tmp_path_factory, *, demo_checkout=False):
    directory = tmp_path_factory.mktemp("browser-backend") / "runtime"
    return _owned_runtime(
        pytestconfig,
        artifact_directory=directory,
        publish_base_url=False,
        env_overrides={
            "DISABLE_UI_ROUTES": "0",
            "DECISION_LOG_PREWARM_ON_START": "0",
            "ROUTER_PREWARM_ON_START": "0",
            "CV_PROVIDER": "basic",
            "AUTO_SEED_CATALOG_ON_START": "0",
            "AUTO_SEED_GAMING_CATALOG_ON_START": "0",
            "RATE_LIMIT_PER_IP_PER_MIN": "0",
            "PAYMENT_EXECUTION_ENABLED": "0",
            "ALLOW_DEMO_CHECKOUT": "1" if demo_checkout else "0",
        },
    )


@pytest.fixture(scope="module", autouse=True)
def browser_test_server(pytestconfig, tmp_path_factory):
    with _browser_runtime(pytestconfig, tmp_path_factory) as runtime:
        yield runtime


@pytest.fixture(scope="module")
def demo_checkout_server(pytestconfig, tmp_path_factory):
    with _browser_runtime(pytestconfig, tmp_path_factory, demo_checkout=True) as runtime:
        yield runtime


@pytest.fixture(autouse=True)
def seed_browser_catalog(browser_test_server):
    """Deterministic per-test catalog seed for storefront/detail/cart flows."""
    con = sqlite3.connect(browser_test_server["database_path"])
    cur = con.cursor()
    cur.execute("DELETE FROM inventory")
    cur.execute("DELETE FROM products")
    cur.execute(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)",
        (
            "e2e_p1",
            "E2E-001",
            "E2E Laptop 14",
            129900,
            "AUD",
            '{"cpu":"Intel Core i7","graphics":"Intel Iris Xe","ram_gb":16,"storage":"512GB","wifi":"Wi-Fi 6","ports":["USB-C","HDMI"]}',
        ),
    )
    cur.execute(
        "INSERT INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)",
        ("e2e_inv1", "e2e_p1", 6, "default"),
    )
    con.commit()
    con.close()
