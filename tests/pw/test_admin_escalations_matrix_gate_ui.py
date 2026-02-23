import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import requests


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def _find_free_port(start: int = 5174) -> int:
    port = start
    while _is_port_open("127.0.0.1", port):
        port += 1
    return port


def _wait_http_ready(url: str, timeout_s: int = 75) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Admin frontend did not become ready: {url}")


@pytest.fixture(scope="module")
def admin_frontend_server(test_server):
    admin_dir = Path(__file__).resolve().parents[2] / "src" / "frontend" / "admin-react"
    if not admin_dir.exists():
        raise RuntimeError(f"admin-react directory not found: {admin_dir}")

    requested_port = int(os.getenv("PLAYWRIGHT_ADMIN_FRONTEND_PORT", "5174"))
    port = _find_free_port(requested_port)
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["VITE_API_BASE"] = test_server["base_url"]
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        pytest.skip("npm executable not found in PATH for admin Playwright test")

    proc = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(admin_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_http_ready(base_url, timeout_s=90)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_escalations_shows_matrix_gate_error_on_409(page, admin_frontend_server):
    incident_id = "inc-matrix-001"

    page.add_init_script(
        """
        localStorage.setItem('shopsquire_api_key', 'local-merchant-key');
        localStorage.setItem('x-api-key', 'local-merchant-key');
        """
    )

    page.route(
        "**/api/v1/admin/incidents?**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"incidents":[{"id":"inc-matrix-001","title":"Matrix Gate Incident","severity":"high","status":"review","created_at":"2026-02-22T09:00:00Z"}]}',
        ),
    )
    page.route(
        f"**/api/v1/admin/incidents/{incident_id}",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"id":"inc-matrix-001","title":"Matrix Gate Incident","severity":"high","status":"review","description":{"reason":"security_review","trace_id":"trace-matrix-001"}}',
        ),
    )
    page.route(
        f"**/api/v1/admin/incidents/{incident_id}/room/token",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"ok":true,"staff_token":"staff-matrix-1","ttl_seconds":86400}'),
    )
    page.route(
        f"**/api/v1/incidents/{incident_id}/room/stream**",
        lambda route: route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body="data: []\n\n"),
    )
    page.route(
        f"**/api/v1/admin/incidents/{incident_id}/status**",
        lambda route: route.fulfill(status=409, content_type="application/json", body='{"detail":"matrix_completeness_required"}'),
    )

    page.goto(f"{admin_frontend_server}/?tab=escalations&incident_id={incident_id}", wait_until="domcontentloaded")
    page.get_by_text("Human Escalations Console", exact=False).wait_for(timeout=15000)
    page.get_by_text("Matrix Gate Incident", exact=False).click()
    page.get_by_role("button", name="Mark resolved").click()
    page.get_by_text("Cannot close incident yet: Security Matrix is incomplete for this trace.", exact=False).wait_for(timeout=10000)

