from datetime import datetime, timezone

from src.app.services.official_evidence_cache import OfficialEvidenceCache
from src.app.services.official_workload_research import (
    compile_source_claims,
    ranking_delta,
    research_official_sources,
)


def _approved_source(
    source_id: str = "nist_manufacturing_digital_twins",
    *,
    allowed_claim_types: list[str] | None = None,
) -> dict:
    allowed = allowed_claim_types or ["concept_identity", "workload_scope"]
    return {
        "source_id": source_id,
        "publisher": "NIST",
        "allowed_domains": ["nist.gov"],
        "canonical_entrypoints": ["https://nist.gov/digital-twins"],
        "allowed_claim_types": allowed,
        "forbidden_claim_types": [
            "minimum_requirements", "behavioral_performance", "benchmark_result",
            "exact_product_fit", "price", "availability",
        ],
        "applicability": {
            "workloads": ["manufacturing_digital_twin"],
            "scope": "Manufacturing digital twin context only",
            "resolution_owner": "research",
        },
        "publisher_policy": {
            "direct_origin_required": True,
            "policy_ref": "test:nist-v1",
        },
        "parser_type": "html",
        "freshness_sla_hours": 720,
        "review_status": "approved",
        "artefact_patterns": ["Digital Twins"],
    }


def test_factory_io_parser_compiles_only_recognized_official_statements() -> None:
    claims, context = compile_source_claims(
        "factory_io_official_docs",
        b"<html><body>Operating System Windows 7 SP1+ or higher "
        b"CPU with SSE2 instruction set support Graphics API DX10, DX11, DX12 capable</body></html>",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://docs.factoryio.com/manual/system-requirements/",
    )
    assert context == []
    assert {row["attribute"] for row in claims} == {
        "operating_system", "cpu_instruction_set", "graphics_api",
    }
    assert all(row["authority_status"] == "verified_official" for row in claims)
    assert not any(row["attribute"] in {"ram_gb", "gpu_vram_gb"} for row in claims)


def test_hyperv_parser_keeps_host_floor_separate_from_buyer_vm_scale() -> None:
    claims, _ = compile_source_claims(
        "microsoft_learn_hyperv",
        b"<p>Windows 11 Professional or Enterprise. A 64-bit processor with "
        b"second-level address translation. VM Monitor Mode Extensions. "
        b"Data Execution Prevention. Plan for at least 4 GB of RAM. "
        b"You need enough memory for all virtual machines.</p>",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://learn.microsoft.com/hyper-v",
    )
    by_attribute = {row["attribute"]: row for row in claims}
    assert by_attribute["ram_gb"]["value"] == 4
    assert by_attribute["operating_system"]["operator"] == "one_of"
    assert "vm_count" not in by_attribute


def test_nist_scope_never_becomes_a_hardware_floor() -> None:
    claims, context = compile_source_claims(
        "nist_digital_twin_cybersecurity", b"<p>Digital Twin Technology</p>",
        observed_at="2026-08-08T00:00:00Z", citation_url="https://csrc.nist.gov/x",
    )
    assert claims == []
    assert context[0]["claim_type"] == "workload_scope"
    assert "does not establish a hardware floor" in context[0]["statement"]


def test_application_parsers_do_not_share_claims_across_publishers() -> None:
    observed_at = "2026-08-08T00:00:00Z"
    blender, _ = compile_source_claims(
        "blender_official_requirements", b"Recommended 32 GB RAM and 8 GB VRAM",
        observed_at=observed_at, citation_url="https://www.blender.org/download/requirements/",
    )
    epic, _ = compile_source_claims(
        "epic_unreal_engine_requirements",
        b"Recommended hardware: 32 GB RAM, 8 GB or more Graphics RAM, DirectX 12",
        observed_at=observed_at, citation_url="https://dev.epicgames.com/documentation/x",
    )
    autocad, _ = compile_source_claims(
        "autodesk_autocad_requirements", b"Recommended 32 GB RAM; DirectX 12 capable GPU",
        observed_at=observed_at, citation_url="https://help.autodesk.com/view/ACD/2026/ENU/",
    )
    assert {row["attribute"] for row in blender} == {"ram_gb", "gpu_vram_gb"}
    assert {row["attribute"] for row in epic} == {"ram_gb", "gpu_vram_gb", "graphics_api"}
    assert {row["attribute"] for row in autocad} == {"ram_gb", "graphics_api"}
    assert all(row["source_id"] == "blender_official_requirements" for row in blender)
    assert all(row["source_id"] == "epic_unreal_engine_requirements" for row in epic)
    assert all(row["source_id"] == "autodesk_autocad_requirements" for row in autocad)


