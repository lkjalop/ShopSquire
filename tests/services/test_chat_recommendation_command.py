from src.app.services.chat_recommendation_dispatch import (
    ChatRecommendationCommand,
    dispatch_chat_recommendation,
    normalize_chat_recommendation_result,
)


def test_chat_command_coerces_boundary_values_once():
    command = ChatRecommendationCommand.from_params({
        "query": 123,
        "uid": "buyer-1",
        "trace_id": "trace-1",
        "turn_intent": "search",
        "external_research_consent": "TRUE",
        "memory_mode": "temporary",
        "session_epoch": " epoch-1 ",
    })

    assert command.query == "123"
    assert command.trace_id == "trace-1"
    assert command.observed_lane == "SEARCH"
    assert command.external_research_consent is True
    assert command.memory_enabled is False
    assert command.session_epoch == "epoch-1"


def test_chat_command_generates_one_trace_identity_when_absent():
    command = ChatRecommendationCommand.from_params({"query": "laptop", "uid": "b"})
    assert command.trace_id
    assert command.raw_params.get("trace_id") is None


def test_dispatch_result_normalization_preserves_authoritative_values():
    command = ChatRecommendationCommand.from_params({
        "query": "laptop", "uid": "b", "trace_id": "trace-1",
        "turn_intent": "research",
    })

    result = normalize_chat_recommendation_result(
        {"execution_mode": "v2_served", "trace_id": "authoritative"},
        command=command,
    )

    assert result == {
        "execution_mode": "v2_served",
        "trace_id": "authoritative",
        "decision_trace_id": "authoritative",
        "operation_id": "chat:trace-1",
        "case_id": None,
        "case_revision": None,
        "research_run_id": None,
        "execution_lane": "RESEARCH",
    }


def test_dispatch_normalization_projects_ingress_facts_without_reparsing_query():
    command = ChatRecommendationCommand.from_params({
        "query": "I have AUD 2,500 for an unknown workload",
        "uid": "b", "trace_id": "trace-budget",
    })
    canonical_budget = {
        "budget_min": None, "budget_max": 2500, "mode": "ceiling",
        "source_span": [7, 16],
    }
    result = normalize_chat_recommendation_result({
        "canonical_facts": {
            "canonical_budget": canonical_budget,
            "commercial_terms": {"currency": "AUD", "quantity": None},
            "quantity": None,
            "budget_scope": "unknown",
            "total_budget_cents": None,
        },
    }, command=command)

    assert result["canonical_budget"] == canonical_budget
    assert result["commercial_terms"]["currency"] == "AUD"
    assert result["budget_scope"] == "unknown"


def test_degraded_chat_does_not_redispatch_the_complete_core(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from src.app.services import recommendation_compatibility, recommendation_facade

    calls = {"facade": 0, "compatibility": 0}

    def facade_once(*args, **kwargs):
        calls["facade"] += 1
        return recommendation_facade.FacadeOutcome(
            status="degraded", reason="model_execution_timeout", lane="PROCUREMENT",
            facts={"quantity": 200, "total_budget_cents": 12_000_000},
            semantic_status={"status": "fallback", "subject_role": "PROCURE_SUBJECT"},
            execution_evidence={"core_invocation_count": 1, "operation_id": "trace-1"},
            diagnostics={"timing_breakdown": {"router_queue_ms": 30, "router_wall_ms": 12000}},
        )

    def forbidden_compatibility(*args, **kwargs):
        calls["compatibility"] += 1
        raise AssertionError("a completed recommendation turn must not be run again")

    monkeypatch.setenv("RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED", "1")
    monkeypatch.setattr(recommendation_facade, "dispatch_recommendation_core_typed", facade_once)
    monkeypatch.setattr(recommendation_compatibility, "serve_v2_compatibility", forbidden_compatibility)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    status, body = asyncio.run(dispatch_chat_recommendation(
        request, {"query": "Buy 200 CRM seats", "uid": "buyer", "trace_id": "trace-1"},
        redis=object(), db=object(), role="buyer",
        tenant_id_resolver=lambda _request: "default",
    ))

    assert status == 200
    assert calls == {"facade": 1, "compatibility": 0}
    assert body["execution_mode"] == "v2_unavailable"
    assert body["timing_breakdown"] == {"router_queue_ms": 30, "router_wall_ms": 12000}
    assert body["canonical_facts"]["quantity"] == 200
    assert body["execution_evidence"]["core_invocation_count"] == 1
    assert body["semantic_resolution"]["reason"] == "model_execution_timeout"
    assert body["workload_authorization"]["reason"] == "model_execution_timeout"
    assert "model" in body["assistant_message"].lower()
    assert "catalog" not in body["assistant_message"].lower()


def test_served_chat_preserves_facade_facts_semantics_and_execution_evidence(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from src.app.services import recommendation_facade

    def served_once(*args, **kwargs):
        return recommendation_facade.FacadeOutcome(
            status="served", lane="SEARCH",
            payload={"products": [], "decision_trace_id": "decision-1"},
            facts={"quantity": 200, "total_budget_cents": 12_000_000},
            semantic_status={
                "status": "evaluated", "subject_role": "PROCURE_SUBJECT",
                "source": "validated_model",
            },
            execution_evidence={
                "component": "recommendation_core", "status": "completed",
                "core_invocation_count": 1, "operation_id": "chat:trace-1",
            },
        )

    monkeypatch.setattr(
        recommendation_facade, "dispatch_recommendation_core_typed", served_once,
    )
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))

    status, body = asyncio.run(dispatch_chat_recommendation(
        request, {"query": "Buy 200 CRM seats", "uid": "buyer", "trace_id": "trace-1"},
        redis=object(), db=object(), role="buyer",
        tenant_id_resolver=lambda _request: "default",
    ))

    assert status == 200
    assert body["canonical_facts"]["quantity"] == 200
    assert body["semantic_status"]["status"] == "evaluated"
    assert body["execution_evidence"]["core_invocation_count"] == 1
