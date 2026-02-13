import os

from playwright.sync_api import expect, Page


BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8080")


def test_add_to_cart_from_product_detail(page: Page):
    page.goto(f"{BASE_URL}/ui/storefront")
    page.locator(".detail").first.click()
    expect(page).to_have_url(f"{BASE_URL}/ui/product/E2E-001")
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


def test_checkout_validation(page: Page):
    page.goto(f"{BASE_URL}/ui/checkout")
    page.locator("button:has-text('Place Order')").click()
    expect(page.locator("#form-error")).to_be_visible()