def test_unregistered_source_parser_cannot_create_claims() -> None:
    claims, context = compile_source_claims(
        "search_snippet", b"32 GB RAM and 16 GB VRAM is perfect",
        observed_at="2026-08-08T00:00:00Z", citation_url="https://search.invalid/",
    )
    assert claims == []
    assert context == []


def test_expired_total_deadline_dispatches_no_external_provider(monkeypatch) -> None:
    def unexpected_fetcher(**kwargs):
        raise AssertionError(f"provider constructed after deadline: {kwargs}")

    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher",
        unexpected_fetcher,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher",
        unexpected_fetcher,
    )

    result = research_official_sources(
        "novel request",
        search_url_template="http://127.0.0.1:8888/search?q={query}&format=json",
        sources=[_approved_source()],
        total_timeout_s=0,
    )

    assert result["provider_accounting"]["external_calls"] == 0
    assert result["execution_mode"] == "not_executed"
    assert result["runtime"]["deadline_exceeded"] is True
    assert result["source_execution"][0]["deadline_status"] == "exceeded_before_dispatch"
    assert result["unresolved"] == [{
        "source_id": "nist_manufacturing_digital_twins",
        "reason": "research_total_deadline_exceeded",
    }]


def test_autocad_point_cloud_tier_keeps_scope_and_workstation_requirement() -> None:
    claims, _ = compile_source_claims(
        "autodesk_autocad_requirements",
        b"Additional Requirements for large datasets, point clouds, and 3D modeling. "
        b"Memory 32 GB RAM or more. Display Card 12 GB VRAM or greater; "
        b"DirectX-capable workstation class graphics card.",
        observed_at="2026-08-08T00:00:00Z",
        citation_url="https://www.autodesk.com/support/technical/article/point-cloud",
    )
    by_attribute = {row["attribute"]: row for row in claims}
    assert by_attribute["gpu_vram_gb"]["value"] == 12
    assert by_attribute["gpu_vram_gb"]["condition"] == (
        "large datasets, point clouds, or 3D modelling"
    )
    assert by_attribute["gpu_class"]["value"] == "workstation"
    assert by_attribute["gpu_class"]["requirement_class"] == "target"


def test_ranking_delta_reports_movement_without_inventing_a_reason() -> None:
    before = {"shelves": [{"shelf_id": "shared", "initial": [
        {"product": {"sku": "A"}}, {"product": {"sku": "B"}},
    ], "next_page": []}]}
    after = {"shelves": [{"shelf_id": "shared", "initial": [
        {"product": {"sku": "B"}}, {"product": {"sku": "A"}},
    ], "next_page": []}]}
    rows = ranking_delta(before, after)
    assert {(row["sku"], row["before"], row["after"]) for row in rows} == {
        ("A", 1, 2), ("B", 2, 1),
    }
    assert all(
        row["reason"] == "relative order changed after deterministic evidence reduction"
        for row in rows
    )


def test_ranking_delta_names_only_observed_fit_and_gap_changes() -> None:
    before = {"shelves": [{"scope_id": "shared", "initial": [{
        "product": {"sku": "A"}, "fit_status": "conditional",
        "unknowns": ["operating system"], "meets": [], "misses": [],
    }, {
        "product": {"sku": "B"}, "fit_status": "conditional",
        "unknowns": ["ram"], "meets": [], "misses": [],
    }], "next_page": []}]}
    after = {"shelves": [{"scope_id": "shared", "initial": [{
        "product": {"sku": "B"}, "fit_status": "qualified",
        "unknowns": [], "meets": ["ram"], "misses": [],
    }, {
        "product": {"sku": "A"}, "fit_status": "conditional",
        "unknowns": ["operating system"], "meets": [], "misses": [],
    }], "next_page": []}]}

    rows = {row["sku"]: row for row in ranking_delta(before, after)}
    assert rows["B"]["reason"] == (
        "fit changed from conditional to qualified; resolved evidence gaps: ram; "
        "newly evidenced meets: ram"
    )
    assert rows["A"]["reason"] == "relative order changed after deterministic evidence reduction"


