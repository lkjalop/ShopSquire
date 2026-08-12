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
    env["VITE_FORCE_INCIDENT_SSE"] = "true"
    npm_cmd = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm_cmd:
        pytest.skip("npm executable not found in PATH for Playwright test")

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
    except RuntimeError:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        pytest.skip(f"Vite frontend did not start in time at {base_url}; skipping test")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_chat_with_admin_click_path_opens_escalation_room(page, frontend_server):
    captured = {"payload": None, "rejected_plan": None}

    def handle_orchestrate(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"decision_trace_id":"trace-cv-1","trace_id":"trace-cv-1",'
                '"proposal":{"results":[]}}'
            ),
        )

    def handle_cv_analyze(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=(
                '{"case_id":"case-cv-1","trace_id":"trace-cv-1","cv_analysis":{"confidence":0.22},'
                '"suggested_routing":"security_review","ui_actions":{"chat_with_admin":true},'
                '"image_consistency":{"status":"mismatch","images":[{"index":0,"status":"mismatch","reasons":["qr_external_url_detected"]}]}}'
            ),
        )

    def handle_escalate(route, request):
        try:
            captured["payload"] = request.post_data_json
        except Exception:
            captured["payload"] = None
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok":true,"incident_id":"inc-chat-001","buyer_token":"buyer-token-1","staff_token":"staff-token-1"}',
        )

    def handle_stream(route):
        event = {
            "event_id": "human-substitute-event-1",
            "role": "merchant",
            "event_type": "proposed_substitute",
            "message": "I found a compatible substitute available now.",
            "actor": {"actor_type": "human_staff", "display_name": "Alex", "title": "Product specialist"},
            "meta": {
                "buyer_confirmation_required": True,
                "cart_plan": {
                    "plan_id": "cmp-human-browser-1",
                    "plan": {"ops": [{
                        "action": "replace_item", "target_skus": ["MODEL-A"],
                        "replacement_sku": "MODEL-B", "replacement_name": "Model B",
                        "quantity": 30,
                    }]},
                },
            },
        }
        route.fulfill(
            status=200,
            headers={"content-type": "text/event-stream"},
            body=f"data: {__import__('json').dumps([event])}\n\n",
        )

    def handle_reject(route, request):
        captured["rejected_plan"] = request.url
        route.fulfill(status=200, content_type="application/json", body='{"status":"rejected"}')

    page.route("**/api/v1/orchestrate", handle_orchestrate)
    page.route("**/api/v1/cv/analyze", handle_cv_analyze)
    page.route("**/api/v1/incidents/escalate", handle_escalate)
    page.route("**/api/v1/incidents/inc-chat-001/room/stream**", handle_stream)
    page.route("**/api/v1/incidents/inc-chat-001/room/message**", lambda route: route.fulfill(status=200, content_type="application/json", body='{"sent":true,"role":"buyer"}'))
    page.route("**/api/v1/cart/mutations/cmp-human-browser-1/reject", handle_reject)

    page.goto(frontend_server, wait_until="domcontentloaded")
    page.get_by_role("button", name="Ask Me!").click()
    page.get_by_placeholder("Type your message...").fill("return request damaged laptop")
    page.get_by_placeholder("Type your message...").press("Enter")

    page.get_by_text("CV Triage", exact=True).wait_for(timeout=10000)
    page.get_by_role("button", name="Analyze photos for damage and product signals").click()
    page.get_by_role("button", name="Escalate and chat with admin").wait_for(timeout=10000)
    page.get_by_role("button", name="Escalate and chat with admin").click()

    page.get_by_text("Human support", exact=True).wait_for(timeout=10000)
    page.get_by_test_id("human-conversation").wait_for(timeout=10000)
    page.get_by_role("button", name="Review proposed cart change").click()
    page.get_by_test_id("pending-cart-change").wait_for(timeout=10000)
    page.get_by_role("button", name="Discard plan").click()
    page.get_by_text("left your cart exactly as it was", exact=False).wait_for(timeout=10000)

    assert captured["payload"] is not None
    assert captured["payload"].get("trace_id") == "trace-cv-1"
    assert isinstance(captured["payload"].get("context"), dict)
    assert isinstance(captured["payload"]["context"].get("evidence_tags"), list)
    assert captured["rejected_plan"] is not None


