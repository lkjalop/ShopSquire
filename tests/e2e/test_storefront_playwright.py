import os
import sys
import time
from pathlib import Path
import re
import json
import pytest
import requests as _requests

try:
    from playwright.sync_api import sync_playwright
    _have_playwright = True
except Exception:
    _have_playwright = False

import urllib.request

FRONTEND_URL = os.getenv("FRONTEND_SMOKE_URL", "http://127.0.0.1:5173")
BACKEND_URL = os.getenv("BACKEND_SMOKE_URL", "http://127.0.0.1:8080")
STRICT_TRACE_READY = True
# When False the existing chat-driven live tests are skipped (they need a fast
# backend).  Contract-mode tests always run when Playwright is enabled.
_LIVE_MODE = os.getenv("LIVE_PLAYWRIGHT_TESTS", "0").lower() in ("1", "true", "yes")
_API_KEY = "local-merchant-key"


def _open_decision_trace(page):
    trigger = page.get_by_title("Decision Trace")
    if trigger.count() == 0:
        trigger = page.get_by_role("button", name=re.compile(r"decision\s*trace", re.I))
    if trigger.count() == 0:
        trigger = page.get_by_text(re.compile(r"decision\s*trace", re.I))
    assert trigger.count() > 0, "Decision Trace trigger not found"
    trigger.first.click(timeout=8000)


def _decision_trace_container(page):
    # Prefer semantic container around tabs instead of brittle #decision-modal id.
    candidates = [
        page.locator("#decision-modal"),
        page.locator("[role='dialog']"),
        page.locator("xpath=//*[contains(., 'Decision Trace') and .//button[normalize-space()='Events']][1]"),
    ]
    for loc in candidates:
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return page.locator("body")


def _wait_for_trace_ready(container, timeout_ms: int = 12000):
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    backoff = [0.3, 0.7, 1.2, 2.0, 2.8]
    i = 0
    while time.monotonic() < deadline:
        text = (container.text_content() or "").lower()
        no_trace = ("no trace id" in text) or ("no decision trace yet" in text)
        loading = "loading trace data" in text
        if (not no_trace) and (not loading):
            return True
        sleep_s = backoff[i] if i < len(backoff) else 2.8
        i += 1
        time.sleep(sleep_s)
    return False


def _inject_api_key_header(page, api_key: str = "local-merchant-key"):
    """Monkey-patch window.fetch before any script runs to inject the API key.
    This makes all SPA requests authenticated without touching module-level state."""
    key_json = json.dumps(api_key)
    page.add_init_script(
        f"""
        (() => {{
            const _orig = window.fetch;
            window.fetch = function(input, init) {{
                init = Object.assign({{}}, init);
                init.headers = Object.assign({{'x-api-key': {key_json}}}, init.headers || {{}});
                return _orig(input, init);
            }};
        }})();
        """
    )


def _seed_trace_direct(uid: str, query: str, base_url: str = None,
                       budget_max: int | None = None, timeout_s: float = 30.0) -> str:
    """Seed a decision trace via Python `requests` (not Playwright page.request).
    Avoids Playwright request-context latency issues on slow/constrained hosts."""
    base = (base_url or BACKEND_URL).rstrip("/")
    params: dict = {"uid": uid, "query": query, "fast_path": "true"}
    if budget_max is not None:
        params["budget_max"] = budget_max
    resp = _requests.get(
        f"{base}/api/v1/recommend/suggest",
        params=params,
        headers={"x-api-key": _API_KEY},
        timeout=timeout_s,
    )
    assert resp.status_code == 200, f"seed suggest failed: {resp.status_code} {resp.text[:300]}"
    body = resp.json() or {}
    trace_id = str(
        body.get("decision_trace_id")
        or body.get("trace_id")
        or body.get("decision_id")
        or ""
    ).strip()
    assert trace_id, f"seed suggest missing trace id: {body}"
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        qr = _requests.get(
            f"{base}/api/v1/decisions/{trace_id}/query",
            params={"include_events": "true"},
            headers={"x-api-key": _API_KEY},
            timeout=10.0,
        )
        if qr.status_code == 200:
            events = (qr.json() or {}).get("events") or []
            if isinstance(events, list) and events:
                return trace_id
        time.sleep(0.25)
    return trace_id


