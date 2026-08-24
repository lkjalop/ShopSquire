"""Opt-in browser proof for an exact cart-line amendment.

Run against the production-shaped demo stack with RUN_LIVE_BROWSER_TESTS=1.
The proof deliberately begins with an exact SKU already in the cart: workload
fit must be adjudicated elsewhere and cannot be invented to unlock commerce.
"""
from __future__ import annotations

import os
import json
import re
import uuid

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_BROWSER_TESTS", "0").strip().lower() not in {"1", "true", "yes"},
    reason="requires the running demo stack",
)


def test_exact_cart_line_amendment_requires_delivery_reconfirmation():
    from playwright.sync_api import sync_playwright

    base_url = os.getenv("LIVE_SHOPPER_URL", "http://localhost:5173").rstrip("/")
    api_key = os.getenv("VITE_API_KEY", "local-merchant-key")
    uid = f"e2e-python-procurement-{uuid.uuid4().hex}"
    console_errors: list[str] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(
            f"sessionStorage.setItem('uid', {json.dumps(uid)})"
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        page.get_by_text("Ask Me!", exact=True).click()
        composer = page.get_by_placeholder("Type your message...")
        composer.fill("clear my cart")
        composer.press("Enter")
        page.get_by_text(
            re.compile(r"cart is (?:already )?empty|cleared your cart|cart has been cleared", re.I)
        ).last.wait_for(timeout=30_000)

        response = page.request.post(
            f"{base_url}/api/v1/cart/items",
            headers={"x-api-key": api_key},
            data={"uid": uid, "sku": "RGAM-0007", "quantity": 10},
        )
        assert response.ok, response.text()

        composer.fill("increase the total units by another 5")
        composer.press("Enter")
        apply_change = page.get_by_role(
            "button", name=re.compile(r"Apply change|Confirm.*apply to cart", re.I)
        ).first
        apply_change.wait_for(timeout=75_000)
        apply_change.click()

        quantity = page.locator('[data-testid^="qty-"]').first
        quantity.wait_for(timeout=20_000)
        assert quantity.inner_text().strip() == "15"
        assert page.locator('[data-testid^="qty-"]').count() == 1
        assert page.get_by_text(
            re.compile(r"review and (?:re)?confirm the (?:revised|updated) delivery plan", re.I)
        ).last.is_visible()
        assert page.get_by_text(re.compile(r"RFQ.*sent", re.I)).count() == 0
        assert not console_errors
        assert not page_errors
        browser.close()
