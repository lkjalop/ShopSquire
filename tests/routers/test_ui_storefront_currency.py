from src.app.routers import ui_storefront


def test_storefront_excludes_unconverted_currency_rows(monkeypatch):
    monkeypatch.setattr(ui_storefront, "_store_currency", lambda: "AUD")
    monkeypatch.setattr(
        ui_storefront,
        "_load_products_from_db",
        lambda: [
            {"sku": "AUD-1", "currency": "AUD", "price": 1200},
            {"sku": "USD-1", "currency": "USD", "price": 800},
            {"sku": "UNKNOWN", "currency": None, "price": 700},
        ],
    )
    assert [item["sku"] for item in ui_storefront._get_products()] == ["AUD-1"]


def test_product_deep_link_obeys_store_currency(monkeypatch):
    monkeypatch.setattr(ui_storefront, "_store_currency", lambda: "AUD")
    monkeypatch.setattr(
        ui_storefront,
        "_load_product_by_sku_from_db",
        lambda sku: {"sku": sku, "currency": "USD", "price": 800},
    )
    monkeypatch.setattr(ui_storefront, "_get_products", lambda: [])
    assert ui_storefront._find_product_by_sku("USD-1") is None
