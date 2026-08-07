from types import SimpleNamespace

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


def test_canonical_fit_explanation_wins_over_independent_reranking():
    state = {
        "last_product_explanation": {
            "sku": "LAP-2",
            "workload_summary": "Blender CGI rendering",
            "coverage_status": "partial",
            "fit_ledger": [{
                "attribute": "gpu_vram_gb",
                "required": [[">=", 8]],
                "observed": 24,
                "verdict": "meets",
            }],
        }
    }

    explanation = recommendation_explain._canonical_fit_explanation(state, "LAP-2")

    assert explanation is not None
    assert explanation["workload_summary"] == "Blender CGI rendering"
    assert explanation["fit_ledger"][0]["observed"] == 24
    assert recommendation_explain._canonical_fit_explanation(state, "OTHER") is None


def test_canonical_fit_explanation_is_resolved_from_exact_trace(monkeypatch):
    canonical = {
        "sku": "LAP-TRACE",
        "workload_summary": "Mechanical maintenance simulation",
        "coverage_status": "bounded",
        "fit_ledger": [{
            "attribute": "ram_gb",
            "required": [[">=", 32]],
            "observed": 64,
            "verdict": "meets",
        }],
    }
    monkeypatch.setattr(
        recommendation_explain,
        "get_cached_trace_events",
        lambda trace_id: [{
            "trace_id": trace_id,
            "payload": {
                "right_panel_contract": {"explanation": canonical},
            },
        }],
    )
    monkeypatch.setattr(
        RecommendationService,
        "retrieve_candidates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("trace-local explanation must avoid independent reranking")
        ),
    )

    response = TestClient(create_app()).get(
        "/api/v1/recommend/why_product",
        params={
            "uid": "explain-trace",
            "sku": "LAP-TRACE",
            "trace_id": "trace-fit-ledger",
        },
        headers={
            "X-Tenant-Id": "tenant-a",
            "X-API-Key": "local-owner-key",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["trace_id"] == "trace-fit-ledger"
    assert response.json()["explanation"] == canonical
