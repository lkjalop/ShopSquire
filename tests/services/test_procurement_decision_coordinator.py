from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.app.models.orm import Base
from src.app.services.procurement_case_state import ProcurementCaseState
from src.app.services.procurement_decision_coordinator import (
    ProcurementDecisionCoordinator, invalidations_for_changed_paths,
    record_procurement_decision_run,
)
from src.app.services.procurement_decision_run import load_decision_runs
from src.app.services.recommendation_core.envelope import CoreResponse, StageResult, TurnEnvelope


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_coordinator_binds_stage_receipts_to_effective_case_revision():
    db = _db()
    state = ProcurementCaseState(
        case_id="case-a", revision=4, objective="fleet",
        workloads=["engineering"], requested_quantity=20,
    )
    envelope = TurnEnvelope.from_suggest_params(
        query="move five units", uid="buyer", tenant_id="portfolio",
        trace_id="trace-123", session={"procurement_case_state": state.model_dump(mode="json")},
    )
    response = CoreResponse(envelope=envelope, lane="PROCUREMENT")
    response.extras["procurement_case_state"] = state.model_dump(mode="json")
    response.extras["case_patch_application"] = {"changed_paths": ["destinations"]}
    response.stage_results = [StageResult(stage="fit", status="ok", latency_ms=2)]

    projection = record_procurement_decision_run(db, envelope=envelope, response=response)

    assert projection["case_revision"] == 4
    assert projection["commercial_authority_granted"] is False
    assert projection["stage_receipts"] == [{
        "stage": "fit", "status": "completed", "dependency_stages": [],
        "reason_code": None,
    }]
    assert projection["invalidations"][0]["changed_path"] == "destinations"
    stored = load_decision_runs(db, tenant_id="portfolio", case_id="case-a")
    assert stored[0].stage_receipts[0].stage == "fit"
    assert stored[0].invalidations[0].invalidated_stages == (
        "commercial", "fulfilment", "response",
    )


def test_invalidation_is_dependency_based_not_place_name_based():
    rows = invalidations_for_changed_paths(["destinations", "requested_quantity", "objective"])
    assert rows[0].changed_path == "destinations"
    assert "fit" not in rows[0].invalidated_stages
    assert "fit" in rows[2].invalidated_stages


def test_unresolved_and_skipped_legacy_stages_never_project_as_completed():
    db = _db()
    state = ProcurementCaseState(case_id="case-b", revision=1, objective="novel workload")
    envelope = TurnEnvelope.from_suggest_params(
        query="help", uid="buyer", tenant_id="portfolio", trace_id="trace-truth",
        session={"procurement_case_state": state.model_dump(mode="json")},
    )
    response = CoreResponse(envelope=envelope, lane="CLARIFY")
    response.stage_results = [
        StageResult(stage="interpretation", status="clarify", latency_ms=1),
        StageResult(stage="fit", status="skipped", latency_ms=0),
    ]

    projection = record_procurement_decision_run(db, envelope=envelope, response=response)

    assert [row["status"] for row in projection["stage_receipts"]] == [
        "degraded", "not_run",
    ]
    assert [row["reason_code"] for row in projection["stage_receipts"]] == [
        "legacy_stage_clarify", "legacy_stage_skipped",
    ]


def test_coordinator_persists_temporal_conflicts_without_resolving_them():
    db = _db()
    state = ProcurementCaseState(case_id="case-conflict", revision=2, objective="fleet")
    envelope = TurnEnvelope.from_suggest_params(
        query="can it arrive", uid="buyer", tenant_id="portfolio", trace_id="trace-conflict",
        session={"procurement_case_state": state.model_dump(mode="json")},
    )
    response = CoreResponse(envelope=envelope, lane="PROCUREMENT")
    response.stage_results = [StageResult(stage="commercial", status="ok")]
    response.extras["temporal_claims"] = [
        {
            "claim_id": "supplier", "subject": "offer:a", "attribute": "lead_time_days",
            "value": 8, "valid_from": "2026-08-17T00:00:00+00:00",
            "observed_at": "2026-08-17T01:00:00+00:00", "source": "supplier",
            "source_authority": "supplier_attested",
        },
        {
            "claim_id": "carrier", "subject": "offer:a", "attribute": "lead_time_days",
            "value": 12, "valid_from": "2026-08-17T00:00:00+00:00",
            "observed_at": "2026-08-17T02:00:00+00:00", "source": "carrier",
            "source_authority": "carrier_observed",
        },
    ]

    projection = record_procurement_decision_run(db, envelope=envelope, response=response)

    assert projection["temporal_conflicts"][0]["status"] == "unresolved"
    stored = load_decision_runs(db, tenant_id="portfolio", case_id="case-conflict")
    assert stored[0].temporal_conflicts[0].resolution_owner == "supplier"


