import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv("SKIP_PLAYWRIGHT", "1") == "1", reason="Playwright not configured in local CI")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8080")


def test_admin_decisions_view(page):
    api_key = os.getenv("OWNER_API_KEY", "local-owner-key")
    page.set_extra_http_headers({"x-api-key": api_key})
    page.goto(f"{BASE_URL}/admin/analytics")
    # Admin analytics page should render in either fallback or built UI
    page.wait_for_selector("text=Admin Analytics")
    text = page.text_content("body") or ""
    assert "Admin Analytics" in text
