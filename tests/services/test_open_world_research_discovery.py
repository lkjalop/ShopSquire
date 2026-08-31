import pytest

from src.app.services.case_research_plan import build_case_research_plan
from src.app.services.open_world_research_discovery import discover_open_world_publishers
from src.app.services.shopping_case_open_world_research import (
    _consume_interpretation_with_bounded_wait,
    _merge_governed_discovery_retry,
)


class StubFetcher:
    def __init__(self):
        self.last_receipt = {}
        self.calls = []

    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"hash-{len(self.calls)}",
            "network_execution": True,
            "external_call_dispatched": True,
            "execution_status": "completed",
            "http_status": 200,
        }
        return [
            {"url": "https://vendor.example/blog/opinion", "title": "Opinion"},
            {
                "url": "https://vendor.example/docs/scientific-solver-system-requirements/",
                "title": "Scientific solver system requirements",
            },
        ]


def test_novel_plan_runs_bounded_discovery_without_fetching_or_claiming_authority():
    plan = build_case_research_plan("novel scientific solver", allow_open_world=True)
    assert plan is not None
    fetcher = StubFetcher()
    result = discover_open_world_publishers(
        plan, search_url_template="http://localhost/search?q={query}", fetcher=fetcher,
    )
    assert len(fetcher.calls) == 3
    assert all(call[1] == [] and call[3] is True for call in fetcher.calls)
    assert result["candidates"][0]["url"].endswith(
        "/docs/scientific-solver-system-requirements/"
    )
    assert all("/blog/" not in item["url"] for item in result["candidates"])
    assert result["provider_accounting"] == {
        "discovery_calls": 3, "external_calls": 3,
        "official_origin_fetches": 0, "paid_calls": 0,
    }
    assert result["claims"] == []
    assert all(item["authority"] == "not_accepted" for item in result["candidates"])
    ladder = {row["tier"]: row for row in result["evidence_ladder"]}
    assert ladder[4]["execution_status"] == "completed"
    assert ladder[4]["dispatch_count"] == 3
    assert ladder[5]["paid_calls"] == 0


class PartialEngineFetcher(StubFetcher):
    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        rows = super().fetch(
            query, allowlist=allowlist, timeout_s=timeout_s,
            discovery_candidates_only=discovery_candidates_only,
        )
        self.last_receipt.update({
            "allowlisted_result_count": len(rows),
            "engines_queried": ["startpage", "bing"],
            "engines_responded": ["bing"],
            "engine_failures": [{"engine": "startpage", "reason": "CAPTCHA"}],
            "engine_reliability": [{
                "engine": "startpage", "health": "degraded", "latency_ms": 2000,
            }],
        })
        return rows


def test_partial_engine_failure_is_projected_without_disabling_discovery():
    plan = build_case_research_plan("novel scientific solver", allow_open_world=True)
    assert plan is not None
    result = discover_open_world_publishers(
        plan, search_url_template="http://localhost/search?q={query}",
        fetcher=PartialEngineFetcher(),
    )

    tier = next(row for row in result["evidence_ladder"] if row["tier"] == 4)
    assert tier["execution_status"] == "degraded"
    assert tier["dispatch_count"] == 3
    assert tier["engines_responded"] == ["bing"]
    assert tier["engine_failures"] == [{"engine": "startpage", "reason": "CAPTCHA"}]


class QualityFetcher(StubFetcher):
    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"hash-{len(self.calls)}", "network_execution": True,
            "external_call_dispatched": True, "execution_status": "completed", "http_status": 200,
        }
        rows = [
            {
                "url": "https://www.linkedin.com/pulse/general-requirements-opinion",
                "title": "General system requirements opinion",
            },
        ]
        if "finite" in query.lower():
            rows.append({
                "url": "https://docs.solver.example/help/finite-element-system-requirements",
                "title": "Finite element solver system requirements",
            })
        return rows


def test_discovery_prefers_cross_axis_subject_match_and_rejects_social_articles():
    plan = build_case_research_plan(
        "Finite element solver with officially supported hardware", allow_open_world=True,
    )
    assert plan is not None
    result = discover_open_world_publishers(
        plan, search_url_template="http://localhost/search?q={query}", fetcher=QualityFetcher(),
    )
    assert [row["domain"] for row in result["candidates"]] == ["docs.solver.example"]
    assert result["candidates"][0]["query_axes"] == [
        "concept_and_software", "requirements_and_compatibility", "support_and_constraints",
    ]
    assert result["candidates"][0]["subject_overlap_count"] >= 2
    assert result["candidates"][0]["quality_score"] > 10
    assert result["candidates"][0]["publisher_ownership_evaluation"]["authority"] == "candidate_only"
    assert result["candidates"][0]["publisher_ownership_evaluation"]["ownership_basis"] == (
        "semantic_origin_signals_only"
    )
    assert result["candidates"][0]["publisher_ownership_evaluation"]["signals"][
        "independent_query_axis_count"
    ] == 3
    assert result["candidates"][0]["publisher_ownership_evaluation"]["status"] in {
        "plausible_direct_origin", "plausible_documentation_origin",
    }


