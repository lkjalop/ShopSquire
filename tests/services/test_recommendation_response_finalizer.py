from contextlib import contextmanager

from src.app.services import recommendation_response_finalizer as finalizer


def test_finalizer_freezes_one_trace_and_ordered_sku_identity(monkeypatch):
    recorded = {}

    def fake_trace(**kwargs):
        recorded.setdefault("events", []).append(kwargs)
        if kwargs.get("event_type") == "recommendation_result":
            recorded["event"] = kwargs

    def fake_decision(**kwargs):
        recorded["decision"] = kwargs
        return True

    monkeypatch.setattr(finalizer, "log_trace_event", fake_trace)
    monkeypatch.setattr(finalizer, "log_decision", fake_decision)
    emitted = {}

    @contextmanager
    def fake_session():
        yield object()

    def fake_market(db, **kwargs):
        emitted.update(kwargs)
        return [{"sku": "SKU-B", "tenant_id": kwargs["tenant_id"]}]

    monkeypatch.setattr("src.app.models.db.db_session", fake_session)
    monkeypatch.setattr(
        "src.app.services.market_projection.emit_projection_events", fake_market)

    payload = {
        "turn_intent": "COMPARE",
        "execution_mode": "v2_served",
        "currency": "AUD",
        "model_selection": {
            "selected": "qwen3:14b",
            "source": "model",
            "authority": "proposes",
            "latency_ms": 321.0,
        },
        "results": [
            {
                "sku": "SKU-B",
                "name": "Second",
                "why": ["within_budget", "gpu_vram_gb >= 8"],
                "score_norm": 0.92,
                "workload_fit": {"overall": "meets"},
            },
            {"sku": "SKU-A", "name": "First"},
        ],
        "constraints_used": {
            "use_cases": ["gaming"],
            "budget_max_cents": 200000,
            "workload_entities": [["game", "Black Myth Wukong"]],
            "requirements": {"gpu_vram_gb": [[">=", 8]]},
        },
        "decision": {
            "workload_entities": [["game", "Black Myth Wukong"]],
        },
        "intent": {
            "primary_use_case": "gaming",
            "workload_use_cases": ["gaming"],
            "title_requirements": {
                "external_workload_evidence": {
                    "live_allowed": True,
                    "items": [{
                        "status": "resolved",
                        "resolved_name": "Black Myth: Wukong",
                        "source": "steam",
                        "source_url": "https://store.steampowered.com/app/2358720/",
                        "retrieved_at": "2026-07-26T09:00:00+00:00",
                    }],
                },
            },
        },
        "right_panel": {"mode": "recommendations"},
        "semantic_resolution": {
            "outcome": "clarify",
            "catalog_authority": "blocked",
            "state_prevented": ["catalog_recommendation"],
        },
        "semantic_evidence": {
            "selected": ["concept_resolution"],
            "source_health": "degraded",
        },
        "catalog_alignment": {
            "outcome": "qualified",
            "qualified_skus": ["SKU-B"],
            "authority": "candidate_only",
        },
        "case_obligations": {
            "selected_sku": None,
            "unresolved": ["explicit_sku_selection"],
        },
        "explanation": {
            "sku": "SKU-B",
            "coverage_status": "bounded",
            "fit_ledger": [{"attribute": "gpu_vram_gb", "verdict": "meets"}],
        },
        "delivery_feasibility": {
            "requested_deadline": "2 days",
            "status": "unknown",
            "reason": "Dated transfer ETA is unavailable.",
        },
    }
    out = finalizer.finalize_core_response(
        payload, "trace-voice-1", query="compare these",
        tenant_id="tenant-a", uid="buyer-a",
    )

    expected = {
        "trace_id": "trace-voice-1",
        "ordered_skus": ["SKU-B", "SKU-A"],
    }
    assert out["canonical_identity"] == expected
    assert out["right_panel"]["canonical_identity"] == expected
    assert out["right_panel"]["anchor_sections"][0]["title"] == "Authorized recommendation"
    assert out["right_panel"]["anchor_sections"][0]["top_products"][0]["sku"] == "SKU-B"
    assert recorded["event"]["payload"]["canonical_identity"] == expected
    assert recorded["event"]["payload"]["right_panel_contract"]["canonical_identity"] == expected
    assert recorded["event"]["payload"]["semantic_resolution"]["catalog_authority"] == "blocked"
    assert recorded["decision"]["retrieved_context"]["semantic_evidence"]["source_health"] == "degraded"
    assert out["right_panel"]["semantic_resolution"]["outcome"] == "clarify"
    assert out["right_panel"]["catalog_alignment"]["qualified_skus"] == ["SKU-B"]
    assert out["right_panel"]["case_obligations"]["selected_sku"] is None
    assert out["right_panel"]["explanation"]["sku"] == "SKU-B"
    assert recorded["event"]["payload"]["right_panel_contract"]["explanation"]["sku"] == "SKU-B"
    assert out["right_panel"]["delivery_feasibility"]["status"] == "unknown"
    assert recorded["event"]["payload"]["delivery_feasibility"]["requested_deadline"] == "2 days"
    assert recorded["decision"]["retrieved_context"]["delivery_feasibility"]["status"] == "unknown"
    assert recorded["decision"]["proposed_action"]["delivery_feasibility"]["reason"].startswith("Dated")
    assert recorded["event"]["payload"]["catalog_alignment"]["authority"] == "candidate_only"
    assert recorded["decision"]["retrieved_context"]["case_obligations"]["unresolved"] == [
        "explicit_sku_selection",
    ]
    proposed = recorded["decision"]["proposed_action"]
    assert proposed["canonical_identity"] == expected
    assert [row["sku"] for row in proposed["products_summary"]] == expected["ordered_skus"]
    assert proposed["products_summary"][0]["reasons"] == [
        "within_budget", "gpu_vram_gb >= 8",
    ]
    assert proposed["products_summary"][0]["score_norm"] == 0.92
    assert proposed["products_summary"][0]["workload_fit"] == {"overall": "meets"}
    assert recorded["event"]["payload"]["constraints_used"]["use_cases"] == ["gaming"]
    assert recorded["event"]["payload"]["security"] == {
        "policy_route": "allow",
        "checked_boundary": "recommendation_facade",
        "has_image": False,
    }
    assert proposed["intent_analysis"]["budget_max"] == 2000
    assert proposed["intent_analysis"]["workloads"] == ["gaming"]
    assert proposed["intent_analysis"]["workload_entities"] == [
        ["game", "Black Myth Wukong"],
    ]
    assert proposed["intent_analysis"]["workload_evidence"]["live_allowed"] is True
    assert proposed["intent_analysis"]["requirements"] == {
        "gpu_vram_gb": [[">=", 8]],
    }
    assert proposed["intent_analysis"]["currency"] == "AUD"
    assert proposed["execution_mode"] == "v2_served"
    assert proposed["evidence_items"][-1]["type"] == "workload_requirement"
    assert proposed["evidence_items"][-1]["source"] == "steam"
    assert emitted["trace_id"] == "trace-voice-1"
    assert emitted["tenant_id"] == "tenant-a"
    assert [item["sku"] for item in emitted["results"]] == ["SKU-B", "SKU-A"]
    assert out["market_projections"] == [{"sku": "SKU-B", "tenant_id": "tenant-a"}]
    assert recorded["decision"]["retrieved_context"]["llm"] == {
        "selected": "qwen3:14b",
        "source": "model",
        "authority": "proposes",
        "latency_ms": 321.0,
    }


