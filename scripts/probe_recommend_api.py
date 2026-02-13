import os, sys, json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from fastapi.testclient import TestClient
from src.app.main import create_app

app = create_app()
client = TestClient(app)

cases = [
    {"name": "price <= $1500", "params": {"uid": "probe", "query": "show me laptops under $1500", "budget_max": 150000}},
    {"name": "spec 1TB", "params": {"uid": "probe", "query": "show me laptops with 1TB"}},
]

for c in cases:
    r = client.get("/api/v1/recommend/suggest", params=c["params"])
    print("\n===", c["name"], "status:", r.status_code)
    try:
        data = r.json()
    except Exception as e:
        print("error parsing json:", e)
        print(r.text)
        continue
    if isinstance(data, dict):
        products = data.get("products") or []
        print("count:", len(products))
        print("skus:", [p.get("sku") for p in products])
        print("agent_chain:", data.get("agent_chain"))
    else:
        print("unexpected body:", data)
