import os
import pytest
from playwright.sync_api import expect, Page

FRONTEND_URL = os.getenv("E2E_FRONTEND_URL")

pytestmark = pytest.mark.skipif(not FRONTEND_URL, reason="E2E_FRONTEND_URL not set")


def test_trace_panel_opens(page: Page):
    page.goto(FRONTEND_URL)
    chat_btn = page.get_by_title("Open assistant")
    expect(chat_btn).to_be_visible()
    chat_btn.click()

    trace_btn = page.get_by_title("Decision & Security Trace")
    expect(trace_btn).to_be_visible()
    trace_btn.click()

    panel = page.get_by_text("Decision & Security Trace")
    expect(panel).to_be_visible()
    expect(page.get_by_text("Trace Log")).to_be_visible()