def test_context_only_research_is_not_reported_as_product_requirements(monkeypatch):
    class Discovery:
        def __init__(self, **kwargs):
            self.last_receipt = {}

        def fetch(self, query, *, allowlist, timeout_s):
            self.last_receipt = {
                "execution_status": "completed", "network_execution": True,
                "external_call_dispatched": True, "http_status": 200,
                "query_hash": "a" * 64, "response_body_hash": "b" * 64,
                "provider_endpoint_host": "search.local",
                "started_at": "2026-08-08T00:00:00Z",
                "completed_at": "2026-08-08T00:00:01Z",
            }
            return []

    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            return {
                "status": "completed",
                "content": b"NIST manufacturing digital twin predictive maintenance context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "c" * 64, "response_body_hash": "d" * 64,
                    "observed_at": "2026-08-08T00:00:00Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:01Z",
                    "completed_at": "2026-08-08T00:00:02Z",
                },
            }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher", Discovery,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "predicting factory breakdowns", search_url_template="http://search/?q={query}",
        sources=[_approved_source()], evidence_cache=OfficialEvidenceCache(),
        workload="manufacturing_digital_twin",
        now=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    )
    assert result["claims"] == []
    assert result["context_claims"]
    assert result["evidence_outcome"] == "context_only"
    assert {row["reason"] for row in result["unresolved"]} >= {
        "no_product_requirement_claims",
    }
    assert result["source_execution"] == [{
        "source_id": "nist_manufacturing_digital_twins",
        "publisher": "NIST",
        "parser_type": "html",
        "parser_version": "official-source-parser-v2:nist_manufacturing_digital_twins",
        "policy_version": "test:nist-v1",
        "freshness_sla_hours": 720,
        "origin_selection_mode": "canonical_direct",
        "canonical_url": "https://nist.gov/digital-twins",
        "selected_origin_url": "https://nist.gov/digital-twins",
        "cache_status": "miss",
        "canonical_fetch_status": "completed",
        "discovery_status": "not_needed",
        "discovery_reason": None,
        "discovery_result_count": 0,
        "deadline_status": "within_deadline",
        "parser_coverage": {
            "pages_fetched": 1,
            "candidate_claims": 1,
            "accepted_claims": 0,
            "rejected_claims": 0,
            "context_claims": 1,
            "parse_status": "completed",
        },
    }]
    assert all(row["provider_capability"] != "WEB_DISCOVERY" for row in result["receipts"])


def test_fresh_cache_precedes_canonical_and_is_tenant_scoped(monkeypatch):
    calls = {"origin": 0, "discovery": 0}

    class Discovery:
        def __init__(self, **kwargs):
            calls["discovery"] += 1

    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            calls["origin"] += 1
            return {
                "status": "completed", "content": b"Digital Twin context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "c" * 64, "response_body_hash": "d" * 64,
                    "observed_at": "2026-08-08T00:00:00Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:00Z",
                    "completed_at": "2026-08-08T00:00:01Z",
                },
            }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher", Discovery,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    cache = OfficialEvidenceCache(max_entries=2)
    kwargs = {
        "purpose": "factory breakdowns", "search_url_template": "",
        "sources": [_approved_source()], "evidence_cache": cache,
        "workload": "manufacturing_digital_twin",
        "now": datetime(2026, 8, 8, 2, tzinfo=timezone.utc),
    }
    first = research_official_sources(**kwargs, tenant_id="tenant-a")
    second = research_official_sources(**kwargs, tenant_id="tenant-a")
    third = research_official_sources(**kwargs, tenant_id="tenant-b")
    assert first["source_execution"][0]["origin_selection_mode"] == "canonical_direct"
    assert second["source_execution"][0]["origin_selection_mode"] == "evidence_cache"
    assert second["provider_accounting"] == {
        "external_calls": 0, "discovery_calls": 0,
        "official_origin_fetches": 0, "cache_hits": 1, "paid_calls": 0,
    }
    assert second["execution_mode"] == "evidence_cache"
    assert second["receipts"][0]["cache_status"] == "fresh_hit"
    assert third["source_execution"][0]["origin_selection_mode"] == "canonical_direct"
    assert calls == {"origin": 2, "discovery": 0}


