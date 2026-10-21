from uuid import uuid4
from sqlalchemy import text
from tests.legacy_endpoint_runtime import endpoint_runtime


def seed_order(engine):
    order_id = "status-" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO orders (id,total_cents,currency,status,created_at,updated_at) VALUES (:id,1000,'USD','created',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id":order_id})
    return order_id


def test_order_status_transitions_valid(endpoint_runtime):
    engine, client = endpoint_runtime
    order_id = seed_order(engine)
    r1 = client.post(f"/api/v1/orders/{order_id}/status", json={"status":"paid"})
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/orders/{order_id}/status", json={"status":"shipped"})
    assert r2.status_code == 200
    r3 = client.post(f"/api/v1/orders/{order_id}/status", json={"status":"delivered"})
    assert r3.status_code == 200


def test_order_status_transitions_invalid(endpoint_runtime):
    engine, client = endpoint_runtime
    order_id = seed_order(engine)
    r = client.post(f"/api/v1/orders/{order_id}/status", json={"status":"delivered"})
    assert r.status_code == 400
