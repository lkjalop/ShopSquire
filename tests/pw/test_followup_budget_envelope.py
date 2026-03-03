import pytest
import time
import os
import sqlite3
import json


def _request_with_retry(method, url, attempts=3, timeout=20, **kwargs):
    requests = pytest.importorskip("requests")
    last_exc = None
    for idx in range(attempts):
        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except requests.exceptions.ReadTimeout as exc:
            last_exc = exc
            if idx < attempts - 1:
                time.sleep(0.4 * (idx + 1))
                continue
            raise
    if last_exc:
        raise last_exc


def _budget_pair(payload: dict) -> tuple[int | None, int | None]:
    c = (payload or {}).get("constraints_used") or {}
    try:
        bmin = c.get("budget_min")
        bmax = c.get("budget_max")
        return (int(bmin) if bmin is not None else None, int(bmax) if bmax is not None else None)
    except Exception:
        return (None, None)


def _seed_budget_range_products() -> None:
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url.startswith("sqlite:///"):
        return
    db_path = db_url.replace("sqlite:///", "", 1)
    if not db_path:
        return
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    specs_a = {
        "ram_gb": 16,
        "storage": "1TB",
        "cpu": "Ryzen 7",
        "display": "14\" FHD",
        "graphics": "RTX 4060",
        "wifi": "Wi-Fi 6E",
        "os": "Windows 11",
    }
    specs_b = {
        "ram_gb": 32,
        "storage": "1TB",
        "cpu": "Intel Core i7",
        "display": "15.6\" QHD",
        "graphics": "RTX 4070",
        "wifi": "Wi-Fi 6E",
        "os": "Windows 11",
    }
    cur.execute(
        "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)",
        ("pw1", "PWGAMING1600", "Portable Gaming Laptop 14", 160000, "USD", json.dumps(specs_a)),
    )
    cur.execute(
        "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, specs, active) VALUES (?,?,?,?,?,?,1)",
        ("pw2", "PWGAMING1850", "Gaming Creator Laptop 15", 185000, "USD", json.dumps(specs_b)),
    )
    cur.execute(
        "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)",
        ("pwinv1", "pw1", 7, "default"),
    )
    cur.execute(
        "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES (?,?,?,?)",
        ("pwinv2", "pw2", 6, "default"),
    )
    con.commit()
    con.close()


def test_exact_followup_keeps_budget_and_result_envelope(test_server):
    """
    Reproduces the real multi-turn regression:
    1) budgeted recommendation request
    2) follow-up detailed/why prompt

    The second turn must preserve the first turn's budget envelope and should
    not expand candidate scope beyond the first turn.
    """
    base = test_server["base_url"]
    headers = {"x-api-key": "local-merchant-key"}
    uid = "pw-followup-envelope-user"
    _seed_budget_range_products()

    q1 = "show me computers that is portable but good for gaming as well between 1500 to 1900"
    q2 = "can i get a detailed list? also tell me why this laptops?"

    r1 = _request_with_retry(
        "GET",
        base + "/api/v1/recommend/suggest",
        params={"uid": uid, "query": q1},
        headers=headers,
    )
    assert r1.status_code == 200
    p1 = r1.json()
    n1 = len(p1.get("results") or [])
    b1 = _budget_pair(p1)
    assert b1 == (1500, 1900), p1.get("constraints_used")

    r2 = _request_with_retry(
        "GET",
        base + "/api/v1/recommend/suggest",
        params={"uid": uid, "query": q2},
        headers=headers,
    )
    assert r2.status_code == 200
    p2 = r2.json()
    n2 = len(p2.get("results") or [])
    b2 = _budget_pair(p2)

    # Core regression checks
    assert b2 == b1, {"first": p1.get("constraints_used"), "second": p2.get("constraints_used")}
    assert n2 <= n1, {"first_count": n1, "second_count": n2}
