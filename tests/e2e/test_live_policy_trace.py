"""Opt-in browser proof for a V2 policy answer and its accountability trace."""
from __future__ import annotations

import os
import re

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_BROWSER_TESTS", "0").strip().lower() not in {"1", "true", "yes"},
    reason="requires the running demo stack",
)


def test_policy_question_uses_typed_chat_and_projects_authority_boundaries():
    from playwright.sync_api import sync_playwright

    base_url = os.getenv("LIVE_SHOPPER_URL", "http://localhost:5173").rstrip("/")
    calls: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on(
            "request",
            lambda request: calls.append(request.url)
            if any(path in request.url for path in ("/chat/stream", "/chat/query", "/orchestrate"))
            else None,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text) if message.type == "error" else None,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
        page.get_by_text("Ask Me!", exact=True).click()
        composer = page.get_by_placeholder("Type your message...")
        composer.fill("What is your returns policy?")
        composer.press("Enter")
        page.get_by_text("30-day returns on unopened items", exact=False).wait_for(timeout=45_000)

        policy_answer = page.get_by_text(
            "30-day returns on unopened items", exact=False,
        ).last
        answer_text = policy_answer.inner_text()
        assert "Widen a little" not in answer_text
        assert "Prioritize interactive performance" not in answer_text
        assert len([url for url in calls if "/chat/stream" in url]) == 1
        assert not any("/orchestrate" in url or "/chat/query" in url for url in calls)

        page.get_by_role("button", name="Decision Trace").click()
        modal = page.get_by_test_id("decision-trace-modal")
        trace_id = modal.get_attribute("data-trace-id")
        assert trace_id

        modal.get_by_role("button", name=re.compile(r"^Show empty panels")).click()
        tabs = [
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
        for section_name, tab_name in tabs:
            modal = page.get_by_test_id("decision-trace-modal")
            modal.get_by_role(
                "button",
                name=re.compile(rf"^{re.escape(section_name)}\b"),
            ).click()
            modal.get_by_role("tab", name=re.compile(rf"^{re.escape(tab_name)}\b")).click()
            page.wait_for_timeout(200)
            assert modal.get_attribute("data-trace-id") == trace_id
            assert "Failed to load" not in modal.inner_text()

        modal.get_by_role("button", name="Decision", exact=True).click()
        modal.get_by_role("tab", name="Execution", exact=True).click()
        execution = modal.inner_text()
        assert "Models propose" in execution
        assert "Platform gates authorize" in execution
        modal.get_by_role("button", name="Reasoning", exact=True).click()
        modal.get_by_role("tab", name="Intent", exact=True).click()
        assert "lane: policy question" in modal.inner_text().lower()
        assert not console_errors
        assert not page_errors
        browser.close()