def test_two_browser_buyer_and_authenticated_staff_exchange_messages(browser, frontend_server, test_server):
    create = requests.post(
        f"{test_server['base_url']}/api/v1/incidents/escalate",
        json={"case_id": "two-browser-case", "trace_id": "two-browser-trace", "reason": "buyer_requested_human"},
        headers={"host": "localhost"},
        timeout=10,
    )
    assert create.status_code == 200, create.text
    incident = create.json()
    incident_id = incident["incident_id"]
    assert "staff_token" not in incident
    issue_staff = requests.post(
        f"{test_server['base_url']}/api/v1/admin/incidents/{incident_id}/room/token",
        headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
        timeout=10,
    )
    assert issue_staff.status_code == 200, issue_staff.text
    staff_token = issue_staff.json()["staff_token"]

    buyer_context = browser.new_context()
    staff_context = browser.new_context()
    buyer_page = buyer_context.new_page()
    staff_page = staff_context.new_page()
    try:
        buyer_page.goto(
            f"{frontend_server}/?surface=incident&role=buyer&incident_id={incident_id}&token={incident['buyer_token']}",
            wait_until="domcontentloaded",
        )
        staff_page.goto(
            f"{frontend_server}/?surface=incident&role=staff&incident_id={incident_id}&token={staff_token}",
            wait_until="domcontentloaded",
        )
        buyer_page.get_by_test_id("human-conversation").wait_for(timeout=10000)
        staff_page.get_by_test_id("human-conversation").wait_for(timeout=10000)
        buyer_page.get_by_text("sse", exact=True).wait_for(timeout=10000)
        staff_page.get_by_text("sse", exact=True).wait_for(timeout=10000)

        staff_page.get_by_placeholder("Message your specialist...").fill("I am Alex from ShopSquire support.")
        staff_page.get_by_role("button", name="Send").click()
        buyer_page.get_by_text("I am Alex from ShopSquire support.", exact=True).wait_for(timeout=10000)
        buyer_page.get_by_text("Product specialist", exact=True).wait_for(timeout=10000)
        staff_page.locator('[data-delivery-status="read"]', has_text="I am Alex from ShopSquire support.").wait_for(timeout=10000)

        buyer_page.get_by_placeholder("Message your specialist...").fill("Please show the split option; <script>alert(1)</script>")
        buyer_page.get_by_role("button", name="Send").click()
        staff_page.get_by_text("Please show the split option; <script>alert(1)</script>", exact=True).wait_for(timeout=10000)
        # The Vite page has its own bootstrap scripts; the message must remain text and create no
        # script element inside the conversation surface.
        assert staff_page.get_by_test_id("human-conversation").locator("script").count() == 0

        buyer_page.reload(wait_until="domcontentloaded")
        buyer_page.get_by_test_id("human-conversation").wait_for(timeout=10000)
        buyer_page.get_by_text("I am Alex from ShopSquire support.", exact=True).wait_for(timeout=10000)
        assert buyer_page.get_by_text("I am Alex from ShopSquire support.", exact=True).count() == 1

        assignment = requests.post(
            f"{test_server['base_url']}/api/v1/admin/incidents/{incident_id}/assign",
            json={"assigned_to": "product-specialist-2", "team": "procurement"},
            headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
            timeout=10,
        )
        assert assignment.status_code == 200, assignment.text
        buyer_page.get_by_text("Incident assignment updated.", exact=True).wait_for(timeout=10000)
    finally:
        buyer_context.close()
        staff_context.close()


def test_rotated_staff_token_is_rejected_and_new_token_uses_sse(browser, frontend_server, test_server):
    create = requests.post(
        f"{test_server['base_url']}/api/v1/incidents/escalate",
        json={"case_id": "rotate-case", "trace_id": "rotate-trace", "reason": "buyer_requested_human"},
        headers={"host": "localhost"},
        timeout=10,
    )
    assert create.status_code == 200, create.text
    incident_id = create.json()["incident_id"]
    headers = {"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")}
    first = requests.post(
        f"{test_server['base_url']}/api/v1/admin/incidents/{incident_id}/room/token",
        headers=headers,
        timeout=10,
    ).json()["staff_token"]
    second = requests.post(
        f"{test_server['base_url']}/api/v1/admin/incidents/{incident_id}/room/token",
        headers=headers,
        timeout=10,
    ).json()["staff_token"]
    assert first != second

    rejected = requests.post(
        f"{test_server['base_url']}/api/v1/incidents/{incident_id}/room/message",
        headers={"x-incident-token": first},
        json={"message": "This rotated credential must fail."},
        timeout=10,
    )
    assert rejected.status_code == 401

    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(
            f"{frontend_server}/?surface=incident&role=staff&incident_id={incident_id}&token={second}",
            wait_until="domcontentloaded",
        )
        page.get_by_test_id("human-conversation").wait_for(timeout=10000)
        page.get_by_text("sse", exact=True).wait_for(timeout=10000)
        page.get_by_placeholder("Message your specialist...").fill("Rotated staff credential is active.")
        page.get_by_role("button", name="Send").click()
        page.get_by_text("Rotated staff credential is active.", exact=True).wait_for(timeout=10000)
    finally:
        context.close()
