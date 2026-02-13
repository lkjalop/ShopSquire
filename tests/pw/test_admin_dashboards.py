import os
import pytest


@pytest.mark.skipif(os.getenv("DISABLE_PLAYWRIGHT_TESTS", "0") in ("1", "true", "yes"), reason="Playwright disabled by env")
def test_admin_ragas_dashboards_links_present(page, test_server):
    base = os.getenv("PLAYWRIGHT_BASE_URL") or test_server["base_url"]
    api_key = os.getenv("OWNER_API_KEY", "local-owner-key")
    page.set_extra_http_headers({"x-api-key": api_key})
    # Admin analytics page lists professional dashboards
    page.goto(f"{base}/admin/analytics")
    # Look for RAGAS dashboard card mention
    text = page.text_content("body") or ""
    assert ("RAGAS Over Time" in text) or ("Grafana" in text)