def test_failed_canonical_uses_discovery_as_an_honest_fallback(monkeypatch):
    calls = {"origin": 0, "discovery": 0}
    queries = []

    class Discovery:
        def __init__(self, **kwargs):
            self.last_receipt = {}

        def fetch(self, query, *, allowlist, timeout_s):
            calls["discovery"] += 1
            queries.append(query)
            self.last_receipt = {
                "execution_status": "completed", "network_execution": True,
                "external_call_dispatched": True, "http_status": 200,
                "query_hash": "a" * 64, "response_body_hash": "b" * 64,
                "provider_endpoint_host": "search.local",
                "started_at": "2026-08-08T00:00:01Z",
                "completed_at": "2026-08-08T00:00:02Z",
            }
            return [{"url": "https://nist.gov/digital-twins"}]

    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            calls["origin"] += 1
            if calls["origin"] == 1:
                return {
                    "status": "failed", "content": b"", "error": "origin_http_status",
                    "receipt": {
                        "execution_status": "failed", "network_execution": True,
                        "external_call_dispatched": True, "http_status": 404,
                        "query_hash": "c" * 64, "provider_endpoint_host": "nist.gov",
                        "started_at": "2026-08-08T00:00:00Z",
                        "completed_at": "2026-08-08T00:00:01Z",
                    },
                }
            return {
                "status": "completed", "content": b"Digital Twin context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "d" * 64, "response_body_hash": "e" * 64,
                    "observed_at": "2026-08-08T00:00:02Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:02Z",
                    "completed_at": "2026-08-08T00:00:03Z",
                },
            }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher", Discovery,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "factory breakdowns", search_url_template="http://search/?q={query}",
        sources=[_approved_source()], evidence_cache=OfficialEvidenceCache(),
        workload="manufacturing_digital_twin",
        now=datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
    )
    execution = result["source_execution"][0]
    assert execution["origin_selection_mode"] == "canonical_fallback_discovered"
    assert execution["canonical_fetch_status"] == "failed"
    assert execution["discovery_status"] == "completed"
    assert execution["discovery_reason"] == "canonical_fetch_failed"
    assert execution["discovery_result_count"] == 1
    assert calls == {"origin": 2, "discovery": 1}
    assert queries and "site:" not in queries[0]
    assert result["provider_accounting"] == {
        "external_calls": 3, "discovery_calls": 1,
        "official_origin_fetches": 2, "cache_hits": 0, "paid_calls": 0,
    }
    ladder = {row["tier"]: row for row in result["evidence_ladder"]}
    assert ladder[0]["execution_status"] == "miss"
    assert ladder[1]["execution_status"] == "failed"
    assert ladder[4]["execution_status"] == "completed"
    assert ladder[5]["execution_status"] == "not_attempted"
    assert ladder[6] == {
        "tier": 6, "mechanism": "governed_abstention",
        "execution_status": "activated",
        "rejection_reason": "product_requirements_not_established",
        "billing_class": "not_applicable",
    }


def test_discovery_rejects_irrelevant_page_on_an_approved_domain(monkeypatch):
    class Discovery:
        def __init__(self, **kwargs):
            self.last_receipt = {}

        def fetch(self, query, *, allowlist, timeout_s):
            self.last_receipt = {
                "execution_status": "completed", "network_execution": True,
                "external_call_dispatched": True, "http_status": 200,
                "query_hash": "a" * 64, "response_body_hash": "b" * 64,
                "provider_endpoint_host": "search.local",
                "started_at": "2026-08-08T00:00:01Z",
                "completed_at": "2026-08-08T00:00:02Z",
            }
            return [{"url": "https://nist.gov/news/unrelated-page"}]

    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            raise AssertionError("an out-of-family page must not be fetched")

    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher", Discovery,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "factory breakdowns", search_url_template="http://search/?q={query}",
        sources=[_approved_source()], evidence_cache=OfficialEvidenceCache(),
        workload="manufacturing_digital_twin", novel_source_ids={"nist_manufacturing_digital_twins"},
        now=datetime(2026, 8, 8, 3, tzinfo=timezone.utc),
    )
    assert result["claims"] == []
    assert result["context_claims"] == []
    assert {row["reason"] for row in result["unresolved"]} == {
        "discovered_origin_outside_canonical_family",
    }


def test_claims_outside_source_policy_are_rejected(monkeypatch):
    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            return {
                "status": "completed", "content": b"Digital Twin context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "c" * 64, "response_body_hash": "d" * 64,
                    "observed_at": "2026-08-08T00:00:00Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:00Z",
                    "completed_at": "2026-08-08T00:00:01Z",
                },
            }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "factory breakdowns", search_url_template="", sources=[_approved_source(
            allowed_claim_types=["concept_identity"],
        )], evidence_cache=OfficialEvidenceCache(), workload="manufacturing_digital_twin",
        now=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    )
    assert result["context_claims"] == []
    assert {row["reason"] for row in result["unresolved"]} >= {
        "emitted_claim_type_not_allowed:workload_scope",
    }