def test_open_world_queries_lead_with_named_software_not_buyer_filler():
    plan = build_case_research_plan(
        "I process large drone surveys in Agisoft Metashape. Only hardware officially "
        "supported by Agisoft is acceptable.",
        allow_open_world=True,
    )
    assert plan is not None
    assert all(
        row.query.lower().startswith("agisoft metashape")
        for row in plan.discovery_queries[1:]
    )
    assert all("process" not in row.query.lower() for row in plan.discovery_queries)
    assert plan.discovery_queries[2].query == "Agisoft Metashape system requirements compatibility"
    assert plan.discovery_queries[0].query.startswith("site:agisoft.com Agisoft Metashape")


class PublisherHostFetcher(StubFetcher):
    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"hash-{len(self.calls)}", "network_execution": True,
            "external_call_dispatched": True, "execution_status": "completed", "http_status": 200,
        }
        return [
            {
                "title": "AcmeSolver System Requirements",
                "url": "https://hardware-blog.example/acmesolver-system-requirements/",
            },
            {
                "title": "System Requirements - AcmeSolver",
                "url": "https://www.acmesolver.com/support/system-requirements/",
            },
        ]


def test_named_publisher_host_outranks_blogs_with_the_same_requirements_title():
    plan = build_case_research_plan(
        "I process surveys in AcmeSolver and need its official system requirements",
        allow_open_world=True,
    )
    assert plan is not None
    result = discover_open_world_publishers(
        plan,
        search_url_template="https://search.invalid/?q={query}",
        fetcher=PublisherHostFetcher(),
    )

    assert result["candidates"][0]["domain"] == "www.acmesolver.com"
    assert result["candidates"][0]["registrable_domain"] == "acmesolver.com"
    assert result["candidates"][0]["authority"] == "not_accepted"


class NoCrediblePublisherFetcher(StubFetcher):
    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"empty-{len(self.calls)}", "network_execution": True,
            "external_call_dispatched": True, "execution_status": "completed",
            "http_status": 200,
        }
        return [{
            "title": "Unrelated discussion",
            "url": "https://www.reddit.com/r/hardware/comments/unrelated",
        }]


def test_completed_search_with_no_credible_publisher_remains_unresolved():
    plan = build_case_research_plan(
        "portable analysis for an unfamiliar scientific workflow", allow_open_world=True,
    )
    assert plan is not None

    result = discover_open_world_publishers(
        plan, search_url_template="http://search/?q={query}",
        fetcher=NoCrediblePublisherFetcher(),
    )

    assert result["status"] == "no_publisher_candidates"
    assert result["candidates"] == []
    assert result["provider_accounting"]["discovery_calls"] == 3
    assert result["next_action"] == "approve_publisher_origin_or_upload_requirements"


class IntermediaryRequirementsFetcher(StubFetcher):
    def fetch(self, query, *, allowlist, timeout_s, discovery_candidates_only):
        self.calls.append((query, allowlist, timeout_s, discovery_candidates_only))
        self.last_receipt = {
            "query_hash": f"intermediary-{len(self.calls)}", "network_execution": True,
            "external_call_dispatched": True, "execution_status": "completed", "http_status": 200,
        }
        return [{
            "title": "AcmeSolver official system requirements documentation",
            "url": "https://www.researchgate.net/publication/acmesolver-system-requirements",
        }]


def test_repeated_search_axes_do_not_promote_an_intermediary_as_a_publisher():
    plan = build_case_research_plan(
        "I use AcmeSolver and need official system requirements", allow_open_world=True,
    )
    assert plan is not None
    result = discover_open_world_publishers(
        plan, search_url_template="http://search/?q={query}",
        fetcher=IntermediaryRequirementsFetcher(),
    )
    assert result["status"] == "no_publisher_candidates"
    assert result["candidates"] == []
    assert result["provider_accounting"]["discovery_calls"] == 3


