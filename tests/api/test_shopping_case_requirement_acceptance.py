from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.db import get_db
from src.app.models.orm import Base, Product
from src.app.routers.shopping_cases import router
from src.app.services.buyer_requirement_evidence import extract_buyer_requirement_claims


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(router)
    app.state.test_engine = engine

    def db_override():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    return TestClient(app)


def _enrol_local_research(monkeypatch, *, tenant_id: str = "default") -> None:
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", tenant_id)
    monkeypatch.setenv("EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED", "1")


def test_manual_specifications_create_same_case_review_proposal():
    client = _client()
    case_id = "case-manual"
    response = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals/from-text",
        json={
            "uid": "buyer-manual",
            "retained_purpose": "I need a mobile system for an unfamiliar scientific workload.",
            "text": "RAM 32GB minimum\nStorage 1TB NVMe\nWindows 11 Pro recommended",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["case_id"] == case_id
    assert payload["status"] == "pending_review"
    assert {row["attribute"] for row in payload["claims"]} >= {
        "ram_gb", "storage_gb", "storage_type", "operating_system",
    }
    assert all(row["authority_status"] == "unverified" for row in payload["claims"])
    assert payload["cart_mutation"] == "not_authorized"


def test_manual_specifications_abstain_when_no_typed_claim_can_be_extracted():
    client = _client()
    case_id = "case-manual-empty"
    response = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals/from-text",
        json={"uid": "buyer-manual-empty", "text": "make it really good please"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "no_explicit_requirement_claims"


def test_interpretation_is_immediate_case_bound_and_zero_network():
    client = _client()
    response = client.post("/api/v1/shopping-cases/interpretations", json={
        "uid": "buyer-fast-lane",
        "retained_purpose": "I need CAD for very large 3D models and point-cloud work.",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "case-interpretation-v1"
    assert payload["case_id"].startswith("sc-case-")
    assert payload["ambiguity_exploration"]["case_id"] == payload["case_id"]
    assert payload["ambiguity_exploration"]["research_plan_id"].startswith("crp-")
    assert payload["ambiguity_exploration"]["provider_accounting"] == {
        "external_calls": 0, "paid_calls": 0,
    }
    assert payload["product_shelves"]["schema_version"] == "product-shelves-v1"
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["supplier_send"] == "not_authorized"


def test_interpretation_defers_covered_catalog_request_to_normal_chat_lane():
    client = _client()
    response = client.post("/api/v1/shopping-cases/interpretations", json={
        "uid": "buyer-local",
        "retained_purpose": "show me a normal everyday laptop",
    })
    assert response.status_code == 204


def test_accepted_upload_runs_corroboration_in_the_same_interpreted_case(monkeypatch):
    client = _client()
    _enrol_local_research(monkeypatch)
    interpreted = client.post("/api/v1/shopping-cases/interpretations", json={
        "uid": "buyer-same-case",
        "retained_purpose": "Digital-twin simulation of factory equipment and predicting breakdowns",
    }).json()
    case_id = interpreted["case_id"]
    claim = extract_buyer_requirement_claims(
        "RAM 32GB minimum", source_reference="upload-same-case",
    )[0]
    proposal = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals",
        json={
            "uid": "buyer-same-case", "source_reference": "upload-same-case",
            "claims": [claim.model_dump(mode="json")],
        },
    ).json()

    def context_research(*args, **kwargs):
        return {
            "claims": [], "context_claims": [{
                "claim_id": "context-same-case",
                "source_id": "nist_manufacturing_digital_twins",
                "claim_type": "workload_scope", "statement": "context only",
            }],
            "unresolved": [{"source_id": None, "reason": "no_product_requirement_claims"}],
            "receipts": [], "source_ids": ["nist_manufacturing_digital_twins"],
            "provider_accounting": {"external_calls": 2, "paid_calls": 0},
            "evidence_outcome": "context_only",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        context_research,
    )
    accepted = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals/{proposal['proposal_id']}/accept",
        headers={"Idempotency-Key": "same-case-accept-1"},
        json={
            "uid": "buyer-same-case", "expected_proposal_version": 1,
            "accepted_claim_ids": [claim.claim_id], "rejected_claim_ids": [],
            "corrections": [], "research_choice": "research_and_corroborate",
        },
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["case_id"] == case_id
    assert payload["trace_id"] == case_id.removeprefix("sc-")
    assert payload["corroboration"]["case_id"] == case_id
    assert payload["corroboration"]["evidence_outcome"] == "context_only"
    assert payload["provider_accounting"] == {"external_calls": 2, "paid_calls": 0}
    assert payload["product_shelves"]["evidence_status"] == "context_only"
    assert payload["product_shelves"]["context_claim_count"] == 1
    assert payload["product_shelves"]["buyer_accepted_claim_count"] == 1
    assert payload["buyer_claim_reconciliation_status_counts"] == {
        "corroborated": 0, "contradicted": 0,
        "unresolved": 1, "preference_only": 0,
    }
    assert payload["buyer_claim_reconciliation"][0]["status"] == "unresolved"
    assert payload["product_shelves"]["buyer_claim_reconciliation"] == payload[
        "buyer_claim_reconciliation"
    ]


def test_acceptance_is_case_scoped_versioned_idempotent_and_never_mutates_cart():
    client = _client()
    claims = extract_buyer_requirement_claims(
        "RAM 32GB minimum, 64GB recommended. Storage 1TB NVMe. Windows 11 Pro recommended.",
        source_reference="screenshot-55",
    )
    created = client.post(
        "/api/v1/shopping-cases/case-ot/requirement-proposals",
        headers={"X-Tenant-Id": "tenant-a"},
        json={
            "uid": "buyer-1", "retained_purpose": "OT cyber range",
            "source_reference": "screenshot-55",
            "claims": [claim.model_dump(mode="json") for claim in claims],
        },
    )
    assert created.status_code == 201
    proposal = created.json()
    selected = [claim["claim_id"] for claim in proposal["claims"]]
    body = {
        "uid": "buyer-1", "expected_proposal_version": 1,
        "accepted_claim_ids": selected, "rejected_claim_ids": [],
        "corrections": [{
            "claim_id": selected[0], "attribute": "ram_gb", "operator": ">=",
            "value": 48, "unit": "GB", "requirement_class": "minimum",
            "constraint_tier": "preferred",
        }],
        "research_choice": "research_and_corroborate",
    }
    headers = {"X-Tenant-Id": "tenant-a", "Idempotency-Key": "accept-case-ot-1"}
    accepted = client.post(
        f"/api/v1/shopping-cases/case-ot/requirement-proposals/{proposal['proposal_id']}/accept",
        headers=headers, json=body,
    )
    assert accepted.status_code == 200
    payload = accepted.json()
    assert payload["status"] == "accepted_provisional"
    assert payload["accepted_claims"][0]["value"] == 48
    assert payload["accepted_claims"][0]["buyer_corrected"] is True
    assert payload["research_authorized"] is True
    assert payload["qualification_authority"] == "none"
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["provider_accounting"] == {"external_calls": 0, "paid_calls": 0}
    assert payload["evidence_acquisition"]["selected_stage"] == "buyer_upload"
    assert payload["evidence_acquisition"]["paid_calls"] == 0

    replay = client.post(
        f"/api/v1/shopping-cases/case-ot/requirement-proposals/{proposal['proposal_id']}/accept",
        headers=headers, json=body,
    )
    assert replay.status_code == 200
    assert replay.json() == payload


def test_acceptance_rejects_cross_buyer_and_stale_versions():
    client = _client()
    claim = extract_buyer_requirement_claims(
        "RAM 32GB minimum", source_reference="buyer-paste",
    )[0]
    proposal = client.post(
        "/api/v1/shopping-cases/case-1/requirement-proposals",
        json={"uid": "buyer-1", "source_reference": "buyer-paste", "claims": [claim.model_dump(mode="json")]},
    ).json()
    url = f"/api/v1/shopping-cases/case-1/requirement-proposals/{proposal['proposal_id']}/accept"
    body = {
        "uid": "buyer-2", "expected_proposal_version": 1,
        "accepted_claim_ids": [claim.claim_id], "rejected_claim_ids": [],
        "corrections": [], "research_choice": "local_only",
    }
    assert client.post(url, headers={"Idempotency-Key": "cross-buyer-1"}, json=body).status_code == 403

    body["uid"] = "buyer-1"
    body["expected_proposal_version"] = 99
    response = client.post(url, headers={"Idempotency-Key": "stale-version-1"}, json=body)
    assert response.status_code == 409


def test_fulfillment_options_are_proposals_not_cart_or_supplier_actions():
    client = _client()
    claim = extract_buyer_requirement_claims("RAM 32GB minimum", source_reference="upload")[0]
    client.post(
        "/api/v1/shopping-cases/case-bulk/requirement-proposals",
        json={"uid": "buyer-1", "source_reference": "upload", "claims": [claim.model_dump(mode="json")]},
    )
    response = client.post("/api/v1/shopping-cases/case-bulk/fulfillment-options", json={
        "uid": "buyer-1", "requested_quantity": 30, "available_now": 12,
        "known_lead_time_days": 8, "deadline_days": 10,
        "has_next_best": True, "has_architecture_alternative": True,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["supplier_send"] == "not_authorized"
    assert [row["choice_id"] for row in payload["choices"]][:3] == [
        "split_delivery", "wait_preferred", "next_best_now",
    ]


def test_live_research_is_case_scoped_and_never_authorizes_commerce(monkeypatch):
    client = _client()
    _enrol_local_research(monkeypatch)

    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )

    def fixture_research(
        purpose, *, search_url_template, sources, plan_id, hypothesis_ids, **kwargs,
    ):
        assert purpose == "OT cyber range"
        assert "{query}" in search_url_template
        assert sources
        assert plan_id == plan.plan_id
        assert set(hypothesis_ids) == {row.hypothesis_id for row in plan.hypotheses}
        assert kwargs["tenant_id"] == "default"
        assert kwargs["evidence_cache"] is not None
        return {
            "schema_version": "official-workload-research-v1",
            "run_id": "fixture-run", "purpose": purpose,
            "research_plan_id": plan_id, "hypothesis_ids": hypothesis_ids,
            "source_ids": [row["source_id"] for row in sources],
            "claims": [{
                "claim_id": "official-os", "attribute": "operating_system",
                "operator": "one_of", "value": ["Windows 11 Pro"],
                "unit": None, "requirement_class": "minimum",
                "claim_class": "attested", "authority_status": "verified_official",
                "freshness_status": "fresh", "source_id": "microsoft_learn_hyperv",
                "acceptance_status": "accepted_official",
            }],
            "context_claims": [], "unresolved": [], "receipts": [],
            "provider_accounting": {"external_calls": 2, "paid_calls": 0},
            "execution_mode": "deterministic_fixture", "authority_rule": "official only",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        fixture_research,
    )
    response = client.post("/api/v1/shopping-cases/sc-trace-1/research", json={
        "uid": "buyer-1", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["case_id"] == "sc-trace-1"
    assert payload["trace_id"] == "trace-1"
    assert payload["status"] == "research_completed"
    assert payload["research"]["claims"][0]["authority_status"] == "verified_official"
    assert payload["evidence_outcome"] == "product_requirements"
    assert payload["ambiguity_exploration"]["status"] == "researched"
    assert payload["ambiguity_exploration"]["execution"] == "live_official_research_completed"
    assert next(
        row for row in payload["ambiguity_exploration"]["research_obligations"]
        if row["obligation_id"] == "official_requirements"
    )["status"] == "resolved"
    assert payload["cart_mutation"] == "not_authorized"
    assert payload["supplier_send"] == "not_authorized"

    with Session(client.app.state.test_engine) as db:
        db.add(Product(
            sku="WS-EXACT-1", name="Exact mobile workstation",
            price_cents=500_000, currency="AUD", active=True,
        ))
        db.commit()
    proposal = client.post("/api/v1/shopping-cases/sc-trace-1/cart-proposals", json={
        "uid": "buyer-1", "sku": "WS-EXACT-1", "quantity": 30,
    })
    assert proposal.status_code == 200
    planned = proposal.json()
    assert planned["status"] == "confirmation_required"
    assert planned["risk"] == "confirm"
    assert planned["cart_mutation"] == "not_applied"
    assert planned["supplier_send"] == "not_authorized"
    assert planned["ops"][0]["allow_sourcing"] is True


def test_context_only_research_keeps_fit_provisional_and_blocks_silent_repeat(monkeypatch):
    client = _client()
    _enrol_local_research(monkeypatch)
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan(
        "Digital-twin simulation of factory equipment and predicting breakdowns",
    )
    assert plan is not None
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    observed = {"completed": False}
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_trace_has_event",
        lambda db, *, case_id, tenant_id, event_type: observed["completed"],
    )

    def context_research(*args, **kwargs):
        observed["completed"] = True
        return {
            "claims": [],
            "context_claims": [{
                "claim_id": "context-1", "source_id": "nist_manufacturing_digital_twins",
                "claim_type": "workload_scope", "statement": "context only",
            }],
            "unresolved": [{"source_id": None, "reason": "no_product_requirement_claims"}],
            "receipts": [], "source_ids": ["nist_manufacturing_digital_twins"],
            "provider_accounting": {
                "external_calls": 0, "cache_hits": 1, "paid_calls": 0,
            },
            "execution_mode": "evidence_cache",
            "evidence_outcome": "context_only",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        context_research,
    )
    body = {
        "uid": "buyer-context", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    }
    first = client.post("/api/v1/shopping-cases/sc-context-only/research", json=body)
    assert first.status_code == 200
    payload = first.json()
    assert payload["evidence_outcome"] == "context_only"
    assert payload["product_shelves"]["evidence_status"] == "context_only"
    assert payload["ambiguity_exploration"]["status"] == "context_only"
    assert payload["ambiguity_exploration"]["execution"] == "governed_evidence_cache_hit"
    assert payload["ambiguity_exploration"]["decision"] == "provisional_exploration_only"
    obligations = {
        row["obligation_id"]: row["status"]
        for row in payload["ambiguity_exploration"]["research_obligations"]
    }
    assert obligations["official_requirements"] == "resolved"
    assert obligations["exact_product_identity"] == "blocked"

    repeated = client.post("/api/v1/shopping-cases/sc-context-only/research", json=body)
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "research_already_completed"


def test_same_case_corroboration_reconciles_every_buyer_claim_without_promotion(monkeypatch):
    client = _client()
    _enrol_local_research(monkeypatch)
    interpreted = client.post("/api/v1/shopping-cases/interpretations", json={
        "uid": "buyer-reconciliation", "retained_purpose": "OT cyber range",
    }).json()
    case_id = interpreted["case_id"]

    def buyer_claim(
        claim_id, attribute, operator, value, requirement_class="minimum", unit=None,
    ):
        return {
            "claim_id": claim_id, "subject": "buyer_workload_requirement",
            "attribute": attribute, "operator": operator, "value": value, "unit": unit,
            "requirement_class": requirement_class, "constraint_tier": "preferred",
            "condition": None, "source_reference": "buyer-specification",
            "evidence_class": "buyer_supplied", "extraction_confidence": 1.0,
            "authority_status": "unverified", "freshness_status": "unknown",
            "source_excerpt": f"{attribute} {operator} {value}",
        }

    claims = [
        buyer_claim("ram-16", "ram_gb", ">=", 16, unit="GB"),
        buyer_claim("ram-64", "ram_gb", ">=", 64, unit="GB"),
        buyer_claim("os-linux", "operating_system", "=", "Linux"),
        buyer_claim("storage", "storage_gb", ">=", 1024, unit="GB"),
        buyer_claim(
            "vram-preference", "gpu_vram_gb", ">=", 12,
            requirement_class="recommended", unit="GB",
        ),
    ]
    proposal = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals",
        json={
            "uid": "buyer-reconciliation", "source_reference": "buyer-specification",
            "claims": claims,
        },
    ).json()

    def official_research(*args, **kwargs):
        return {
            "claims": [{
                "claim_id": "official-ram-32", "attribute": "ram_gb",
                "operator": ">=", "value": 32, "unit": "GB",
                "requirement_class": "minimum", "authority_status": "verified_official",
                "freshness_status": "fresh", "source_id": "microsoft_learn_hyperv",
            }, {
                "claim_id": "official-windows", "attribute": "operating_system",
                "operator": "one_of", "value": ["Windows 11 Pro"],
                "requirement_class": "minimum", "authority_status": "verified_official",
                "freshness_status": "fresh", "source_id": "microsoft_learn_hyperv",
            }],
            "context_claims": [], "unresolved": [], "receipts": [],
            "source_ids": ["microsoft_learn_hyperv"], "source_execution": [],
            "provider_accounting": {"external_calls": 0, "paid_calls": 0},
            "evidence_outcome": "product_requirements",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        official_research,
    )
    response = client.post(
        f"/api/v1/shopping-cases/{case_id}/requirement-proposals/"
        f"{proposal['proposal_id']}/accept",
        headers={"Idempotency-Key": "reconcile-accepted-claims"},
        json={
            "uid": "buyer-reconciliation", "expected_proposal_version": 1,
            "accepted_claim_ids": [row["claim_id"] for row in claims],
            "rejected_claim_ids": [], "corrections": [],
            "research_choice": "research_and_corroborate",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    statuses = {
        row["buyer_claim_id"]: row["status"]
        for row in payload["buyer_claim_reconciliation"]
    }
    assert statuses == {
        "ram-16": "corroborated", "ram-64": "unresolved",
        "os-linux": "contradicted", "storage": "unresolved",
        "vram-preference": "preference_only",
    }
    assert payload["buyer_claim_reconciliation_status_counts"] == {
        "corroborated": 1, "contradicted": 1,
        "unresolved": 2, "preference_only": 1,
    }
    assert len(payload["accepted_claims"]) == len(claims)
    assert all(row["authority_status"] == "unverified" for row in payload["accepted_claims"])
    assert payload["product_shelves"]["buyer_accepted_claim_count"] == len(claims)
    assert payload["product_shelves"][
        "buyer_claim_reconciliation_status_counts"
    ] == payload["buyer_claim_reconciliation_status_counts"]


def test_research_scope_cannot_be_changed_by_the_browser(monkeypatch):
    client = _client()
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    legacy = client.post("/api/v1/shopping-cases/sc-scope/research", json={
        "uid": "buyer-1", "retained_purpose": "CAD point cloud",
        "workload": "ot_cyber_range",
    })
    assert legacy.status_code == 422

    tampered = client.post("/api/v1/shopping-cases/sc-scope/research", json={
        "uid": "buyer-1", "research_plan_id": "crp-00000000000000000000",
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    })
    assert tampered.status_code == 409
    assert tampered.json()["detail"]["code"] == "case_research_plan_mismatch"


def test_canonical_research_bypasses_unavailable_discovery_but_not_disabled_policy(monkeypatch):
    client = _client()
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    body = {
        "uid": "buyer-proof", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    }

    _enrol_local_research(monkeypatch)
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "0")
    disabled = client.post("/api/v1/shopping-cases/sc-disabled/research", json=body)
    assert disabled.status_code == 503
    assert disabled.json()["detail"]["code"] == "external_research_disabled"

    search_templates = []

    def canonical_research(*args, **kwargs):
        search_templates.append(kwargs["search_url_template"])
        return {
            "claims": [], "context_claims": [], "unresolved": [],
            "receipts": [], "source_ids": [],
            "source_execution": [{
                "origin_selection_mode": "canonical_direct",
                "canonical_fetch_status": "completed",
                "discovery_status": "not_needed", "discovery_result_count": 0,
            }],
            "provider_accounting": {"external_calls": 1, "paid_calls": 0},
            "evidence_outcome": "unresolved",
        }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.research_official_sources",
        canonical_research,
    )
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL")
    not_configured = client.post(
        "/api/v1/shopping-cases/sc-not-configured/research", json=body,
    )
    assert not_configured.status_code == 200
    assert not_configured.json()["research"]["canonical_direct_ready"] is True
    assert not_configured.json()["research"]["discovery_readiness"]["error_code"] == (
        "discovery_endpoint_not_configured"
    )

    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._external_research_runtime_status",
        lambda: {"reachable": False, "last_failure_at": "2026-08-09T02:00:00Z"},
    )
    unreachable = client.post("/api/v1/shopping-cases/sc-unreachable/research", json=body)
    assert unreachable.status_code == 200
    assert unreachable.json()["research"]["discovery_readiness"]["error_code"] == (
        "discovery_endpoint_unreachable"
    )

    monkeypatch.setattr(
        "src.app.routers.shopping_cases._external_research_runtime_status",
        lambda: {
            "reachable": True, "degraded": True,
            "last_success_at": "2026-08-09T01:00:00Z",
            "last_failure_code": "http_503",
        },
    )
    degraded = client.post("/api/v1/shopping-cases/sc-degraded/research", json=body)
    assert degraded.status_code == 200
    assert degraded.json()["research"]["discovery_readiness"]["error_code"] == (
        "discovery_endpoint_degraded"
    )
    assert search_templates == ["", "", ""]


def test_research_route_requires_tenant_enrollment_and_buyer_authorization(monkeypatch):
    client = _client()
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    body = {
        "uid": "buyer-proof", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    }
    _enrol_local_research(monkeypatch, tenant_id="tenant-a")

    tenant_denied = client.post(
        "/api/v1/shopping-cases/sc-tenant-denied/research",
        headers={"X-Tenant-Id": "tenant-b"}, json=body,
    )
    assert tenant_denied.status_code == 403
    assert tenant_denied.json()["detail"]["code"] == "external_research_tenant_not_enrolled"

    body["research_authorized"] = False
    unauthorized = client.post(
        "/api/v1/shopping-cases/sc-not-authorized/research",
        headers={"X-Tenant-Id": "tenant-a"}, json=body,
    )
    assert unauthorized.status_code == 422


def test_research_route_rejects_source_without_policy_or_freshness(monkeypatch):
    client = _client()
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    _enrol_local_research(monkeypatch)
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    monkeypatch.setattr(
        "src.app.services.case_research_plan.approved_sources_for_plan",
        lambda plan: ({
            "source_id": "unfresh-source",
            "review_status": "approved",
            "freshness_sla_hours": 0,
            "publisher_policy": {"direct_origin_required": False},
            "allowed_domains": ["docs.example.test"],
        },),
    )

    response = client.post("/api/v1/shopping-cases/sc-policy/research", json={
        "uid": "buyer-proof", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    })

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "publisher_policy_or_freshness_not_enrolled"


def test_novel_source_still_requires_effective_discovery(monkeypatch):
    client = _client()
    from src.app.services.case_research_plan import build_case_research_plan

    plan = build_case_research_plan("OT cyber range")
    assert plan is not None
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "default")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    monkeypatch.setattr(
        "src.app.routers.shopping_cases._case_research_plan_from_trace",
        lambda db, *, case_id, tenant_id: plan,
    )
    monkeypatch.setattr(
        "src.app.services.case_research_plan.approved_sources_for_plan",
        lambda plan: ({
            "source_id": "reviewed-novel-source", "review_status": "approved",
            "freshness_sla_hours": 24,
            "publisher_policy": {"direct_origin_required": True},
            "allowed_domains": ["docs.example.test"], "canonical_entrypoints": [],
        },),
    )

    response = client.post("/api/v1/shopping-cases/sc-novel/research", json={
        "uid": "buyer-proof", "research_plan_id": plan.plan_id,
        "ambiguity_object_ids": [row.ambiguity_id for row in plan.ambiguities],
        "hypothesis_ids": [row.hypothesis_id for row in plan.hypotheses],
        "research_authorized": True,
    })

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "discovery_endpoint_not_configured"
