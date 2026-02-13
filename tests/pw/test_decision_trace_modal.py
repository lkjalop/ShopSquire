def test_decision_trace_gear_modal(page, test_server):
    base = test_server["base_url"]
    # Open a known product page
    page.goto(base + "/ui/product/XPS13PLUS")
    # Wait for the product widget and gear icon
    gear = page.locator("[data-test='decision-gear']")
    assert gear.wait_for(state="visible", timeout=5000) is None
    gear.click()
    # Modal should appear with Decision Trace title (scoped to dialog)
    # The widget injects a modal with id `decision-modal` for tests
    modal = page.locator("#decision-modal")
    assert modal.wait_for(state="visible", timeout=5000) is None
    title = modal.locator("text=Decision Trace")
    assert title.is_visible()
    # Within modal, check for the Model Selection section and Selected line
    model_section = modal.locator("text=Model Selection")
    assert model_section.is_visible()
    selected = modal.locator("text=Selected")
    assert selected.is_visible()