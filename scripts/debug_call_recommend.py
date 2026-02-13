import os
import sys
from fastapi.testclient import TestClient
# Ensure repo root is importable
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from src.app.main import create_app
import json


def main():
    app = create_app()
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    uid = "test_guest_123"
    resp = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "laptop under $1000", "budget_max": 1000},
        headers=headers,
    )
    print("status:", resp.status_code)
    try:
        print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print("json error:", e)


if __name__ == "__main__":
    main()