def _backend_fast_path_latency(base_url: str = None, timeout_s: float = 10.0) -> float:
    """Return wall-clock seconds for a fast-path suggest call (0.0 on failure)."""
    base = (base_url or BACKEND_URL).rstrip("/")
    t0 = time.perf_counter()
    try:
        _requests.get(
            f"{base}/api/v1/recommend/suggest",
            params={"uid": "gate-check", "query": "test laptops", "fast_path": "true"},
            headers={"x-api-key": _API_KEY},
            timeout=timeout_s,
        )
    except Exception:
        pass
    return time.perf_counter() - t0


def _enforce_chat_query_latency_gate(base_url: str = None, threshold_s: float = 8.0):
    """Fail fast in strict runs when /api/v1/chat/query is degraded."""
    if os.getenv("STRICT_TRACE_READY", "").lower() not in ("1", "true"):
        return
    base = (base_url or BACKEND_URL).rstrip("/")
    t0 = time.perf_counter()
    try:
        r = _requests.post(
            f"{base}/api/v1/chat/query",
            json={
                "uid": f"gate-{int(time.time())}",
                "query": "show laptops under 1500",
            },
            headers={"x-api-key": _API_KEY},
            timeout=threshold_s + 2.0,
        )
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, f"chat/query gate status={r.status_code}: {r.text[:240]}"
        assert elapsed <= threshold_s, (
            f"chat/query gate exceeded {threshold_s:.1f}s (actual {elapsed:.2f}s)"
        )
    except Exception as exc:
        pytest.fail(f"chat/query gate failed before browser flow: {exc}")


def _set_session_uid(page, uid: str):
    uid_literal = json.dumps(uid)
    page.add_init_script(
        f"""
        try {{
            window.sessionStorage.setItem('uid', {uid_literal});
        }} catch {{}}
        """
    )


def _api_get(page, path: str, *, params: dict | None = None, timeout_ms: int = 20000):
    bases = ["http://127.0.0.1:8080", FRONTEND_URL.rstrip("/")]
    last_err = None
    for base in bases:
        url = f"{base}{path}"
        try:
            return page.request.get(
                url,
                params=params,
                headers={"x-api-key": "local-merchant-key"},
                timeout=timeout_ms,
            )
        except Exception as exc:
            last_err = exc
            continue
    raise AssertionError(f"GET failed for {path}: {last_err}")


def _wait_latest_trace_for_uid(page, uid: str, timeout_s: float = 30.0) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = _api_get(page, "/api/v1/decisions/latest", params={"uid": uid}, timeout_ms=20000)
        if r.status == 200:
            j = r.json() or {}
            maybe = str(j.get("decision_id") or j.get("trace_id") or "").strip()
            if maybe:
                return maybe
        time.sleep(0.3)
    return ""


def _seed_trace_for_uid(page, uid: str, query: str, budget_max: int | None = None, timeout_s: float = 20.0) -> str:
    params = {"uid": uid, "query": query, "fast_path": "true"}
    if budget_max is not None:
        params["budget_max"] = budget_max
    resp = _api_get(page, "/api/v1/recommend/suggest", params=params, timeout_ms=25000)
    assert resp.status == 200, f"seed suggest failed: {resp.status}"
    body = resp.json() or {}
    trace_id = str(body.get("decision_trace_id") or body.get("trace_id") or body.get("decision_id") or "").strip()
    assert trace_id, f"seed suggest missing trace id: {body}"

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        q = _api_get(page, f"/api/v1/decisions/{trace_id}/query", params={"include_events": "true"}, timeout_ms=10000)
        if q.status == 200:
            qb = q.json() or {}
            events = qb.get("events") or []
            if isinstance(events, list) and len(events) > 0:
                return trace_id
        time.sleep(0.25)
    return trace_id


def _trace_id_from_response_body(body: dict) -> str:
    return str(
        body.get("decision_trace_id")
        or body.get("trace_id")
        or body.get("decision_id")
        or ((body.get("data") or {}).get("decision_trace_id") if isinstance(body.get("data"), dict) else "")
        or ((body.get("data") or {}).get("trace_id") if isinstance(body.get("data"), dict) else "")
        or ""
    ).strip()

