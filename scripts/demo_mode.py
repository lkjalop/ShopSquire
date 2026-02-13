#!/usr/bin/env python3
"""
ShopSquire Demo Mode: seeds a live email security incident via public API, 
verifies admin incidents and tickets, and opens the admin UI for recording.

Proof artifacts:
- Prints request IDs returned by middleware (x-request-id)
- Appends to runs/request_log.txt server-side
- Writes runs/demo_proof.json with incident + ticket ids and timestamps

Usage:
  python scripts/demo_mode.py --api http://127.0.0.1:8081 --open-ui
  python scripts/demo_mode.py --api http://127.0.0.1:8081 --autostart --open-ui

Notes:
- Requires the API running with DISABLE_UI_ROUTES=0
- Uses x-api-key: local-developer-key
"""
import argparse
import json
import os
import time
import webbrowser
from typing import Any, Dict, Optional

import requests

DEFAULT_API = os.environ.get("DEMO_API", "http://127.0.0.1:8081")
HEADERS = {"x-api-key": os.environ.get("DEMO_API_KEY", "local-developer-key")}


def wait_ready(api: str, timeout: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            r = requests.get(f"{api}/readyz", timeout=2)
            if r.ok and (r.json() or {}).get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def start_server(api_port: int = 8081) -> None:
    # Best-effort: start uvicorn in a detached process
    # Environment mirrors typical local demo settings
    env = os.environ.copy()
    env.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{os.getcwd()}/tmp/e2e.sqlite")
    env.setdefault("DISABLE_UI_ROUTES", "0")
    env.setdefault("API_PORT", str(api_port))
    env.setdefault("BACKPRESSURE_TEST_DELAY_SEC", "0.2")
    # Spawn uvicorn
    import subprocess, sys

    cmd = [sys.executable, "-m", "uvicorn", "src.app.main:create_app", "--host", "127.0.0.1", "--port", str(api_port), "--factory"]
    subprocess.Popen(cmd, env=env, cwd=os.getcwd())


def post_email_evaluate(api: str, tenant_id: str = "t1") -> Dict[str, Any]:
    payload = {
        "tenant_id": tenant_id,
        "message_id": "<demo-abc@xyz>",
        "from_addr": "CEO <ceo@microsoft.com>",
        "reply_to": "finance@micros0ft.com",
        "subject": "Urgent wire transfer",
        "body": "Please pay invoice at https://micros0ft-payments.com immediately.",
        "attachments": [{"name": "invoice.html"}],
        "dmarc_fail": False,
    }
    r = requests.post(f"{api}/api/v1/email_security/evaluate", headers=HEADERS, json=payload, timeout=8)
    r.raise_for_status()
    rid = r.headers.get("x-request-id")
    body = r.json()
    return {"request_id": rid, "verdict": body}


def list_incidents(api: str, severity: Optional[str] = None, has_ticket: Optional[bool] = None, limit: int = 20) -> Dict[str, Any]:
    params = {"limit": str(limit)}
    if severity:
        params["severity"] = severity
    if has_ticket is not None:
        params["has_ticket"] = "true" if has_ticket else "false"
    r = requests.get(f"{api}/api/v1/admin/email_security/incidents", headers=HEADERS, params=params, timeout=8)
    r.raise_for_status()
    rid = r.headers.get("x-request-id")
    body = r.json()
    return {"request_id": rid, "data": body}


def write_proof(proof: Dict[str, Any]) -> str:
    try:
        os.makedirs("runs", exist_ok=True)
    except Exception:
        pass
    path = os.path.join("runs", "demo_proof.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": int(time.time()), **proof}, f, indent=2)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API, help="API base URL")
    ap.add_argument("--tenant", default="t1", help="Tenant ID to use")
    ap.add_argument("--autostart", action="store_true", help="Start server if not ready")
    ap.add_argument("--open-ui", action="store_true", help="Open admin UI in browser")
    args = ap.parse_args()

    api = args.api.rstrip("/")
    print(f"[demo] using API: {api}")

    ready = wait_ready(api, timeout=6.0)
    if not ready and args.autostart:
        print("[demo] server not ready; starting uvicorn...")
        start_server(api_port=int(api.split(":")[-1]))
        ready = wait_ready(api, timeout=12.0)
    if not ready:
        print("[demo] server not ready; please start API and re-run.")
        return 2

    print("[demo] posting email_security/evaluate...")
    verdict = post_email_evaluate(api, tenant_id=args.tenant)
    print(f"[demo] evaluate: req_id={verdict['request_id']} severity={verdict['verdict'].get('severity')} playbook={(verdict['verdict'].get('playbook') or {}).get('id')}")

    print("[demo] fetching incidents with has_ticket=true (server-side filter)...")
    inc = list_incidents(api, severity=None, has_ticket=True, limit=10)
    rows = (inc.get("data") or {}).get("incidents") or []
    print(f"[demo] incidents: req_id={inc['request_id']} count={len(rows)}")
    for i, row in enumerate(rows[:3]):
        pb = ((row.get("playbook") or {}).get("id") or "-")
        print(f"  [{i}] id={row.get('id')} sev={row.get('severity')} ticket={row.get('ticket',{}).get('id')} pb={pb}")

    proof_path = write_proof({"evaluate": verdict, "incidents": inc})
    print(f"[demo] wrote proof file: {proof_path}")

    if args.open_ui:
        url = f"{api}/admin"
        print(f"[demo] opening admin UI: {url}")
        try:
            webbrowser.open(url)
        except Exception:
            print("[demo] please open the URL manually in your browser.")

    print("\nTips to record proof:\n- Keep DevTools Network open while running this script.\n- Show runs/request_log.txt updating in real time.\n- Open an incident and click the ticket deep link.\n- Export CSV from Email Incidents to capture the new row.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