def test_shadow_coordinator_owns_single_invocation_and_grants_no_authority():
    db = _db()
    state = ProcurementCaseState(case_id="case-owner", revision=1, objective="fleet")
    envelope = TurnEnvelope.from_suggest_params(
        query="help", uid="buyer", tenant_id="portfolio", trace_id="trace-owner",
        session={"procurement_case_state": state.model_dump(mode="json")},
    )
    response = CoreResponse(envelope=envelope, lane="SEARCH")
    calls = []
    coordinator = ProcurementDecisionCoordinator(db, envelope)
    result = coordinator.evaluate(lambda: calls.append("called") or response)
    coordinator.persist(result)
    assert calls == ["called"]
    assert result.extras["procurement_decision_coordinator"]["mode"] == (
        "shadow_owner_legacy_stage_adapter"
    )
    assert result.extras["procurement_decision_coordinator"]["commercial_authority_granted"] is False
    assert len(load_decision_runs(db, tenant_id="portfolio", case_id="case-owner")) == 1


def test_shadow_coordinator_reports_overrun_and_checks_cancellation(monkeypatch):
    from src.app.services.recommendation_core.cancellation import (
        RecommendationCancellation,
        RecommendationCancelled,
    )
    import pytest

    db = _db()
    envelope = TurnEnvelope.from_suggest_params(
        query="help", uid="buyer", tenant_id="portfolio", trace_id="trace-deadline",
    )
    response = CoreResponse(envelope=envelope)
    ticks = iter((10.0, 10.2))
    monkeypatch.setattr(
        "src.app.services.procurement_decision_coordinator.time.perf_counter",
        lambda: next(ticks),
    )
    monkeypatch.setenv("PROCUREMENT_DECISION_SHADOW_DEADLINE_MS", "100")
    result = ProcurementDecisionCoordinator(db, envelope).evaluate(lambda: response)
    assert result.extras["procurement_decision_coordinator"]["deadline_status"] == (
        "exceeded_observed"
    )

    cancellation = RecommendationCancellation.with_timeout(10)
    cancellation.cancel("buyer_disconnected")
    cancelled_envelope = TurnEnvelope.from_suggest_params(
        query="help", uid="buyer", tenant_id="portfolio", trace_id="trace-cancelled",
        cancellation=cancellation,
    )
    calls = []
    with pytest.raises(RecommendationCancelled):
        ProcurementDecisionCoordinator(db, cancelled_envelope).evaluate(
            lambda: calls.append("should-not-run") or response,
        )
    assert calls == []


def test_inventory_tool_scope_receipt_is_persisted_as_decision_stage(monkeypatch):
    from src.app.services.inventory_source import stock_levels
    from src.app.services import commerce_catalog

    db = _db()
    state = ProcurementCaseState(case_id="case-inventory", revision=1, objective="fleet")
    envelope = TurnEnvelope.from_suggest_params(
        query="what is available", uid="buyer", tenant_id="portfolio",
        trace_id="trace-inventory",
        session={"procurement_case_state": state.model_dump(mode="json")},
    )
    response = CoreResponse(envelope=envelope, lane="SEARCH")
    response.extras["procurement_case_state"] = state.model_dump(mode="json")
    response.stage_results = [StageResult(stage="commercial", status="ok")]
    monkeypatch.setattr(commerce_catalog, "catalog_enabled", lambda: False)

    def execute():
        assert stock_levels(["SKU-1"], tenant_id="portfolio", legacy_fn=lambda _: {"SKU-1": 4})["SKU-1"] == 4
        return response

    coordinator = ProcurementDecisionCoordinator(db, envelope)
    result = coordinator.evaluate(execute)
    coordinator.persist(result)
    stored = load_decision_runs(db, tenant_id="portfolio", case_id="case-inventory")[0]
    inventory = next(row for row in stored.stage_receipts if row.stage == "inventory_source")
    assert inventory.tool_selection_receipts[0]["capability"] == "inventory_availability"
    assert inventory.tool_selection_receipts[0]["outcome"] == "selected"