def test_finalizer_never_authorizes_products_without_positive_fit_evidence(monkeypatch):
    monkeypatch.setattr(finalizer, "log_trace_event", lambda **_: None)
    monkeypatch.setattr(finalizer, "log_decision", lambda **_: True)

    out = finalizer.finalize_core_response(
        {
            "results": [{"sku": "GPU-1", "name": "Expensive gaming laptop"}],
            "right_panel": {"mode": "recommendations"},
            "constraints_used": {"requirements": {}},
            "catalog_alignment": {"authority": "candidate_only"},
        },
        None,
    )

    # No trace persistence is needed for the truth projection itself.
    out = finalizer.finalize_core_response(
        {
            "results": [{"sku": "GPU-1", "name": "Expensive gaming laptop"}],
            "right_panel": {"mode": "recommendations"},
            "constraints_used": {"requirements": {}},
            "catalog_alignment": {"authority": "candidate_only"},
        },
        "trace-provisional-1",
    )
    section = out["right_panel"]["anchor_sections"][0]
    assert section["title"] == "Provisional catalog exploration"
    assert section["qualification_authority"] == "none"
    assert "capability" not in section["match_basis"]


def test_finalizer_deduplicates_repeated_exact_sku(monkeypatch):
    monkeypatch.setattr(finalizer, "log_trace_event", lambda **_: None)
    monkeypatch.setattr(finalizer, "log_decision", lambda **_: True)
    out = finalizer.finalize_core_response({
        "results": [
            {"sku": "SAME-1", "name": "Same configuration"},
            {"sku": "SAME-1", "name": "Same configuration repeated"},
        ],
    }, "trace-dedupe-1")
    assert [row["sku"] for row in out["results"]] == ["SAME-1"]