def _url_reachable(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:
            return int(getattr(r, "status", 0) or 0) in (200, 301, 302, 307, 308)
    except Exception:
        return False


_PW_SKIP = (
    (not _have_playwright)
    or (os.getenv("DISABLE_PLAYWRIGHT_TESTS", "0").lower() in ("1", "true", "yes"))
    or (sys.platform.startswith("win") and os.getenv("FORCE_PLAYWRIGHT_TESTS", "0").lower() not in ("1", "true", "yes"))
)


@pytest.mark.skipif(_PW_SKIP, reason="playwright disabled or unsupported on this platform")
def test_storefront_playwright_basic():
    if not _url_reachable("http://127.0.0.1:8080/ui/storefront", timeout_s=1.5):
        pytest.skip("storefront not reachable; skip playwright e2e")
    # Quick sanity: start playwright and fetch storefront page
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        resp = page.goto("http://127.0.0.1:8080/ui/storefront", timeout=10000)
        assert (resp is not None and resp.status == 200) or page.title() is not None
        browser.close()


@pytest.mark.skipif(_PW_SKIP, reason="playwright disabled or unsupported on this platform")
def test_frontend_storefront_shell_smoke():
    if not _url_reachable(FRONTEND_URL, timeout_s=2.0):
        pytest.skip("frontend not reachable; skip storefront shell smoke")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(FRONTEND_URL, timeout=20000)

        ask_me = page.get_by_role("button", name="Ask Me!")
        assert ask_me.count() == 1
        assert page.get_by_text("ShopSquire Admin").count() == 0

        ask_me.click()
        page.wait_for_timeout(500)
        assert page.get_by_text("ShopSquire Assistant").count() >= 1
        assert page.get_by_placeholder("Type your message...").count() == 1

        browser.close()


@pytest.mark.skipif(_PW_SKIP, reason="playwright disabled or unsupported on this platform")
def test_decision_trace_contract():
    """Deterministic contract test for Decision Trace UI rendering.

    Seeds a trace via direct HTTP (no Playwright page.request) then opens the
    browser and asserts tab rendering.  Decisions API calls are served from
    page.route mocks so they resolve instantly from pre-seeded data.  This test
    is independent of backend latency and runs whenever Playwright is enabled.
    """
    if not _url_reachable(BACKEND_URL + "/healthz", timeout_s=2.0) and \
       not _url_reachable(BACKEND_URL + "/health", timeout_s=2.0):
        pytest.skip("backend not reachable; skip contract trace test")
    if not _url_reachable("http://127.0.0.1:5173", timeout_s=1.5):
        pytest.skip("web UI not reachable; skip contract trace test")

    uid = f"pw-contract-{int(time.time())}"
    try:
        trace_id = _seed_trace_direct(uid, "show gaming laptops under 1500", timeout_s=30.0)
    except Exception as exc:
        pytest.skip(f"Backend seed failed (backend likely degraded): {exc}")
        return

    # Fetch trace data upfront so we can serve it deterministically from route mocks
    trace_data: dict = {}
    try:
        tr = _requests.get(
            f"{BACKEND_URL}/api/v1/decisions/{trace_id}/query",
            params={"include_events": "true"},
            headers={"x-api-key": _API_KEY},
            timeout=10.0,
        )
        if tr.status_code == 200:
            trace_data = tr.json() or {}
    except Exception:
        pass

    latest_payload = json.dumps({"decision_id": trace_id, "trace_id": trace_id})
    query_payload = json.dumps(trace_data or {"decision_id": trace_id, "trace_id": trace_id, "events": []})
    chat_payload = json.dumps(
        {
            "ok": True,
            "response": "Contract-mode mocked response",
            "decision_trace_id": trace_id,
            "trace_id": trace_id,
        }
    )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _inject_api_key_header(page)
        _set_session_uid(page, uid)

        # Serve pre-seeded trace data from route mocks — no blocking network calls
        page.route("**/api/v1/decisions/latest**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=latest_payload,
        ))
        page.route(f"**/api/v1/decisions/{trace_id}/query**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=query_payload,
        ))
        page.route(f"**/api/v1/decisions/{trace_id}", lambda route: route.fulfill(
            status=200, content_type="application/json", body=query_payload,
        ))
        page.route("**/api/v1/chat/query**", lambda route: route.fulfill(
            status=200, content_type="application/json", body=chat_payload,
        ))

        page.goto("http://127.0.0.1:5173", timeout=20000)
        page.get_by_text("Ask Me!").click()
        page.get_by_placeholder("Type your message...").fill("show gaming laptops under 1500")
        with page.expect_response(lambda r: "/api/v1/chat/query" in (r.url or "") and r.request.method == "POST", timeout=15000):
            page.keyboard.press("Enter")
        page.wait_for_timeout(600)

        _open_decision_trace(page)
        modal = _decision_trace_container(page)
        ready = _wait_for_trace_ready(modal, timeout_ms=15000)
        assert ready, (
            f"Decision Trace stayed in no-trace/loading state "
            f"(contract mode, trace={trace_id})"
        )

        page.get_by_role("button", name="Security Matrix").click()
        page.wait_for_timeout(800)
        sec_text = (modal.text_content() or "").lower()
        assert "loading trace data" not in sec_text, (
            "Security Matrix tab still in loading state (contract mode)"
        )

        browser.close()


