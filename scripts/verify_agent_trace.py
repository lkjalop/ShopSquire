import os
import requests
import json

BASE = os.getenv('API_BASE', 'http://127.0.0.1:8080')
HEADERS = {'x-api-key': os.getenv('MERCHANT_API_KEY', 'local-merchant-key'), 'Content-Type': 'application/json'}

print('POST /api/v1/orchestrate')
body = {
    'uid': 'trace-test-1',
    'cart_total_cents': 15000,
    'sku': 'sku-verify-1',
    'tenant_id': 't1',
    'actor_id': 'actor-verify',
    'actor_role': 'merchant',
}
resp = requests.post(f"{BASE}/api/v1/orchestrate", headers=HEADERS, data=json.dumps(body), timeout=10)
print('status', resp.status_code)
try:
    data = resp.json()
    print(json.dumps(data, indent=2))
except Exception:
    print(resp.text)

proposal_id = None
if resp.status_code == 200:
    proposal = data.get('proposal') if isinstance(data, dict) else None
    if isinstance(proposal, dict):
        proposal_id = proposal.get('proposal_id')

if not proposal_id:
    print('No proposal_id found; exiting')
    raise SystemExit(1)

print('\nGET /api/v1/trace/{proposal_id}/events')
trace_resp = requests.get(f"{BASE}/api/v1/trace/{proposal_id}/events", headers=HEADERS, timeout=10)
print('status', trace_resp.status_code)
try:
    print(json.dumps(trace_resp.json(), indent=2))
except Exception:
    print(trace_resp.text)
