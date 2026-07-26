from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.routers import recommendation_explain
from src.app.services.recommendations import RecommendationService


def test_why_product_falls_back_to_tenant_catalog_without_inventing_rank_factors(
    monkeypatch,
):
    monkeypatch.setattr(
        RecommendationService,
        "retrieve_candidates",
        lambda self, query, limit=60: [],
    )
    monkeypatch.setattr(
        recommendation_explain,
        "get_variant",
        lambda db, sku, tenant_id: SimpleNamespace(
            sku=sku,
            title="Verified Creator Laptop",
        ),
    )
    response = TestClient(create_app()).get(
        "/api/v1/recommend/why_product",
        params={
            "uid": "explain-catalog-fallback",
            "sku": "LAP-VERIFIED",
            "trace_id": "trace-catalog-fallback",
        },
        headers={
            "X-Tenant-Id": "tenant-a",
            "X-API-Key": "local-owner-key",
        },
    )

    assert response.status_code == 200, response.text
    explanation = response.json()["explanation"]
    assert explanation["sku"] == "LAP-VERIFIED"
    assert explanation["evidence_status"] == "catalog_only"
    assert explanation["positive_factors"] == []
    assert "detailed ranking factors were not retained" in explanation["reason_summary"]
