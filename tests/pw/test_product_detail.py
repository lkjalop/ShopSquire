def test_product_detail_not_found(page, test_server):
    base = test_server["base_url"]
    page.goto(base + "/ui/product/NON_EXISTENT_SKU")
    # Expect a simple not-found message
    assert page.locator("text=Product not found").is_visible()
