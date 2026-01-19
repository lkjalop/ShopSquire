import time
from fastapi.testclient import TestClient
from src.app.main import app
client = TestClient(app)
start=time.time()
r=client.get('/api/v1/pricing/suggest', params={'uid':'normal','cart_total_cents':12000})
elapsed=time.time()-start
print('status', r.status_code)
try:
    print('json:', r.json())
except Exception as e:
    print('json error', e)
print('elapsed', elapsed)
