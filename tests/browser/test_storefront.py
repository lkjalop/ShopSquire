import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SKIP_PLAYWRIGHT", "1") == "1", reason="Playwright not configured in local CI")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8080")


def test_browse_to_checkout(page):
    page.goto(f"{BASE_URL}/ui/storefront")
    page.click(".detail")
    page.click(".add-to-cart")
    page.goto(f"{BASE_URL}/ui/checkout")
    page.click("button:has-text('Place Order')")
    assert page.locator("#form-error").is_visible()
