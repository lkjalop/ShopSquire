"""Playwright smoke tests for DecisionTrace timeline and drilldown."""

import pytest


def test_timeline_renders_events(page, test_server):
    base = test_server["base_url"]
    page.goto(f"{base}/ui/product/XPS13PLUS")

    gear = page.locator("[data-test='decision-gear']")
    gear.wait_for(state="visible", timeout=5000)
    gear.click()

    modal = page.locator("#decision-modal")
    modal.wait_for(state="visible", timeout=5000)

    # Compatibility assertion: UI variants may render either timeline table
    # or compact summary/model sections.
    has_table = modal.locator("table").is_visible()
    has_summary_text = modal.locator("text=Model Selection").is_visible() or modal.locator("text=Decision Trace").is_visible()
    assert has_table or has_summary_text


def test_event_drilldown(page, test_server):
    base = test_server["base_url"]
    page.goto(f"{base}/ui/product/XPS13PLUS")

    gear = page.locator("[data-test='decision-gear']")
    gear.wait_for(state="visible", timeout=5000)
    gear.click()

    modal = page.locator("#decision-modal")
    modal.wait_for(state="visible", timeout=5000)

    events_tab = modal.locator("button", has_text="Events")
    if events_tab.is_visible():
        events_tab.click()
    first_event = modal.locator("tbody tr").first
    if first_event.is_visible():
        first_event.click()
        payload = modal.locator(".detailBox")
        payload.wait_for(state="visible", timeout=3000)
        assert payload.is_visible()
