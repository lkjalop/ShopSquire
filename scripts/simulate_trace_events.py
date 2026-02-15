import os
import json
import time
import uuid
import requests

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8080")
API_KEY = os.environ.get("API_KEY", "local-merchant-key")

TRACE_ID = os.environ.get("TRACE_ID") or f"sim-{uuid.uuid4().hex}"

headers = {"Content-Type": "application/json", "x-api-key": API_KEY}

# Minimal parallel agent event burst for demo
batch = [
    {
        "trace_id": TRACE_ID,
        "event_type": "security_scan",
        "source_type": "agent",
        "source_id": "Email_Security_Agent",
        "payload": {"severity": "warning", "signals": ["bank_change_request", "confusable_homoglyph_domain"]},
    },
    {
        "trace_id": TRACE_ID,
        "event_type": "sender_trust_assessed",
        "source_type": "agent",
        "source_id": "Email_Trust_Graph_Agent",
        "payload": {"sender_trust_score": 0.32, "vendor_relationship_confidence": 0.28},
    },
    {
        "trace_id": TRACE_ID,
        "event_type": "ioc_enrichment_fusion",
        "source_type": "agent",
        "source_id": "IOC_Enrichment_Agent",
        "payload": {"malicious_hits": 0, "cache_hits": 1, "provider_weights": {"local_cache": 0.6}},
    },
    {
        "trace_id": TRACE_ID,
        "event_type": "policy_gate",
        "source_type": "agent",
        "source_id": "Email_Policy_Gate_Agent",
        "payload": {"decision": "review", "reason": "rule_first_gate"},
    },
]

resp = requests.post(f"{API_BASE}/api/v1/trace/events", data=json.dumps(batch), headers=headers)
print("status:", resp.status_code)
try:
    print(json.dumps(resp.json(), indent=2))
except Exception:
    print(resp.text)

print("Trace ID:", TRACE_ID)
print("Open stream:", f"{API_BASE}/api/v1/trace/{TRACE_ID}/events/stream")
