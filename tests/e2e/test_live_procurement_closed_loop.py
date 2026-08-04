"""Opt-in browser proof for recommendation -> RFQ -> amendment -> redraft.

Run against the demo stack with RUN_LIVE_BROWSER_TESTS=1. This is intentionally
not part of hermetic CI: it proves the real Vite/FastAPI/Ollama integration.
"""
from __future__ import annotations

import os
import re

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

        # Use a satisfiable office workload for the execution proof. Capability/no-fit behavior
        # for game development is tested separately; a closed-loop test must not purchase a
        # nearest-fit machine that failed the workload floor merely to reach procurement.
        composer.fill("I need 100 business laptops for office work with a total budget of AUD 200000")
        composer.press("Enter")
        add = page.get_by_role("button", name="Add", exact=True).first
        per_item = page.get_by_role("button", name="Per item", exact=True)
        add.or_(per_item).wait_for(timeout=75_000)
        if per_item.is_visible():
            per_item.click()
        add.wait_for(timeout=75_000)
        add.click()
        page.get_by_text("Delivery plan", exact=False).first.wait_for(timeout=20_000)
        assert page.locator('[data-testid^="qty-"]').first.inner_text() == "100"

        page.get_by_role("button", name="Confirm delivery plan", exact=True).click()
        page.get_by_test_id("cart-sourcing-note").wait_for(timeout=30_000)
        page.get_by_role("button", name="Decision Trace").click()
        page.get_by_role("button", name=re.compile(r"^Commercial Journey\b")).click()
        page.get_by_role("tab", name="Procurement", exact=False).click()
        page.get_by_text("Drafted supplier RFQ", exact=False).first.wait_for(timeout=30_000)
        modal = page.get_by_test_id("decision-trace-modal")
        original_trace_id = modal.get_attribute("data-trace-id")
        before = modal.inner_text()
        assert original_trace_id
        assert "Preferred channel" in before
        assert "Ordering terms" in before
        initial_shortfall_match = re.search(r"(\d+) supplier-shortfall", before)
        assert initial_shortfall_match, before
        initial_shortfall = int(initial_shortfall_match.group(1))

        # Every trace projection must remain navigable on the same immutable trace. Individual
        # tabs may truthfully report no activity, but none may crash, detach, or replace identity.
        trace_tabs = [
            ("Decision", "Events"), ("Decision", "Execution"), ("Decision", "Summary"),
            ("Reasoning", "Why"), ("Reasoning", "Intent"),
            ("Reasoning", "Memory"), ("Reasoning", "Complexity"),
            ("Evidence & Risk", "Evidence"), ("Evidence & Risk", "Multimodal"),
            ("Evidence & Risk", "Security"),
            ("Commercial Journey", "Market Intelligence"),
            ("Commercial Journey", "Procurement"),
            ("Advanced technical details", "Audit Trail"),
            ("Advanced technical details", "Raw"),
        ]
        for section_name, tab_name in trace_tabs:
            # Procurement and Evidence append a status badge/count to their accessible name.
            # Reacquire the modal because asynchronous trace projections can refresh its DOM.
            modal = page.get_by_test_id("decision-trace-modal")
            modal.get_by_role(
                "button",
                name=re.compile(rf"^{re.escape(section_name)}\b"),
            ).click()
            leaf_tab = modal.get_by_role(
                "tab",
                name=re.compile(rf"^{re.escape(tab_name)}\b"),
            )
            if not leaf_tab.count():
                modal.get_by_role(
                    "button",
                    name=re.compile(r"^Show empty panels"),
                ).click()
            leaf_tab.click()
            page.wait_for_timeout(300)
            assert modal.get_attribute("data-trace-id") == original_trace_id
            assert "Failed to load" not in modal.inner_text()
        modal.get_by_role("button", name=re.compile(r"^Commercial Journey\b")).click()
        modal.get_by_role("tab", name=re.compile(r"^Procurement\b")).click()

        page.locator('button[title="Close"]').last.click()
        composer.fill("actually make it 80")
        composer.press("Enter")
        apply_change = page.get_by_role(
            "button", name=re.compile(r"Confirm qty|apply to cart", re.I)
        ).first
        apply_change.wait_for(timeout=35_000)
        apply_change.click()
        page.wait_for_function(
            "() => document.querySelector('[data-testid^=qty-]')?.textContent?.trim() === '80'",
            timeout=20_000,
        )

        page.get_by_test_id("split-confirm").click()
        page.wait_for_timeout(4_000)
        page.get_by_role("button", name="Decision Trace").click()
        page.get_by_role("button", name=re.compile(r"^Commercial Journey\b")).click()
        page.get_by_role("tab", name="Procurement", exact=False).click()
        page.get_by_text("Drafted supplier RFQ", exact=False).first.wait_for(timeout=30_000)
        modal = page.get_by_test_id("decision-trace-modal")
        # The RFQ projection and the bitemporal case journey are fetched independently.
        # Wait for both instead of relying on a fixed delay that races a healthy backend.
        modal.get_by_text("state transitions", exact=False).wait_for(timeout=20_000)
        after = modal.inner_text()
        amended_trace_id = modal.get_attribute("data-trace-id")
        assert amended_trace_id
        assert amended_trace_id != original_trace_id
        revised_shortfall_match = re.search(r"(\d+) supplier-shortfall", after)
        assert revised_shortfall_match, after
        assert int(revised_shortfall_match.group(1)) == max(0, initial_shortfall - 20)
        assert "supersed" in after.lower()
        assert "state transitions" in after
        assert not console_errors
        assert not page_errors
        browser.close()
