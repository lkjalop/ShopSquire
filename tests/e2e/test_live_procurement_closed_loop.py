"""Opt-in browser proof for recommendation -> RFQ -> amendment -> redraft.

Run against the demo stack with RUN_LIVE_BROWSER_TESTS=1. This is intentionally
not part of hermetic CI: it proves the real Vite/FastAPI/Ollama integration.
"""
from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_BROWSER_TESTS", "0").strip().lower() not in {"1", "true", "yes"},
    reason="requires the running demo stack",
)


def test_procurement_trace_survives_amendment_and_redrafts():
    from playwright.sync_api import sync_playwright

    base_url = os.getenv("LIVE_SHOPPER_URL", "http://localhost:5173").rstrip("/")
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        page.get_by_text("Ask Me!", exact=True).click()
        composer = page.get_by_placeholder("Type your message...")
        composer.fill("clear my cart")
        composer.press("Enter")
        page.get_by_text("your cart is now empty", exact=False).wait_for(timeout=20_000)

        composer.fill("I need 20 laptops for game development with a total budget of AUD 41000")
        composer.press("Enter")
        page.get_by_text("Top Recommendations", exact=True).wait_for(timeout=45_000)
        page.get_by_text("Top Recommendations", exact=True).locator("xpath=..").get_by_role(
            "button", name="Add", exact=True,
        ).first.click()
        page.get_by_text("Delivery plan", exact=False).first.wait_for(timeout=20_000)
        assert page.locator('[data-testid^="qty-"]').first.inner_text() == "20"

        page.get_by_role("button", name="Confirm delivery plan", exact=True).click()
        page.get_by_test_id("cart-sourcing-note").wait_for(timeout=30_000)
        page.get_by_role("button", name="Decision Trace").click()
        page.get_by_role("button", name="Procurement", exact=False).click()
        page.get_by_text("Drafted supplier RFQ", exact=False).first.wait_for(timeout=30_000)
        modal = page.get_by_test_id("decision-trace-modal")
        original_trace_id = modal.get_attribute("data-trace-id")
        before = modal.inner_text()
        assert original_trace_id
        assert "Preferred channel" in before
        assert "Ordering terms" in before
        assert "Quantity: 5" in before or "5 supplier-shortfall" in before

        page.locator('button[title="Close"]').last.click()
        composer.fill("actually make it 18")
        composer.press("Enter")
        apply_change = page.locator("button").filter(has_text="apply to cart").first
        apply_change.wait_for(timeout=35_000)
        assert page.locator('[data-testid^="qty-"]').first.inner_text() == "20"
        apply_change.click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid^=qty-]')?.textContent?.trim() === '18'",
            timeout=20_000,
        )

        page.get_by_test_id("cart-confirm-updated-plan").click()
        page.wait_for_timeout(4_000)
        page.get_by_role("button", name="Decision Trace").click()
        page.get_by_role("button", name="Procurement", exact=False).click()
        page.get_by_text("Drafted supplier RFQ", exact=False).first.wait_for(timeout=30_000)
        modal = page.get_by_test_id("decision-trace-modal")
        page.wait_for_timeout(2_000)
        after = modal.inner_text()
        assert modal.get_attribute("data-trace-id") == original_trace_id
        assert "Quantity: 3" in after or "3 supplier-shortfall" in after
        assert "prior draft superseded" in after
        assert "state transitions" in after
        assert not console_errors
        assert not page_errors
        browser.close()
