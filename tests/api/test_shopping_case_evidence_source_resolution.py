from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base
from src.app.routers.shopping_cases import router


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    return TestClient(app)


def _case(client: TestClient) -> str:
    response = client.post("/api/v1/shopping-cases/interpretations", json={
        "uid": "buyer-link",
        "retained_purpose": "I need to simulate a PLC-controlled factory and cyberattacks against the OT network.",
    })
    assert response.status_code == 200
    return response.json()["case_id"]


def test_url_resolution_is_case_bound_zero_network_until_authorized():
    client = _client()
    case_id = _case(client)
    response = client.post(
        f"/api/v1/shopping-cases/{case_id}/evidence-source-resolutions",
        json={
            "uid": "buyer-link",
            "source_url": "https://docs.factoryio.com/manual/system-requirements/",
            "research_authorized": False,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution"]["status"] == "resolved"
    assert payload["resolution"]["selected_source_id"] == "factory_io_official_docs"
    assert payload["research_status"] == "not_authorized"
    assert payload["provider_accounting"] == {"external_calls": 0, "paid_calls": 0}
    assert payload["cart_mutation"] == "not_authorized"


def test_authorized_url_fetches_reviewed_canonical_and_reranks_same_case(monkeypatch):
    client = _client()
    case_id = _case(client)
    calls = []

    def fake_research(purpose, **kwargs):
        calls.append((purpose, kwargs))
        return {
            "claims": [{
                "claim_id": "official-factory-ram", "attribute": "ram_gb",
                "operator": ">=", "value": 32, "unit": "GB",
                "requirement_class": "recommended", "authority_status": "verified_official",
                "freshness_status": "fresh", "source_id": "factory_io_official_docs",
            }],
            "context_claims": [], "unresolved": [], "receipts": [],
            "evidence_ladder": [], "evidence_outcome": "product_requirements",
            "provider_accounting": {
                "external_calls": 1, "discovery_calls": 0,
                "official_origin_fetches": 1, "cache_hits": 0, "paid_calls": 0,
            },
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        fake_research,
    )
    response = client.post(
        f"/api/v1/shopping-cases/{case_id}/evidence-source-resolutions",
        json={
            "uid": "buyer-link",
            "source_url": "https://docs.factoryio.com/manual/system-requirements/",
            "research_authorized": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["case_id"] == case_id
    assert payload["research_status"] == "completed"
    assert payload["evidence_outcome"] == "product_requirements"
    assert payload["provider_accounting"]["official_origin_fetches"] == 1
    assert payload["provider_accounting"]["paid_calls"] == 0
    assert payload["product_shelves"]["schema_version"] == "product-shelves-v1"
    assert calls[0][1]["search_url_template"] == ""
    assert [row["source_id"] for row in calls[0][1]["sources"]] == ["factory_io_official_docs"]


def test_vendor_ambiguity_and_unrelated_same_domain_page_never_dispatch(monkeypatch):
    client = _client()
    case_id = _case(client)
    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )
    ambiguous = client.post(
        f"/api/v1/shopping-cases/{case_id}/evidence-source-resolutions",
        json={"uid": "buyer-link", "vendor_name": "Autodesk", "research_authorized": True},
    ).json()
    assert ambiguous["resolution"]["status"] == "ambiguous"
    assert len(ambiguous["resolution"]["candidates"]) == 2
    unrelated = client.post(
        f"/api/v1/shopping-cases/{case_id}/evidence-source-resolutions",
        json={
            "uid": "buyer-link", "source_url": "https://www.autodesk.com/company/news",
            "research_authorized": True,
        },
    ).json()
    assert unrelated["resolution"]["status"] == "not_enrolled"
    assert unrelated["provider_accounting"]["external_calls"] == 0
