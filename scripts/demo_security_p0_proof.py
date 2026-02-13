from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from src.app.main import create_app


_received: List[Dict[str, Any]] = []


class _CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8", errors="ignore"))
        except Exception:
            payload = {"raw": raw.decode("utf-8", errors="ignore")}
        _received.append({"path": self.path, "payload": payload})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, format, *args):  # noqa: A003
        return


def run() -> Dict[str, Any]:
    server = HTTPServer(("127.0.0.1", 18088), _CaptureHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    os.environ["ELASTIC_SECURITY_EVENTS_URL"] = "http://127.0.0.1:18088/siem"
    os.environ["ELASTIC_API_KEY"] = ""

    app = create_app()
    client = TestClient(app)
    hdr_owner = {"x-api-key": "local-owner-key"}

    runbook = client.get("/api/v1/admin/email_security/demo/runbook", headers=hdr_owner).json()
    execute = client.post(
        "/api/v1/admin/email_security/demo/runbook/execute",
        headers=hdr_owner,
        json={"tenant_id": "demo-tenant", "scenarios": ["bec", "prompt_injection", "canary", "supplier_bank_change"]},
    ).json()

    funnel = client.get("/api/v1/admin/email_security/demo/funnel?tenant_id=demo-tenant", headers=hdr_owner).json()
    reliability = client.get("/api/v1/admin/email_security/connectors/reliability?hours=24", headers=hdr_owner).json()

    drilldowns = []
    for r in (execute.get("results") or []):
        did = r.get("decision_id") or r.get("trace_id")
        if not did:
            continue
        q = client.get(f"/api/v1/decisions/{did}/query?include_events=true", headers=hdr_owner)
        drilldowns.append({"id": did, "status": q.status_code, "body": q.json() if q.status_code == 200 else {}})

    server.shutdown()
    server.server_close()

    out = {
        "runbook": runbook,
        "execute": execute,
        "funnel": funnel,
        "reliability": reliability,
        "receiver_captured_events": _received,
        "drilldowns": drilldowns,
    }
    Path("dump").mkdir(parents=True, exist_ok=True)
    Path("dump/demo_security_p0_proof.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    result = run()
    print(json.dumps({"saved": "dump/demo_security_p0_proof.json", "results": len(result.get("execute", {}).get("results") or [])}))
