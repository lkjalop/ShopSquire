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


def _find_free_port(start: int = 5173) -> int:
    port = start
    while _is_port_open("127.0.0.1", port):
        port += 1
    return port


def _wait_http_ready(url: str, timeout_s: int = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Frontend did not become ready: {url}")


@pytest.fixture(scope="module")
def frontend_server(test_server):
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if not frontend_dir.exists():
        raise RuntimeError(f"frontend directory not found: {frontend_dir}")

    requested_port = int(os.getenv("PLAYWRIGHT_FRONTEND_PORT", "5173"))
    port = _find_free_port(requested_port)
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["VITE_API_BASE_URL"] = test_server["base_url"]
    env["VITE_ALLOW_OFFLINE_FALLBACK"] = "0"
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        pytest.skip("npm executable not found in PATH for Playwright smoke test")

    proc = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(frontend_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        _wait_http_ready(base_url, timeout_s=75)
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_storefront_shows_assistant_not_admin(page, frontend_server):
    page.goto(frontend_server, wait_until="domcontentloaded")

    ask_button = page.get_by_role("button", name="Ask Me!")
    ask_button.wait_for(state="visible", timeout=10000)
    assert ask_button.is_visible()

    assert page.locator("text=ShopSquire Admin").count() == 0

    ask_button.click()
    assistant_title = page.get_by_text("ShopSquire Assistant", exact=True)
    assistant_title.wait_for(state="visible", timeout=10000)
    assert assistant_title.is_visible()

    assert page.locator("text=ShopSquire Admin").count() == 0
