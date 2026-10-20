"""Performance regression test for the vision triage endpoint.

Covers:
    1. API-level test — POST /api/v1/vision/triage with a minimal PNG must
       complete in < 8 s (pre-fix it blocked the event loop for ~2 minutes).
    2. Playwright E2E test — upload a flagged image through the storefront UI
       and assert the response panel appears within 10 s.

Prior bug: three synchronous calls (analyze_linked_artifact, detect_adversarial,
detect_steganography) were made directly in the async route handler, blocking
uvicorn's event loop.  All three are now dispatched to a thread executor,
capped at 4 s / 8 s respectively.

Run with:
    DISABLE_PLAYWRIGHT_TESTS=0 python -m pytest tests/pw/test_vision_upload_perf.py -v
"""

import os
import time

import pytest
from tests.image_security_fixtures import clean_png_bytes

# ---------------------------------------------------------------------------
# Skip guard — honour the same env var as the rest of the pw suite
# ---------------------------------------------------------------------------
if os.getenv("DISABLE_PLAYWRIGHT_TESTS", "1").strip().lower() in ("1", "true", "yes"):
    pytest.skip(
        "Playwright tests disabled (set DISABLE_PLAYWRIGHT_TESTS=0 to enable)",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Minimal 1×1 PNG (valid image, triggers all security scan paths)
# ---------------------------------------------------------------------------
_MINIMAL_PNG = clean_png_bytes()

# Slightly larger PNG with an embedded plain-text "QR payload" to exercise the
# security-flag / adversarial path without a real ML model.
_FLAGGED_PNG = _MINIMAL_PNG  # same bytes; the monkeypatch injects the flags below


# ---------------------------------------------------------------------------
# PART 1 — Direct API performance test (no browser required)
# ---------------------------------------------------------------------------

_PERF_BUDGET_SECONDS = 8.0  # triage must complete within this wall-clock budget


def _request_with_retry(method, url, attempts=3, timeout=15, **kwargs):
    """Thin retry wrapper to absorb transient port-binding races."""
    import requests  # import inside test scope so skip guard stays clean

    # Do not repeat a POST whose response is uncertain.
    return requests.request(method, url, timeout=timeout, **kwargs)


class TestVisionTriagePerformance:
    """POST /api/v1/vision/triage must return within _PERF_BUDGET_SECONDS."""

    def test_clean_image_completes_within_budget(self, test_server, monkeypatch):
        """Clean image — no security signals — should be fastest path."""
        # Monkeypatch the three previously-blocking calls to be instant no-ops.
        _patch_blocking_calls(monkeypatch)

        base = test_server["base_url"]
        files = [("image", ("clean.png", _MINIMAL_PNG, "image/png"))]

        t0 = time.perf_counter()
        r = _request_with_retry(
            "POST",
            f"{base}/api/v1/vision/triage",
            files=files,
            headers={"x-api-key": "local-merchant-key"},
            timeout=_PERF_BUDGET_SECONDS + 2,
        )
        elapsed = time.perf_counter() - t0

        assert r.status_code == 200, (
            f"Unexpected status {r.status_code}: {r.text[:300]}"
        )
        assert elapsed < _PERF_BUDGET_SECONDS, (
            f"Vision triage took {elapsed:.2f}s — exceeded {_PERF_BUDGET_SECONDS}s budget. "
            "Check that blocking sync calls are still wrapped in thread executors."
        )

    def test_flagged_image_completes_within_budget(self, test_server, monkeypatch):
        """Flagged image — simulated adversarial + steg signals — must still be fast.

        Pre-fix: the adversarial and steg detectors ran synchronously for up to
        8 s each, totalling ~16 s on the event loop.  With the executor wraps the
        wall-clock time is dominated by the mock's instant return.
        """
        _patch_blocking_calls(monkeypatch, inject_flags=True)

        base = test_server["base_url"]
        files = [("image", ("flagged.png", _FLAGGED_PNG, "image/png"))]

        t0 = time.perf_counter()
        r = _request_with_retry(
            "POST",
            f"{base}/api/v1/vision/triage",
            files=files,
            headers={"x-api-key": "local-merchant-key"},
            timeout=_PERF_BUDGET_SECONDS + 2,
        )
        elapsed = time.perf_counter() - t0

        # A flagged image may return 200 or a 4xx security block — both are fine
        # for this perf test; we only care about speed.
        assert r.status_code == 200, (
            f"Server error {r.status_code}: {r.text[:300]}"
        )
        assert elapsed < _PERF_BUDGET_SECONDS, (
            f"Flagged-image triage took {elapsed:.2f}s — exceeded budget. "
            "Executor wraps may have been removed or the timeout increased."
        )

    def test_response_contains_security_signals_key(self, test_server, monkeypatch):
        """Structural contract: response must include a 'security_signals' or
        'security' key so the UI can render the security matrix."""
        _patch_blocking_calls(monkeypatch, inject_flags=True)

        base = test_server["base_url"]
        files = [("image", ("check.png", _MINIMAL_PNG, "image/png"))]

        r = _request_with_retry(
            "POST",
            f"{base}/api/v1/vision/triage",
            files=files,
            headers={"x-api-key": "local-merchant-key"},
            timeout=_PERF_BUDGET_SECONDS + 2,
        )
        assert r.status_code == 200, r.text[:500]
        body = r.json()
        assert isinstance(body["security"]["signals"], dict)
        assert body["security"]["signals"]["adversarial_detected"] is True
        assert body["security"]["signals"]["steg_suspicious"] is True

    def test_health_remains_responsive_while_detector_runs(self, test_server, monkeypatch):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from src.app.security import adversarial_image_detector as adversarial

        _patch_blocking_calls(monkeypatch)
        started, release = Event(), Event()

        def slow_detector(content):
            started.set()
            assert release.wait(timeout=5), "owned detector was not released"
            return adversarial.AdversarialResult()

        monkeypatch.setattr(adversarial, "detect_adversarial", slow_detector)
        base = test_server["base_url"]
        with ThreadPoolExecutor(max_workers=1) as worker:
            pending = worker.submit(_request_with_retry, "POST", base + "/api/v1/vision/triage",
                files=[("image", ("clean.png", _MINIMAL_PNG, "image/png"))],
                headers={"x-api-key": "local-merchant-key"}, timeout=_PERF_BUDGET_SECONDS+2)
            try:
                assert started.wait(timeout=3), "request never reached the detector"
                t0 = time.perf_counter()
                health = _request_with_retry("GET", base + "/health", timeout=1)
                assert health.status_code == 200
                assert time.perf_counter()-t0 < 1
                assert not pending.done(), "detector must still be running during the health probe"
            finally:
                release.set()
            response = pending.result(timeout=_PERF_BUDGET_SECONDS+2)
        assert response.status_code == 200, response.text[:500]


# ---------------------------------------------------------------------------
# PART 2 — Playwright E2E upload performance test
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def vision_ui(test_server, tmp_path_factory):
    """Serve this checkout's real React UI against only its owned API."""
    import json
    from pathlib import Path
    import shutil
    import socket
    import subprocess
    import psutil
    import requests

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    vite = frontend / "node_modules/vite/bin/vite.js"
    node = shutil.which("node")
    assert node and vite.is_file(), "the required UI profile needs the installed pinned frontend tools"
    directory = tmp_path_factory.mktemp("vision-owned-ui")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    env = {**os.environ, "VITE_API_PROXY_TARGET": test_server["base_url"],
           "VITE_API_BASE_URL": "", "VITE_API_KEY": "", "VITE_OWNER_API_KEY": "",
           "VITE_CACHE_DIR": str(directory / "vite-cache")}
    log_path = directory / "vite.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([node, str(vite), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=frontend, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (directory / "owner.json").write_text(json.dumps({"pid": process.pid, "base_url": base}), encoding="utf-8")
        try:
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                assert process.poll() is None, f"owned Vite exited; inspect {log_path}"
                if base in log_path.read_text(encoding="utf-8", errors="replace"):
                    try:
                        ready = requests.get(base, timeout=1)
                        if ready.status_code == 200 and "@vite/client" in ready.text:
                            break
                    except requests.ConnectionError:
                        pass
                time.sleep(0.1)
            else:
                pytest.fail(f"owned Vite was not ready; inspect {log_path}")
            yield base
        finally:
            if process.poll() is None:
                parent = psutil.Process(process.pid)
                owned = [*parent.children(recursive=True), parent]
                for child in owned:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
                _, alive = psutil.wait_procs(owned, timeout=5)
                for child in alive:
                    child.kill()
                psutil.wait_procs(alive, timeout=5)
            process.wait(timeout=5)


class TestVisionUploadE2EPerf:
    """Browser E2E: uploading an image in the storefront must populate the
    recommendation panel within 10 s (was ~2 minutes before the async fix)."""

    _E2E_BUDGET_SECONDS = 10.0

    def test_image_upload_populates_panel_within_budget(self, vision_ui, test_server, page):
        from urllib.parse import urlparse, parse_qs
        from playwright.sync_api import expect
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.context.set_extra_http_headers({"x-api-key": test_server["api_key"]})
        page.goto(vision_ui, timeout=15_000)
        page.get_by_role("button", name="Ask Me!", exact=True).click()
        query = page.get_by_placeholder("Type your message...")
        expect(query).to_be_visible()
        upload = page.locator("input[type='file']").last
        expect(upload).to_be_attached()
        upload.set_input_files({"name": "owned-clean.png", "mimeType": "image/png", "buffer": _MINIMAL_PNG})
        expect(page.get_by_role("img", name="attached 1", exact=True)).to_be_visible()
        query.fill("Inspect this image. Do not add anything to my cart.")
        t0 = time.perf_counter()
        with page.expect_response(lambda response: "/api/v1/vision/triage" in response.url
                and response.request.method == "POST" and "fast" not in parse_qs(urlparse(response.url).query),
                timeout=int(self._E2E_BUDGET_SECONDS*1000)) as pending:
            query.press("Enter")
        response = pending.value
        assert response.status == 200, response.text()[:500]
        body = response.json()
        assert body["security"]["analysis_stage"] == "full"
        assert body["artifact"]["artifact_id"]
        expect(page.locator("[class*='anchorHeader']").first).to_be_visible(
            timeout=max(1, int((self._E2E_BUDGET_SECONDS-(time.perf_counter()-t0))*1000)))
        assert time.perf_counter()-t0 < self._E2E_BUDGET_SECONDS
        assert errors == []



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_blocking_calls(monkeypatch, *, inject_flags: bool = False):
    """Replace the three previously-blocking sync functions with instant stubs.

    This makes the performance test deterministic — we assert that the *wiring*
    (executor + timeout) is still in place, not that the real ML models are fast.
    """
    from src.app.security import linked_artifact_analysis as linked
    from src.app.security import adversarial_image_detector as adversarial
    from src.app.security import steg_detector as steg

    monkeypatch.setattr(linked, "analyze_linked_artifact", lambda *args, **kwargs: {
        "linked_artifact_available": False, "linked_artifact_type": None,
        "ssn_hits": [], "pii_type": [], "linked_final_url": None,
    })
    monkeypatch.setattr(adversarial, "detect_adversarial", lambda content:
        adversarial.AdversarialResult(is_adversarial=inject_flags,
                                      adversarial_score=0.95 if inject_flags else 0.02))
    monkeypatch.setattr(steg, "detect_steganography", lambda content:
        steg.StegResult(is_suspicious=inject_flags, steg_score=0.9 if inject_flags else 0.0,
                        explanations=["Owned injected detector control"] if inject_flags else []))
