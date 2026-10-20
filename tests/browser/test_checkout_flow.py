from playwright.sync_api import expect, Page




def test_add_to_cart_from_product_detail(page: Page, browser_test_server):
    page.goto(f"{browser_test_server['base_url']}/ui/storefront")
    page.locator(".detail").first.click()
    expect(page).to_have_url(f"{browser_test_server['base_url']}/ui/product/E2E-001")
    page.evaluate(
        """(async () => {
          const apiBase = window.location.origin;
          const apiKey = 'local-merchant-key';
          await fetch(`${apiBase}/api/v1/cart/clear?uid=guest-user`, { method: 'POST', headers: { 'x-api-key': apiKey } });
          localStorage.setItem('cart_count', '0');
        })()"""
    )
    expect(page.locator(".cart-count")).to_have_text("0")
    expect(page.locator(".add-to-cart")).to_be_visible()
    page.locator(".add-to-cart").click()
    expect(page.locator(".cart-count")).to_have_text("1")


def test_checkout_is_disabled_without_a_payment_provider(page: Page, browser_test_server):
    page.goto(f"{browser_test_server['base_url']}/ui/checkout")
    expect(page.locator('#submit-btn')).to_be_disabled()
    expect(page.locator('#btn-label')).to_have_text('Payment unavailable')


def test_checkout_validation(page: Page, demo_checkout_server):
    commercial_requests = []
    page.on('request', lambda request: commercial_requests.append(request.url)
            if request.method == 'POST' and ('/payments/' in request.url or '/orders/' in request.url) else None)
    page.goto(f"{demo_checkout_server['base_url']}/ui/checkout")
    page.locator("button:has-text('Place Order')").click()
    expect(page.locator("#form-error")).to_have_text('Please fill in all required fields.')
    assert commercial_requests == []
