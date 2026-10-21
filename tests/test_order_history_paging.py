from uuid import uuid4
from sqlalchemy import text
from tests.legacy_endpoint_runtime import endpoint_runtime


def test_order_history_paging(endpoint_runtime):
    engine, client = endpoint_runtime
    uid = "paging-" + uuid4().hex
    with engine.begin() as connection:
        for index in range(5):
            order_id = uid + str(index)
            connection.execute(text("INSERT INTO orders (id,total_cents,currency,status,created_at,updated_at) VALUES (:id,:total,'USD','created',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id":order_id,"total":10000+index*100})
            connection.execute(text("INSERT INTO order_sessions (id,uid,order_id,created_at) VALUES (:id,:uid,:order,CURRENT_TIMESTAMP)"), {"id":"session-"+order_id,"uid":uid,"order":order_id})
    r = client.get("/api/v1/orders/history", params={"uid":uid,"limit":2,"offset":0})
    assert r.status_code == 200
    data = r.json()
    assert len(data.get("orders",[])) == 2
    assert data.get("has_more") is True
    r2 = client.get("/api/v1/orders/history", params={"uid":uid,"limit":2,"offset":data.get("next_offset",2)})
    assert r2.status_code == 200
    data2 = r2.json()
    assert len(data2.get("orders",[])) == 2
