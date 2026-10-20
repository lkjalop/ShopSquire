import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SKIP_PLAYWRIGHT", "1") == "1", reason="Playwright not configured in local CI")



def test_browse_to_checkout_shows_provider_unavailable(page, browser_test_server):
    commercial_requests = []
    page.on('request', lambda request: commercial_requests.append(request.url)
            if request.method == 'POST' and ('/payments/' in request.url or '/orders/' in request.url) else None)
    page.goto(f"{browser_test_server['base_url']}/ui/storefront")
    page.click(".detail")
    page.click(".add-to-cart")
    page.goto(f"{browser_test_server['base_url']}/ui/checkout")
    assert page.locator("#submit-btn").is_disabled()
    assert page.locator("#btn-label").inner_text() == "Payment unavailable"
    assert commercial_requests == []
