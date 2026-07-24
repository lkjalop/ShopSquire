from types import SimpleNamespace

from src.app.services import market_projection


def test_operator_projection_keeps_demo_wholesale_unapproved(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.catalog_read_model.get_variant",
        lambda *a, **k: SimpleNamespace(price_cents=200_000, currency="AUD"))
    monkeypatch.setattr(
        "src.app.services.supplier_catalog.best_supplier_cost",
        lambda *a, **k: {
            "unit_cost_cents": 150_000, "cost_basis": "seeded_wholesale_estimate",
            "simulation_only": True,
        })
    monkeypatch.setattr(
        market_projection, "projections",
        lambda *a, **k: {"SKU-1": {"units_per_day": 2.0}})
    out = market_projection.operator_product_projection(
        object(), sku="SKU-1", tenant_id="tenant-a")
    assert out["gross_margin_pct"] == 0.25
    assert out["projected_profit_30d_cents"] == 3_000_000
    assert out["discount_headroom_cents"] is None
    assert out["discount_authorized"] is False
    assert out["simulation_only"] is True


def test_product_projection_endpoint_requires_operator_auth():
    from fastapi.testclient import TestClient
    from src.app.main import create_app

    response = TestClient(create_app()).get(
        "/api/v1/admin/bi/product-projection", params={"sku": "SKU-1"})
    assert response.status_code in {401, 403}
