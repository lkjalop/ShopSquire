"""Owned HTTP fault controls for warm-up accounting, not model accuracy."""
import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI

from src.app.bootstrap.runtime_lifecycle import RuntimeLifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,expected", [
    (200, {"model": "owned-fixture", "done": True}, "ready"),
    (503, {"error": "owned_unavailable"}, "degraded"),
    (200, {"error": "owned_model_missing"}, "degraded"),
    (200, {"done": False}, "degraded"),
    (200, "not JSON", "degraded"),
])
async def test_warmup_records_the_actual_http_outcome(monkeypatch, status, payload, expected):
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = (json.dumps(payload) if not isinstance(payload, str) else payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("CV_VISION_MODEL", "owned-fixture")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    runtime = RuntimeLifecycle(vlm_warmup_enabled=lambda: True)
    runtime._app = app = FastAPI()
    try:
        await asyncio.wait_for(runtime._warm_vlm(), timeout=3)
        result = app.state.startup_capabilities["vlm_warmup"]
        assert result["status"] == expected
        assert result["criticality"] == "optional"
        assert observed and observed[0]["model"] == "owned-fixture"
        assert observed[0]["options"]["num_predict"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        assert not thread.is_alive()


@pytest.mark.asyncio
async def test_unreachable_warmup_is_recorded_without_an_unhandled_background_error(monkeypatch):
    with socket.socket() as owned:
        owned.bind(("127.0.0.1", 0))
        port = owned.getsockname()[1]
    monkeypatch.setenv("OLLAMA_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    runtime = RuntimeLifecycle(vlm_warmup_enabled=lambda: True)
    runtime._app = app = FastAPI()
    await asyncio.wait_for(runtime._warm_vlm(), timeout=3)
    result = app.state.startup_capabilities["vlm_warmup"]
    assert result["status"] == "degraded"
    assert result["error_type"] == "ConnectError"
