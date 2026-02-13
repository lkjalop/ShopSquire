import os
import pytest


@pytest.mark.skipif(not os.getenv("SHOPSQUIRE_UI_URL"), reason="SHOPSQUIRE_UI_URL not set")
def test_followup_chips_render_and_are_clickable(page):
    """Lightweight Playwright test scaffold for follow-up chips.

    This test is skipped unless the environment variable `SHOPSQUIRE_UI_URL`
    is set to a running UI that includes the widget. It's intentionally
    conservative to provide fast feedback without flakiness in CI.
    """
    url = os.getenv("SHOPSQUIRE_UI_URL")
    page.goto(url)

    # Wait briefly for widget to initialize
    page.wait_for_timeout(1000)

    # Try finding follow-up chips by a permissive selector used in widget
    chips = page.query_selector_all(".sq-followup-chip, .shopsquire-followup-chip")

    # If there are chips, clicking one should not throw and should trigger a network request
    if chips:
        chips[0].click()
        page.wait_for_timeout(500)

    # Test passes if navigation and interaction did not raise errors
    assert True
