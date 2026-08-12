"""Honest readiness for the flag-gated commerce features (visual similarity + external search).

A feature is LIVE only when all preconditions hold — flag + (index | endpoint+allowlist). The
readiness report tells the truth so we never claim a capability that won't produce results.
"""
from __future__ import annotations

from src.app.services.commerce_feature_readiness import (
    commerce_feature_readiness,
    external_research_runtime_observation,
    external_search_readiness,
    record_external_research_runtime_observation,
    reset_external_research_runtime_observation,
    visual_search_readiness,
)


# ── visual similarity ──
def test_visual_off_when_flag_off(monkeypatch):
    monkeypatch.delenv("IMAGE_SIMILARITY_ENABLED", raising=False)
    r = visual_search_readiness({"IMAGE_SIMILARITY_ENABLED": False},
                                status_fn=lambda: {"index_ready": True, "available": True, "index_size": 9})
    assert r["live"] is False and "off" in r["reason"]


def test_visual_enabled_but_no_index_is_not_live(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": False, "available": True})
    assert r["live"] is False and "index" in r["reason"].lower()


def test_visual_live_when_flag_and_index(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": True, "available": True, "index_size": 42})
    assert r["live"] is True and r["index_size"] == 42 and r["reason"] == "live"


def test_visual_reports_missing_deps(monkeypatch):
    monkeypatch.setenv("IMAGE_SIMILARITY_ENABLED", "1")
    r = visual_search_readiness({}, status_fn=lambda: {"index_ready": False, "available": False})
    assert r["live"] is False and ("CLIP" in r["reason"] or "FAISS" in r["reason"])


# ── external search ──
def test_external_off_when_flag_off(monkeypatch):
    monkeypatch.delenv("EXTERNAL_RESEARCH_ENABLED", raising=False)
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    r = external_search_readiness({"EXTERNAL_RESEARCH_ENABLED": False})
    assert r["live"] is False and "off" in r["reason"]


def test_external_enabled_but_no_endpoint(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SEARCH_URL", raising=False)
    r = external_search_readiness({}, allowlist=["trusted.com"])
    assert r["live"] is False and "SEARCH_URL" in r["reason"]


def test_external_enabled_endpoint_but_no_allowlist(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    r = external_search_readiness({}, allowlist=[])
    assert r["live"] is False and "allowlist" in r["reason"].lower()


def test_external_live_when_all_present(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_URL", "https://requirements.example.com/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST", "docs.vendor.example")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "reviewer@example.com")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_KEY", "test-secret")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_PUBLISHER_POLICY_ID", "publisher-policy-v1")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_FRESHNESS_SLA_HOURS", "24")
    r = external_search_readiness(
        {}, allowlist=["trusted.com", "techradar.com"], tenant_id="tenant-a",
        probe_fn=lambda endpoint: {
            "reachable": True, "status": "healthy",
            "last_success_at": "2026-08-09T01:02:03Z",
        },
    )
    assert r["live"] is True and r["allowlist_size"] == 2 and r["reason"] == "live"
    assert r["configured"] is True
    assert r["reachable"] is True
    assert r["effective"] is True
    assert r["degraded"] is False
    assert r["last_success_at"] == "2026-08-09T01:02:03Z"
    assert r["advisory_live"] is True
    assert r["requirement_authority_ready"] is True
    assert r["requirements_credential_configured"] is True
    assert r["freshness_sla_hours"] == 24


def test_external_search_does_not_claim_requirement_authority_without_review(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_API_URL", "https://requirements.example.com/api?q={query}")
    monkeypatch.setenv("OFFICIAL_REQUIREMENTS_DOMAIN_ALLOWLIST", "docs.vendor.example")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.delenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", raising=False)

    r = external_search_readiness(
        {}, allowlist=["trusted.com"], tenant_id="tenant-a",
        probe_fn=lambda endpoint: {"reachable": True},
    )

    assert r["advisory_live"] is True
    assert r["requirement_authority_ready"] is False
    assert r["live"] is True
    assert r["reason"] == "live_advisory_only"
    assert "review" in r["authority_reason"].lower()


def test_external_search_requires_tenant_enrollment(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "https://search.example.com/api?q={query}")
    monkeypatch.delenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", raising=False)
    monkeypatch.setenv("EXTERNAL_RESEARCH_SOURCE_REVIEWED_BY", "reviewer@example.com")

    r = external_search_readiness({}, allowlist=["trusted.com"])

    assert r["live"] is False
    assert r["requirement_authority_ready"] is False
    assert "tenant" in r["reason"].lower()


def test_external_configured_is_not_reachable_or_effective_without_observation(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")
    monkeypatch.delenv("EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED", raising=False)

    result = external_search_readiness(
        {}, allowlist=["learn.microsoft.com"], tenant_id="tenant-a",
    )

    assert result["configured"] is True
    assert result["reachable"] is None
    assert result["effective"] is False
    assert result["degraded"] is False
    assert result["capability_status"] == "configured_unverified"
    assert result["error_code"] == "discovery_reachability_not_observed"


def test_external_probe_distinguishes_unreachable_from_degraded(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "tenant-a")

    unreachable = external_search_readiness(
        {}, allowlist=["learn.microsoft.com"], tenant_id="tenant-a",
        probe_fn=lambda endpoint: {
            "reachable": False, "last_failure_at": "2026-08-09T02:00:00Z",
        },
    )
    degraded = external_search_readiness(
        {}, allowlist=["learn.microsoft.com"], tenant_id="tenant-a",
        runtime_status={
            "reachable": True, "degraded": True,
            "last_success_at": "2026-08-09T01:00:00Z",
            "last_failure_code": "http_503",
        },
    )

    assert unreachable["error_code"] == "discovery_endpoint_unreachable"
    assert unreachable["reachable"] is False and unreachable["effective"] is False
    assert degraded["error_code"] == "discovery_endpoint_degraded"
    assert degraded["reachable"] is True and degraded["degraded"] is True
    assert degraded["effective"] is False


def test_explicit_local_proof_enrollment_allows_first_attempt_without_faking_success(monkeypatch):
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv(
        "EXTERNAL_RESEARCH_SEARCH_URL",
        "http://127.0.0.1:8888/search?q={query}&format=json",
    )
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "default")
    monkeypatch.setenv("EXTERNAL_RESEARCH_LOCAL_PROOF_ENROLLED", "1")

    result = external_search_readiness(
        {}, allowlist=["docs.factoryio.com"], tenant_id="default",
    )

    assert result["capability_status"] == "local_proof_enrolled_unverified"
    assert result["reachable"] is None
    assert result["effective"] is True
    assert result["last_success_at"] is None


def test_runtime_observation_separates_discovery_origin_and_claim_success():
    reset_external_research_runtime_observation()
    observed = record_external_research_runtime_observation({
        "source_execution": [{
            "discovery_status": "completed", "discovery_result_count": 3,
            "origin_selection_mode": "discovered_novel",
        }],
        "receipts": [{
            "provider_capability": "OFFICIAL_ORIGIN_FETCH",
            "execution_status": "completed", "network_execution": True,
        }],
        "claims": [{"claim_id": "official-1"}],
        "unresolved": [],
    })

    assert observed["reachable"] is True
    assert observed["last_discovery_result_count"] == 3
    assert observed["last_discovery_success_at"]
    assert observed["last_official_fetch_success_at"]
    assert observed["last_claim_compilation_success_at"]
    assert observed["last_claim_compilation_count"] == 1


def test_http_success_with_zero_discovery_results_is_not_effective_discovery():
    reset_external_research_runtime_observation()
    record_external_research_runtime_observation({
        "source_execution": [{
            "discovery_status": "attempted_empty", "discovery_result_count": 0,
        }],
        "receipts": [{
            "provider_capability": "WEB_DISCOVERY",
            "execution_status": "completed", "network_execution": True,
            "http_status": 200, "result_count": 0,
        }],
        "claims": [], "unresolved": [],
    })

    observed = external_research_runtime_observation()
    assert observed["reachable"] is None
    assert observed["last_discovery_success_at"] is None
    assert observed["last_discovery_result_count"] is None


def test_open_world_discovery_receipts_update_runtime_without_source_execution():
    reset_external_research_runtime_observation()
    observed = record_external_research_runtime_observation({
        "receipts": [{
            "provider_capability": "WEB_DISCOVERY",
            "execution_status": "completed", "network_execution": True,
            "external_call_dispatched": True, "http_status": 200,
            "result_count": 4,
        }],
        "claims": [], "unresolved": [],
    })

    assert observed["reachable"] is True
    assert observed["degraded"] is False
    assert observed["last_discovery_result_count"] == 4
    assert observed["last_discovery_success_at"]


def test_combined_health_projects_process_local_research_observations(monkeypatch):
    reset_external_research_runtime_observation()
    record_external_research_runtime_observation({
        "source_execution": [{
            "discovery_status": "completed", "discovery_result_count": 2,
            "origin_selection_mode": "discovered_novel",
        }],
        "receipts": [], "claims": [], "unresolved": [],
    })
    monkeypatch.setenv("EXTERNAL_RESEARCH_ENABLED", "1")
    monkeypatch.setenv("EXTERNAL_RESEARCH_SEARCH_URL", "http://127.0.0.1:8888/?q={query}")
    monkeypatch.setenv("EXTERNAL_RESEARCH_TENANT_ALLOWLIST", "default")

    health = commerce_feature_readiness(
        {}, allowlist=["docs.factoryio.com"], tenant_id="default",
        status_fn=lambda: {},
    )["external_search"]

    assert health["reachable"] is True
    assert health["effective"] is True
    assert health["last_discovery_result_count"] == 2
    assert health["last_discovery_success_at"]
    reset_external_research_runtime_observation()