def test_model_retry_merge_caps_authority_and_accumulates_provider_calls():
    primary = {
        "status": "no_publisher_candidates", "candidates": [], "claims": [],
        "receipts": [{"query_id": "q1"}],
        "provider_accounting": {
            "discovery_calls": 3, "external_calls": 3,
            "official_origin_fetches": 0, "paid_calls": 0,
        },
    }
    retry = {
        "status": "publisher_candidates_found",
        "candidates": [{
            "url": "https://docs.vendor.example/requirements", "quality_score": 20,
            "authority": "not_accepted",
        }],
        "claims": [{"attribute": "ram_gb", "value": 64}],
        "receipts": [{"query_id": "model_1"}],
        "provider_accounting": {
            "discovery_calls": 1, "external_calls": 1,
            "official_origin_fetches": 0, "paid_calls": 0,
        },
    }

    merged = _merge_governed_discovery_retry(primary, retry)

    assert merged["status"] == "publisher_candidates_found"
    assert merged["provider_accounting"]["external_calls"] == 4
    assert merged["claims"] == []
    assert merged["candidates"][0]["authority"] == "not_accepted"


@pytest.mark.asyncio
async def test_completed_durable_query_plan_is_consumed_without_waiting(monkeypatch):
    plan = build_case_research_plan("novel scientific solver", allow_open_world=True)
    assert plan is not None
    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.consume_completed_case_interpretation",
        lambda *_args, **_kwargs: (plan, {
            "status": "completed_durable", "authority": "discovery_proposal_only",
        }),
    )

    proposed, receipt = await _consume_interpretation_with_bounded_wait(
        object(), tenant_id="default", case_id="sc-1", case_revision=1, plan=plan,
    )

    assert proposed == plan
    assert receipt["bounded_wait_ms"] == 600
    assert receipt["fallback_used"] is False


def test_cooperative_cancellation_stops_remaining_query_dispatches():
    plan = build_case_research_plan(
        "portable analysis for an unfamiliar scientific workflow", allow_open_world=True,
    )
    assert plan is not None
    fetcher = StubFetcher()

    result = discover_open_world_publishers(
        plan, search_url_template="http://search/?q={query}", fetcher=fetcher,
        cancellation_requested=lambda: len(fetcher.calls) >= 1,
    )

    assert len(fetcher.calls) == 1
    assert result["status"] == "cancelled"
    assert result["candidates"] == []
    assert result["provider_accounting"]["discovery_calls"] == 1
    assert result["cancellation"] == {
        "requested": True, "remaining_queries_not_dispatched": 2,
    }


def test_case_service_forwards_http_cancellation_to_discovery(monkeypatch):
    from src.app.services.case_research_plan import build_case_research_plan
    from src.app.services.shopping_case_open_world_research import (
        execute_open_world_publisher_discovery,
    )

    plan = build_case_research_plan("novel certified simulation suite", allow_open_world=True)
    assert plan is not None and plan.publisher_status == "unresolved"
    observed = {}

    async def cancelled_discovery(*args, cancellation_requested=None, **kwargs):
        observed["callback"] = cancellation_requested
        assert cancellation_requested is not None and cancellation_requested()
        return {
            "schema_version": "open-world-discovery-v1",
            "status": "cancelled",
            "publisher_status": "unresolved",
            "candidates": [],
            "receipts": [],
            "provider_accounting": {
                "discovery_calls": 0, "external_calls": 0,
                "official_origin_fetches": 0, "paid_calls": 0,
            },
            "claims": [],
            "next_action": "explicit_refresh_or_upload_requirements",
            "cancellation": {"requested": True, "remaining_queries_not_dispatched": 3},
        }

    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.external_search_readiness",
        lambda **kwargs: {"effective": True},
    )
    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.consume_completed_case_interpretation",
        lambda db, *, plan, **kwargs: (plan, {"status": "not_used"}),
    )
    monkeypatch.setattr(
        "src.app.services.open_world_research_discovery.discover_open_world_publishers_async",
        cancelled_discovery,
    )
    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.persist_discovered_candidates",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.project_accepted_catalog",
        lambda *args, **kwargs: type("Projection", (), {"model_dump": lambda self, **kw: {"shelves": []}})(),
    )
    monkeypatch.setattr(
        "src.app.services.shopping_case_open_world_research.log_trace_event",
        lambda **kwargs: None,
    )

    class Db:
        def commit(self):
            pass

        def execute(self, _statement):
            case = type("Case", (), {"revision": 1})()
            return type("Result", (), {"scalar_one": lambda self: case})()

    result = execute_open_world_publisher_discovery(
        Db(), plan=plan, tenant_id="default", case_id="sc-cancel", uid="buyer",
        search_url_template="http://127.0.0.1:8888/search?q={query}&format=json",
        runtime_status={}, candidate_configuration_ids=[], budget_cents=None,
        cancellation_requested=lambda: True,
    )
    assert callable(observed["callback"])
    assert result["research"]["status"] == "cancelled"
    assert result["research"]["provider_accounting"]["external_calls"] == 0
    assert result["research"]["next_action"] == "explicit_refresh_or_upload_requirements"
