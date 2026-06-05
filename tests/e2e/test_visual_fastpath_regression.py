import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
import urllib.request

import pytest

pytest.importorskip("playwright", reason="Playwright not installed")
from playwright.sync_api import sync_playwright


FRONTEND_URL = os.getenv("FRONTEND_SMOKE_URL", "http://127.0.0.1:5173")
BACKEND_URL = os.getenv("BACKEND_SMOKE_URL", "http://127.0.0.1:8080")
LIVE = os.getenv("LIVE_PLAYWRIGHT_TESTS", "0").lower() in {"1", "true", "yes"}


def _wait_url(url: str, timeout_s: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_s
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:
            last = exc
        time.sleep(0.5)
    pytest.skip(f"{url} not reachable: {last}")


def _url_ok(url: str, timeout_s: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return int(getattr(resp, "status", 0) or 0) < 500
    except Exception:
        return False


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def stable_live_stack():
    """Use an already-running stack, or start a Windows-safe local demo stack."""
    api_proc = None
    ui_proc = None
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    backend_port = int(os.getenv("BACKEND_SMOKE_PORT", "8080"))
    frontend_port = int(os.getenv("FRONTEND_SMOKE_PORT", "5173"))
    backend_host = "127.0.0.1"
    frontend_host = "127.0.0.1"

    if not _url_ok(f"http://{backend_host}:{backend_port}/healthz"):
        env = os.environ.copy()
        env.update(
            {
                "APP_ENV": "dev",
                "DATABASE_URL": env.get("DATABASE_URL", "sqlite:///test.sqlite"),
                "TEST_USE_FALLBACK_PRODUCTS": "1",
                "USE_LLM_SUMMARY": "0",
                "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                "VISUAL_SEARCH_PREWARM_ON_START": "0",
                "VISUAL_SEARCH_INDEX_ON_START": "0",
                "FAQ_VECTOR_INDEX_ON_START": "0",
                "CV_WARMUP_ON_START": "0",
                "CV_PROVIDER": env.get("CV_PROVIDER", "none"),
                "RATE_LIMIT_PER_IP_PER_MIN": "0",
            }
        )
        py = str(Path(".venv/Scripts/python.exe")) if Path(".venv/Scripts/python.exe").exists() else sys.executable
        api_proc = subprocess.Popen(
            [py, "-m", "uvicorn", "src.app.main:app", "--host", backend_host, "--port", str(backend_port)],
            cwd=str(Path.cwd()),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _wait_url(f"http://{backend_host}:{backend_port}/healthz", 90.0)

    if not _port_open(frontend_host, frontend_port):
        env = os.environ.copy()
        env["VITE_API_BASE_URL"] = f"http://{backend_host}:{backend_port}"
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not npm:
            pytest.skip("npm not available to start frontend")
        ui_proc = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", frontend_host, "--port", str(frontend_port)],
            cwd=str(Path.cwd() / "frontend"),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        _wait_url(f"http://{frontend_host}:{frontend_port}/", 90.0)

    try:
        yield
    finally:
        for proc in (ui_proc, api_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


@pytest.mark.skipif(not LIVE, reason="live Playwright regression disabled; set LIVE_PLAYWRIGHT_TESTS=1")
def test_compromised_images_render_products_trace_tabs_and_healthz(stable_live_stack):
    _wait_url(f"{FRONTEND_URL}/", 20.0)
    _wait_url(f"{BACKEND_URL}/healthz", 45.0)
    apple = Path("dump/test-cv/apple-red.jpg")
    msi = Path("dump/test-cv/msi-SSN.png")
    assert apple.exists()
    assert msi.exists()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.add_init_script(
            """
            (() => {
              const originalFetch = window.fetch;
              window.fetch = (input, init = {}) => {
                init = Object.assign({}, init);
                init.headers = Object.assign({'x-api-key': 'local-merchant-key'}, init.headers || {});
                return originalFetch(input, init);
              };
            })();
            """
        )
        start = time.monotonic()
        page.goto(f"{FRONTEND_URL}/?e2e=visual-fastpath-regression", timeout=30000)
        page.get_by_text("Ask Me!").click(timeout=10000)
        page.locator("input[type='file']").last.set_input_files([str(apple.resolve()), str(msi.resolve())])
        box = page.get_by_placeholder("Type your message...")
        box.fill("please recommend gaming laptops between 1300 to 1800?")
        box.press("Enter")

        body_text = ""
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            body_text = page.locator("body").inner_text(timeout=2000)
            if re.search(r"MSI|Katana|Thin A15|LOQ", body_text, re.I):
                break
            page.wait_for_timeout(250)
        assert re.search(r"MSI|Katana|Thin A15|LOQ", body_text, re.I), body_text[-1200:]
        assert time.monotonic() - start < 10.0

        trigger = page.get_by_title("Decision Trace")
        if trigger.count() == 0:
            trigger = page.get_by_role("button", name=re.compile(r"decision\s*trace", re.I))
        trigger.first.click(timeout=10000)
        modal = page.locator("xpath=//*[contains(., 'Decision Trace') and .//button[normalize-space()='Events']][1]").first
        modal.wait_for(timeout=8000)

        for tab in ["Events", "Summary", "Why Recommended", "Intent", "Multimodal", "Complexity", "Memory", "Security Matrix"]:
            page.get_by_role("button", name=tab, exact=True).click(timeout=5000)
            page.wait_for_timeout(400)
            text = modal.inner_text(timeout=5000)
            assert "Loading trace data" not in text

        page.get_by_role("button", name="Security Matrix", exact=True).click()
        sec_text = modal.inner_text(timeout=5000).lower()
        assert "maestro" in sec_text or "sc-04b" in sec_text or "raw_image_payload_quarantined" in sec_text

        health_start = time.monotonic()
        with urllib.request.urlopen(f"{BACKEND_URL}/healthz", timeout=2.0) as resp:
            assert resp.status == 200
        assert time.monotonic() - health_start < 2.0
        browser.close()
