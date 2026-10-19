import json
from sqlalchemy import text
from tests.legacy_endpoint_runtime import endpoint_runtime


def latest_event(engine,path):
    with engine.connect() as connection:
        row = connection.execute(text("SELECT details FROM security_events WHERE path=:path ORDER BY event_time DESC LIMIT 1"), {"path":path}).fetchone()
    return json.loads(row[0]) if row else None


def test_observer_logs_for_recommend(endpoint_runtime):
    engine, client = endpoint_runtime
    response = client.get("/api/v1/recommend/suggest",params={"uid":"u1","query":"laptop"})
    assert response.status_code == 200, response.text
    details = latest_event(engine,"/api/v1/recommend/suggest")
    assert details and details.get("payload")


def test_observer_logs_for_support(endpoint_runtime):
    engine, client = endpoint_runtime
    response = client.post("/api/v1/support/answer",params={"question":"need help"})
    assert response.status_code == 200, response.text
    details = latest_event(engine,"/api/v1/support/answer")
    assert details and details.get("payload")