def test_finalizer_adds_sanitize_persist_and_projection_timings(monkeypatch):
    events = []
    monkeypatch.setattr(finalizer, "security_sanitize", lambda payload: dict(payload))
    monkeypatch.setattr(
        finalizer,
        "log_trace_event",
        lambda **kwargs: events.append(kwargs),
    )
    monkeypatch.setattr(finalizer, "log_decision", lambda **_kwargs: True)

    payload = {
        "products": [],
        "timing_breakdown": {
            "recommendation_total_ms": 12.0,
            "route_total_ms": 8.0,
        },
    }
    out = finalizer.finalize_core_response(
        payload, "trace-timing-1", query="laptop",
        tenant_id="tenant-a", uid="buyer-a",
    )

    timing = out["timing_breakdown"]
    assert timing["recommendation_total_ms"] == 12.0
    assert timing["route_total_ms"] == 8.0
    assert timing["sanitize_ms"] >= 0
    assert timing["trace_persist_ms"] >= 0
    assert timing["market_projection_ms"] >= 0
    assert timing["finalization_ms"] >= timing["sanitize_ms"]
    timing_events = [event for event in events if event["event_type"] == "timing_breakdown"]
    assert len(timing_events) == 1
    assert timing_events[0]["payload"]["timing_breakdown"] == timing


def test_finalizer_does_not_authorize_products_already_presented_as_failed_fit(
    monkeypatch,
):
    monkeypatch.setattr(finalizer, "security_sanitize", lambda payload: dict(payload))
    monkeypatch.setattr(finalizer, "log_trace_event", lambda **_kwargs: None)
    monkeypatch.setattr(finalizer, "log_decision", lambda **_kwargs: True)

    payload = {
        "turn_intent": "PROCUREMENT",
        "products": [
            {
                "sku": "CLOSE-1",
                "name": "Closest but unsuitable",
                "workload_fit": {"overall": "fails"},
            },
        ],
        "shelf": {
            "bands": [
                {
                    "id": "closest_fit",
                    "label": "Closest within budget - requirements not met",
                    "skus": ["CLOSE-1"],
                },
                {
                    "id": "stretch",
                    "label": "Meets your needs - outside budget",
                    "skus": ["FIT-1"],
                },
            ],
        },
    }

    out = finalizer.finalize_core_response(
        payload,
        "trace-failed-fit",
        query="50 game development laptops",
        tenant_id="tenant-a",
        uid="buyer-a",
    )

    assert out["right_panel"]["anchor_sections"] == []
    assert out["right_panel"]["canonical_identity"]["ordered_skus"] == ["CLOSE-1"]
