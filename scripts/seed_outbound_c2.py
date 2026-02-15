import argparse
import json
import os
import time
from typing import Dict, Any

import requests


def post_json(url: str, payload: Dict[str, Any], api_key: str | None = None, tenant_id: str | None = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if tenant_id:
        headers["X-Tenant-Id"] = tenant_id
    r = requests.post(url, data=json.dumps(payload), headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_json(url: str, api_key: str | None = None) -> Dict[str, Any]:
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


def simulate_beacon(api: str, tenant: str, api_key: str | None):
    url = api.rstrip("/") + "/api/v1/admin/email_security/outbound/simulate"
    base = {
        "tenant_id": tenant,
        "agent_id": "agent-demo",
        "subject": "aW52b2ljZS1wYXktcG9GUEFQRFZTS0xER0hKTDEyMzQ1Njc4OTAyYWJjZGVm",  # longer base64-like subject to raise entropy
        "body": "heartbeat",
        "interval_sec": 0.3,
        "minutes": 2,
    }
    # Vary destination domains and thread IDs to trigger drift/coherence in addition to entropy.
    variations = [
        {"to": "c2@attacker.invalid", "thread_id": "th-1", "count": 4},
        {"to": "ops@alt1.invalid", "thread_id": "th-2", "count": 3},
        {"to": "ops@alt2.invalid", "thread_id": "th-3", "count": 3},
    ]

    for v in variations:
        payload = {**base, **v}
        _ = post_json(url, payload, api_key=api_key, tenant_id=tenant)

    # Final analysis on recent window, expecting multiple reasons.
    out = post_json(url, {**base, "to": "c2@attacker.invalid", "thread_id": "th-4", "count": 1}, api_key=api_key, tenant_id=tenant)
    print(f"[ok] outbound simulate: anomaly_id={out.get('anomaly_id')} score={(out.get('analysis') or {}).get('score')} reasons={(out.get('analysis') or {}).get('reasons')}")

    # Fetch anomalies list to show Email XDR outbound tab is populated
    lst = get_json(api.rstrip("/") + "/api/v1/admin/email_security/outbound/anomalies", api_key=api_key)
    print(f"[ok] outbound anomalies count={lst.get('count')} latest_id={(lst.get('items') or [{}])[0].get('id') if lst.get('items') else None}")


def main():
    p = argparse.ArgumentParser(description="Seed outbound email C2/beacon anomalies for Email XDR")
    p.add_argument("--api", default=os.getenv("API_URL", "http://127.0.0.1:8081"))
    p.add_argument("--tenant", default=os.getenv("TENANT_ID", "t-demo"))
    p.add_argument("--api-key", default=os.getenv("API_KEY", "local-owner-key"))
    args = p.parse_args()
    simulate_beacon(args.api, args.tenant, args.api_key)


if __name__ == "__main__":
    main()
