def test_decision_trace_modal_and_trace_api(page, test_server):
    base = test_server["base_url"]
    # Open a known product page
    page.goto(base + "/ui/product/XPS13PLUS")
    # Wait for global decision gear and click
    page.wait_for_selector("[data-test='decision-gear']")
    page.locator("[data-test='decision-gear']").click()
    # Wait for modal to become visible
    page.wait_for_selector("#decision-modal", state="visible", timeout=5000)
    # Scope inside modal and assert Model Selection present
    model_text = page.evaluate("() => document.querySelector('#decision-modal').innerText")
    assert 'Model Selection' in model_text or 'Decision Trace' in model_text

    # Verify decision trace API returns 404 for missing traces (no demo stub)
    headers = { 'x-api-key': 'local-merchant-key' }
    trace_id = 'demo-trace-1'
    r = page.request.get(base + f"/api/v1/decisions/{trace_id}", headers=headers)
    assert r.status == 404
