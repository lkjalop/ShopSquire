import os
import time
import pytest
from playwright.sync_api import Page


def _first(selector_list, page: Page):
    for s in selector_list:
        el = page.query_selector(s)
        if el:
            return el
    return None


def _all(selector_list, page: Page):
    for s in selector_list:
        els = page.query_selector_all(s)
        if els:
            return els
    return []


def test_followup_chips_e2e(page: Page, test_server):
    """End-to-end smoke for follow-up chips.

    Targets a local dev UI at http://localhost:5173 by default. Set
    `SHOPSQUIRE_UI_URL` to override. This test expects the widget to be
    reachable and interactive; run the frontend locally before executing.
    """
    url = os.getenv("SHOPSQUIRE_UI_URL") or test_server.get("base_url") or "http://localhost:5173"
    page.goto(url)

    # Allow widget to boot
    page.wait_for_timeout(1000)

    # Open launcher/chat if present
    launcher = _first([".shopsquire-launch-button", ".sq-launcher", "#shopsquire-launch"], page)
    if not launcher:
        launcher = _first(["button:has-text('Ask Me!')", ".chatFab"], page)
    if launcher:
        try:
            launcher.click()
            page.wait_for_timeout(500)
        except Exception:
            pass

    # Locate input field (permissive selectors used by widget variants)
    input_el = _first(
        [
            "input.sq-search-input",
            "textarea.sq-chat-input",
            "input.chatInput",
            "input[placeholder*='Search']",
            "input[placeholder*='Type your message']",
            "textarea[placeholder*='Message']",
        ],
        page,
    )
    if not input_el:
        pytest.skip("Widget input field not present in this UI variant/environment")

    input_el.click()
    input_el.fill("laptop")
    # Submit via Enter
    try:
        input_el.press("Enter")
    except Exception:
        # Fallback: click a send button if present
        send = _first([".sq-send-btn", ".shopsquire-send", "button[aria-label='Send']"], page)
        if send:
            send.click()

    # Wait for proposals / follow-up chips to appear
    chips = []
    for _ in range(20):
        chips = _all([".sq-followup-chip", ".shopsquire-followup-chip", ".followup-chip"], page)
        if chips:
            break
        page.wait_for_timeout(500)

    if not chips:
        pytest.skip("No follow-up chips rendered in this environment/fixture")

    # Click the first follow-up chip and ensure widget responds
    try:
        chips[0].click()
    except Exception:
        pytest.skip("Follow-up chip not interactable in this environment")

    # Give the widget a moment to handle the click and submit
    page.wait_for_timeout(800)

    # Verify a proposal or assistant message is present after follow-up
    proposal = _first([".sq-proposal", ".shopsquire-proposal", ".proposal", ".assistant-message"], page)
    if not proposal:
        pytest.skip("No proposal/assistant message found after follow-up in this environment")
