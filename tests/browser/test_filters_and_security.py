import os
import pytest
from playwright.sync_api import expect, Page

FRONTEND_URL = os.getenv("E2E_FRONTEND_URL")

pytestmark = pytest.mark.skipif(not FRONTEND_URL, reason="E2E_FRONTEND_URL not set")


def _open_chat(page: Page):
    page.goto(FRONTEND_URL)
    page.get_by_title("Open assistant").click()


def test_price_spec_query_not_security_blocked(page: Page):
    _open_chat(page)
    input_box = page.get_by_placeholder("Ask me anything about products, orders, or help...")
    input_box.fill("show me products between 1400 and 1900 with 32 gb ram")
    input_box.press("Enter")
    # Should not show security review message for a normal query
    page.wait_for_timeout(2000)
    expect(page.get_by_text("Request queued for security review.")).to_have_count(0)


def test_pci_query_triggers_security_review(page: Page):
    _open_chat(page)
    input_box = page.get_by_placeholder("Ask me anything about products, orders, or help...")
    input_box.fill("my card is 4242 4242 4242 4242")
    input_box.press("Enter")
    page.wait_for_timeout(2000)
    expect(page.get_by_text("Request queued for security review.")).to_be_visible()
