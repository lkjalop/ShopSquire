"""Rendered proof for the deterministic eight-buyer shadow-allocation scenario."""
from __future__ import annotations

import os
import json

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_BROWSER_TESTS", "0").strip().lower() not in {"1", "true", "yes"},
    reason="requires running backend and admin frontend",
)


def test_eight_buyer_pressure_wave_and_partial_recovery_are_visible():
    from playwright.sync_api import sync_playwright

    admin = os.getenv("LIVE_ADMIN_URL", "http://127.0.0.1:3000").rstrip("/")
    api_key = os.getenv("SHOPSQUIRE_API_KEY") or os.getenv("OWNER_API_KEY") or "local-owner-key"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_init_script(
            "sessionStorage.setItem('shopsquire_admin_api_key', " + json.dumps(api_key) + ");"
        )
        page = context.new_page()
        page.goto(
            f"{admin}/?tab=procurement&allocation_sku=SIM-RGAM-0007",
            wait_until="networkidle", timeout=60_000,
        )
        workbench = page.get_by_test_id("allocation-workbench")
        workbench.wait_for(state="visible", timeout=30_000)
        assert workbench.get_by_text("Shadow allocation").is_visible()
        assert workbench.get_by_text("80", exact=True).first.is_visible()
        assert workbench.get_by_text("53", exact=True).first.is_visible()
        assert workbench.get_by_text("27", exact=True).first.is_visible()
        assert workbench.get_by_text("Supplier confirmed", exact=True).is_visible()
        assert workbench.get_by_text("18", exact=True).first.is_visible()
        assert workbench.get_by_text("Supplier unresolved", exact=True).is_visible()
        assert workbench.get_by_text("9", exact=True).first.is_visible()
        assert workbench.get_by_test_id("allocation-demand-row").count() == 8
        batch = workbench.get_by_test_id("allocation-sourcing-batch")
        workbench.locator("summary").click()
        assert batch.count() == 1
        assert "3 anonymized child demand" in batch.inner_text()
        wave = workbench.get_by_test_id("allocation-sourcing-wave")
        assert wave.count() == 1
        assert "Estimate only" in wave.inner_text()
        assert "no RFQ, PO, shipment or payment executed" in wave.inner_text()
        recovery = workbench.get_by_test_id("allocation-recovery-options")
        assert recovery.is_visible()
        assert recovery.get_by_test_id("allocation-alternative-supplier").count() >= 1
        assert "availability unknown" in recovery.inner_text()
        assert "confirmation required" in recovery.inner_text()
        assert "unconfirmed supply presented as available" in recovery.inner_text()
        assert "no supplier contact or order executed" in recovery.inner_text()
        browser.close()
