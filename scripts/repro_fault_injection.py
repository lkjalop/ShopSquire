import os
import random
import time
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from src.app.main import create_app

os.environ.setdefault("DATABASE_URL", "sqlite:///test.sqlite")
os.environ.setdefault("DISABLE_TRACING", "1")
os.environ["SKIP_OBSERVER_ENDPOINTS"] = "/api/v1/recommend,/api/v1/admin"

app = create_app()
# Propagate server exceptions so we see tracebacks
client = TestClient(app, raise_server_exceptions=True)
HEADERS = {
    "x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key"),
    "x-skip-observer": "1",
}

for i in range(10000):
    method, path, params = random.choice([
        ("GET", "/api/v1/admin/overview", {}),
        ("GET", "/api/v1/recommend/suggest", {"query": "laptop"}),
        ("GET", "/api/v1/admin/security/metrics", {}),
    ])
    if random.random() < 0.1 and "query" in params:
        params = {"query": "'" * 50}
    r = client.request(method, path, params=params, headers=HEADERS)
    if r.status_code == 500:
        print("Got 500 at iteration", i)
        print(r.text)
        break
    if i % 1000 == 0:
        print("iter", i)
print("done")
