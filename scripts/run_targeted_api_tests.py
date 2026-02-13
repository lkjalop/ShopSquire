from fastapi.testclient import TestClient
from src.app.main import create_app
import json

app = create_app()
client = TestClient(app)
headers = {"x-api-key": "local-merchant-key"}

def pretty(r):
    try:
        return json.dumps(r.json(), indent=2)
    except Exception:
        return r.text

print("GET /api/v1/inventory/alerts")
r = client.get("/api/v1/inventory/alerts", headers=headers)
print(r.status_code)
print(pretty(r))

print('\nPOST /api/v1/orchestrate')
body = {
    "uid": "test-1",
    "cart_total_cents": 10000,
    "sku": "sku-123",
    "tenant_id": "t1",
    "actor_id": "actor-1",
    "actor_role": "merchant",
}
r = client.post("/api/v1/orchestrate", json=body, headers=headers)
print(r.status_code)
print(pretty(r))

print('\nPOST /api/v1/cv/analyze')
body = {
    "labels": ["cracked", "screen"],
    "extracted_text": "SN: ABC12345",
    "description": "test",
    "issue_type": "damage",
}
r = client.post("/api/v1/cv/analyze", json=body, headers=headers)
print(r.status_code)
print(pretty(r))