def test_discovery_uses_bounded_fallback_queries_and_stops_on_official_origin(monkeypatch):
    queries: list[str] = []

    class Discovery:
        def __init__(self, **kwargs):
            self.last_receipt = {}

        def fetch(self, query, *, allowlist, timeout_s):
            queries.append(query)
            self.last_receipt = {
                "execution_status": "completed", "network_execution": True,
                "external_call_dispatched": True, "http_status": 200,
                "query_hash": str(len(queries)) * 64, "response_body_hash": "b" * 64,
                "provider_endpoint_host": "search.local",
                "started_at": "2026-08-08T00:00:01Z",
                "completed_at": "2026-08-08T00:00:02Z",
            }
            if len(queries) == 1:
                return []
            return [{"url": "https://nist.gov/digital-twins/factory"}]

    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            return {
                "status": "completed", "content": b"Digital Twin context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "c" * 64, "response_body_hash": "d" * 64,
                    "observed_at": "2026-08-08T00:00:00Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:00Z",
                    "completed_at": "2026-08-08T00:00:01Z",
                },
            }

    source = _approved_source()
    source["canonical_entrypoints"] = ["https://nist.gov/digital-twins"]
    source["artefact_patterns"] = ["manufacturing digital twin", "factory lifecycle"]
    monkeypatch.setattr(
        "src.app.services.official_workload_research.HttpxResearchFetcher", Discovery,
    )
    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )

    result = research_official_sources(
        "factory breakdowns", search_url_template="http://search/?q={query}",
        sources=[source], evidence_cache=OfficialEvidenceCache(),
        workload="manufacturing_digital_twin",
        novel_source_ids={source["source_id"]},
        now=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    )

    assert len(queries) == 2
    assert all("factory breakdowns" not in query for query in queries)
    assert result["source_execution"][0]["discovery_query_count"] == 2
    discovery_receipts = [
        row for row in result["receipts"]
        if row["provider_capability"] == "WEB_DISCOVERY"
    ]
    assert [row["query_id"] for row in discovery_receipts] == [
        f"{source['source_id']}_q1", f"{source['source_id']}_q2",
    ]
    assert result["source_execution"][0]["discovery_query_axes"] == [
        "named_concept", "application_scope",
    ]
    assert [row["query_purpose"] for row in discovery_receipts] == [
        "official_origin_discovery:named_concept",
        "official_origin_discovery:application_scope",
    ]


def test_origin_quality_prefers_requirements_page_over_forum_order(monkeypatch):
    from src.app.services.official_workload_research import _discovered_origin_for_source

    source = _approved_source()
    source["canonical_entrypoints"] = ["https://nist.gov/digital-twins"]
    results = [
        {
            "url": "https://nist.gov/digital-twins/community/forum",
            "title": "Community forum discussion",
        },
        {
            "url": "https://nist.gov/digital-twins/system-requirements",
            "title": "Official system requirements",
        },
    ]

    selected, error = _discovered_origin_for_source(results, source)

    assert error is None
    assert selected.endswith("/system-requirements")


def test_wrong_workload_applicability_blocks_network_execution(monkeypatch):
    class Origin:
        def __init__(self, **kwargs):
            raise AssertionError("inapplicable source must not be fetched")

    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "OT cyber range", search_url_template="", sources=[_approved_source()],
        evidence_cache=OfficialEvidenceCache(), workload="ot_cyber_range",
    )
    assert result["execution_mode"] == "not_executed"
    assert result["receipts"] == []
    assert {row["reason"] for row in result["unresolved"]} >= {
        "source_not_applicable_to_workload",
    }


def test_stale_origin_observation_cannot_emit_fresh_claims(monkeypatch):
    class Origin:
        def __init__(self, **kwargs):
            pass

        def fetch(self, url, *, allowlist, timeout_s, certification_run_id):
            return {
                "status": "completed", "content": b"Digital Twin context",
                "content_type": "text/html",
                "receipt": {
                    "execution_status": "completed", "network_execution": True,
                    "external_call_dispatched": True, "http_status": 200,
                    "query_hash": "c" * 64, "response_body_hash": "d" * 64,
                    "observed_at": "2025-01-01T00:00:00Z",
                    "provider_endpoint_host": "nist.gov",
                    "started_at": "2026-08-08T00:00:00Z",
                    "completed_at": "2026-08-08T00:00:01Z",
                },
            }

    monkeypatch.setattr(
        "src.app.services.official_workload_research.GovernedOfficialOriginFetcher", Origin,
    )
    result = research_official_sources(
        "factory breakdowns", search_url_template="", sources=[_approved_source()],
        evidence_cache=OfficialEvidenceCache(), workload="manufacturing_digital_twin",
        now=datetime(2026, 8, 8, 1, tzinfo=timezone.utc),
    )
    assert result["claims"] == []
    assert result["context_claims"] == []
    assert {row["reason"] for row in result["unresolved"]} >= {
        "origin_evidence_stale",
    }
