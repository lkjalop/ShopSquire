import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SKIP_PLAYWRIGHT", "1") == "1", reason="Playwright not configured in local CI")



def test_browse_to_checkout(page, browser_test_server):
    page.goto(f"{browser_test_server['base_url']}/ui/storefront")
    page.click(".detail")
    page.click(".add-to-cart")
    page.goto(f"{browser_test_server['base_url']}/ui/checkout")
    page.click("button:has-text('Place Order')")
    assert page.locator("#form-error").is_visible()
