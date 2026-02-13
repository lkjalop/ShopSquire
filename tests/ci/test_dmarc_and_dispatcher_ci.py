import os
import time
import tempfile
from pathlib import Path

import requests
from fastapi.testclient import TestClient


SAMPLE_DMARC = b"""
<feedback>
  <report_metadata>
    <org_name>CI</org_name>
    <email>postmaster@ci.example</email>
    <report_id>CI-1</report_id>
    <date_range>
      <begin>1736200000</begin>
      <end>1736286400</end>
    </date_range>
  </report_metadata>
  <policy_published>
    <domain>ci.example</domain>
    <adkim>r</adkim>
    <aspf>r</aspf>
    <p>none</p>
  </policy_published>
  <record>
    <row>
      <source_ip>203.0.113.5</source_ip>
      <count>2</count>
    </row>
    <policy_evaluated>
      <disposition>none</disposition>
      <dkim>fail</dkim>
      <spf>fail</spf>
    </policy_evaluated>
  </record>
</feedback>
"""


def _with_temp_db(func):
    def _inner():
        tmp = Path(os.getcwd()) / "tmp"
        tmp.mkdir(exist_ok=True)
        dbpath = tmp / f"ci_{int(time.time()*1000)}.sqlite"
        path_str = str(dbpath).replace('\\', '/')
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///" + path_str
        return func()

    return _inner


@_with_temp_db
def test_dmarc_ingest_and_summary():
    from src.app.main import create_app

    app = create_app()
    client = TestClient(app)
    files = {"file": ("r.xml", SAMPLE_DMARC, "application/xml")}
    r = client.post("/api/v1/security/dmarc/ingest", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body.get("reports", 0) >= 1

    r2 = client.get("/api/v1/admin/dmarc/summary")
    assert r2.status_code == 200
    s = r2.json()
    assert "summary" in s


@_with_temp_db
def test_dispatcher_enqueue_and_send():
    from src.app.main import create_app
    from src.app.services.webhook_dispatcher import enqueue_webhook
    from src.app.models.db import get_engine

    app = create_app()
    client = TestClient(app)

    # Start a small HTTP server to receive the webhook
    import http.server, socketserver, threading

    received = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            received["body"] = body.decode("utf-8", errors="ignore")
            self.send_response(200)
            self.end_headers()

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()

    eng = get_engine()
    # ensure table
    from sqlalchemy import text
    with eng.begin() as conn:
      conn.execute(
        text(
          """
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
          id TEXT PRIMARY KEY,
          url TEXT,
          payload TEXT,
          tenant_id TEXT,
          attempts INTEGER DEFAULT 0,
          max_attempts INTEGER DEFAULT 3,
          next_attempt_at TEXT,
          status TEXT DEFAULT 'pending',
          last_error TEXT,
          key_id TEXT,
          secret_id TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
      )

    # Start dispatcher worker for the test (faster polling)
    from src.app.services.webhook_dispatcher import start_worker, stop_worker
    start_worker(poll_interval=0.05)

    wid = f"ci-{int(time.time()*1000)}"
    enqueue_webhook(wid, f"http://127.0.0.1:{port}/webhook", {"ok": True}, max_attempts=3, tenant_id="ci")

    # Wait up to 5s for delivery
    from sqlalchemy import text
    for _ in range(40):
      with eng.connect() as conn:
        row = conn.execute(text("SELECT status FROM webhook_deliveries WHERE id = :id"), {"id": wid}).fetchone()
        if row and row[0] == "sent":
          break
      time.sleep(0.125)

    srv.shutdown()
    try:
      stop_worker()
    except Exception:
      pass
    assert received.get("body") is not None