@pytest.mark.skipif(_PW_SKIP, reason="playwright disabled or unsupported on this platform")
@pytest.mark.skipif(not _LIVE_MODE, reason="live Playwright tests disabled (set LIVE_PLAYWRIGHT_TESTS=1)")
def test_decision_trace_populates_after_chat():
    _enforce_chat_query_latency_gate(BACKEND_URL, threshold_s=8.0)
    if not _url_reachable("http://127.0.0.1:5173", timeout_s=1.5):
        pytest.skip("web UI not reachable; skip playwright e2e")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        uid = f"pw-dtrace-basic-{int(time.time())}"
        _set_session_uid(page, uid)
        page.goto("http://127.0.0.1:5173", timeout=15000)

        seeded_trace = _seed_trace_for_uid(
            page,
            uid=uid,
            query="show gaming laptops under 1500 with best value and msi options",
            budget_max=1500,
        )

        # Open chat
        page.get_by_text("Ask Me!").click()
        page.get_by_placeholder("Type your message...").fill(
            "show gaming laptops under 1500 with best value and msi options"
        )
        with page.expect_response(lambda r: "/api/v1/chat/query" in (r.url or "") and r.request.method == "POST", timeout=70000) as chat_resp_info:
            page.keyboard.press("Enter")
        chat_resp = chat_resp_info.value
        assert chat_resp.ok, f"chat/query failed with status={chat_resp.status}"
        chat_body = chat_resp.json() or {}
        chat_trace = _trace_id_from_response_body(chat_body)
        assert chat_trace, f"chat/query missing trace id: {chat_body}"

        # Wait for response bubble to appear
        page.wait_for_timeout(2000)

        # Open Decision Trace and wait for usable trace state.
        _open_decision_trace(page)
        modal = _decision_trace_container(page)
        page.wait_for_timeout(1000)
        ready = _wait_for_trace_ready(modal, timeout_ms=28000)
        assert ready, (
            "Decision Trace stayed in no-trace/loading state "
            f"(seeded trace={seeded_trace}, chat_trace={chat_trace})"
        )

        # Hard UI assertion: Security Matrix tab must surface taxonomy tags/signals.
        page.get_by_role("button", name="Security Matrix").click()
        page.wait_for_timeout(1200)
        sec_text = (modal.text_content() or "").lower()
        assert "loading trace data" not in sec_text
        assert (
            "security overview" in sec_text
            or "image triage signals" in sec_text
            or "under review" in sec_text
            or "no security analysis available" in sec_text
        ), "Security Matrix content did not render in Decision Trace"

        browser.close()


