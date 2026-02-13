"""Quick local test for webhook dispatcher.

Starts a dummy HTTP server to accept POSTs, enqueues a webhook, starts worker,
and waits for the delivery to be marked 'sent' in the DB.
"""
import http.server
import socketserver
import threading
import time
import uuid
import json
from sqlalchemy import text

from src.app.services.webhook_dispatcher import start_worker, enqueue_webhook
from src.app.models.db import get_engine


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('content-length') or 0)
        body = self.rfile.read(length) if length else b''
        try:
            print('Received POST:', body.decode('utf-8', errors='ignore'))
        except Exception:
            pass
        self.send_response(200)
        self.end_headers()


def run_server(port=9009):
    srv = socketserver.TCPServer(('127.0.0.1', port), Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv


def main():
    srv = run_server(9009)
    start_worker(poll_interval=0.1)
    eid = str(uuid.uuid4())
    url = 'http://127.0.0.1:9009/webhook'
    payload = {'test': 'ok', 'id': eid}
    eng = get_engine()
    # Ensure the table exists for the test (simple schema compatible with dispatcher)
    with eng.connect() as conn:
        conn.execute(text(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id TEXT PRIMARY KEY,
                url TEXT,
                payload TEXT,
                tenant_id TEXT,
                attempts INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                next_attempt_at REAL,
                status TEXT DEFAULT 'pending',
                last_error TEXT,
                key_id TEXT,
                secret_id TEXT,
                created_at REAL
            )
            """
        ))
    enqueue_webhook(eid, url, payload, max_attempts=3, tenant_id='test-tenant')
    # wait for processing up to 10s
    for i in range(40):
        with eng.connect() as conn:
            row = conn.execute(text("SELECT status FROM webhook_deliveries WHERE id = :id"), {'id': eid}).fetchone()
            if row and row[0] == 'sent':
                print('Delivery succeeded')
                srv.shutdown()
                return
        time.sleep(0.25)
    print('Timed out waiting for delivery; check logs')
    srv.shutdown()


if __name__ == '__main__':
    main()
