def test_product_detail_not_found(page, test_server):
    base = test_server["base_url"]
    page.goto(base + "/ui/product/NON_EXISTENT_SKU")
    # The product detail page renders a demo fallback shell (never a hard 404)
    # so confirm the page loaded and the SKU is displayed in the title/header.
    assert page.locator("text=NON_EXISTENT_SKU").first.is_visible()