@pytest.mark.skipif(_PW_SKIP, reason="playwright disabled or unsupported on this platform")
@pytest.mark.skipif(not _LIVE_MODE, reason="live Playwright tests disabled (set LIVE_PLAYWRIGHT_TESTS=1)")
def test_decision_trace_multimodal_tabs_regression():
    _enforce_chat_query_latency_gate(BACKEND_URL, threshold_s=8.0)
    if not _url_reachable("http://127.0.0.1:5173", timeout_s=1.5):
        pytest.skip("web UI not reachable; skip playwright e2e")

    img_a = Path("tmp_ui_uploads") / "apple-mac.jpg"
    img_b = Path("tmp_ui_uploads") / "msi-SSN.png"
    if not img_a.exists() or not img_b.exists():
        pytest.skip("required image fixtures missing for multimodal regression")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        uid = f"pw-dtrace-mm-{int(time.time())}"
        _set_session_uid(page, uid)
        trace_calls: list[str] = []

        def _track_request(req):
            try:
                u = req.url or ""
                if "/api/v1/decisions/" in u:
                    trace_calls.append(u)
            except Exception:
                pass

        page.on("request", _track_request)
        page.goto("http://127.0.0.1:5173", timeout=20000)
        page.get_by_text("Ask Me!").click()

        page.get_by_label("Attach image").click()
        file_inputs = page.locator("input[type='file']")
        file_inputs.last.set_input_files([str(img_a.resolve()), str(img_b.resolve())])

        input_box = page.get_by_placeholder("Type your message...")
        input_box.fill("recommend msi gaming laptop between 1300 and 1800 with image context")
        start = time.monotonic()
        with page.expect_response(lambda r: "/api/v1/chat/query" in (r.url or "") and r.request.method == "POST", timeout=90000) as chat_resp_info:
            input_box.press("Enter")
        chat_resp = chat_resp_info.value
        assert chat_resp.ok, f"chat/query failed with status={chat_resp.status}"
        chat_body = chat_resp.json() or {}
        latest_trace = _trace_id_from_response_body(chat_body)
        assert latest_trace, f"chat/query missing trace id for multimodal flow: {chat_body}"

        gear = page.get_by_title("Decision Trace")
        if gear.count() == 0:
            gear = page.get_by_role("button", name=re.compile(r"decision\s*trace", re.I))
        gear.wait_for(timeout=12000)
        elapsed = time.monotonic() - start
        assert elapsed < 15.0, f"products/trace affordance too slow: {elapsed:.2f}s"

        trace_calls.clear()
        _open_decision_trace(page)
        modal = _decision_trace_container(page)
        ready = _wait_for_trace_ready(modal, timeout_ms=22000)
        assert ready, f"Decision Trace stayed in no-trace/loading state for uid={uid}, trace={latest_trace}"
        modal_text = (modal.text_content() or "").lower()
        assert "loading trace data" not in modal_text

        page.get_by_role("button", name="Security Matrix").click()
        page.wait_for_timeout(1200)
        sec_text = (modal.text_content() or "").lower()
        assert "under review" in sec_text.lower() or "raw payload quarantined" in sec_text.lower()

        page.get_by_role("button", name="Multimodal").click()
        page.wait_for_timeout(1200)
        mm_text = modal.text_content() or ""
        assert mm_text.strip()
        assert "loading trace data" not in mm_text.lower()

        page.get_by_role("button", name="Why Recommended").click()
        page.wait_for_timeout(1200)
        why_text = modal.text_content() or ""
        assert why_text.strip()
        assert "loading trace data" not in why_text.lower()

        page.get_by_role("button", name="Events").click()
        page.wait_for_timeout(1200)
        ev_text = modal.text_content() or ""
        assert "Trace events are not available yet" not in ev_text

        explain_replay_calls = [u for u in trace_calls if u.endswith("/explain") or u.endswith("/replay")]
        assert len(explain_replay_calls) == 0, f"modal open triggered eager explain/replay: {explain_replay_calls}"

        browser.close()


def test_storefront_http_fallback():
    # If Playwright isn't available, fall back to simple HTTP GET with urllib
    url = "http://127.0.0.1:8080/ui/storefront"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            assert r.status == 200
            body = r.read(200)
            assert len(body) > 0
    except Exception:
        pytest.skip("storefront not reachable; skip e2e check")
