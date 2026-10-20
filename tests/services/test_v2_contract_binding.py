import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ShoppingCase
from src.app.services import case_contract_binding as binding
from src.app.services.recommendation_core import core
from src.app.services.recommendation_core.envelope import TurnEnvelope, CoreResponse


@pytest.fixture
def state(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    from src.app.services.procurement_decision_coordinator import ProcurementDecisionCoordinator

    monkeypatch.setattr(ProcurementDecisionCoordinator, "persist", lambda *args: None)
    with Session(engine) as db:
        db.add(ShoppingCase(case_id="case", tenant_id="tenant", uid="buyer", revision=1))
        db.commit()
        contract = binding.available_contracts()[0]
        selected = binding.select_case_contract(
            db,
            tenant_id="tenant",
            case_id="case",
            uid="buyer",
            expected_revision=1,
            contract_id=contract.id,
            context=contract.context,
        )
        db.commit()
        env = TurnEnvelope.from_suggest_params(
            query="Find a product",
            uid="buyer",
            tenant_id="tenant",
            session={"case_anchor": {"case_id": "case", "revision": 2}},
        )
        yield db, env, selected
    engine.dispose()


def test_selected_contract_cannot_bypass_semantic_stage(state, monkeypatch):
    db, env, _ = state
    monkeypatch.setattr(
        core, "_recommend_turn", lambda *a, **k: CoreResponse(envelope=env, message="Qualified!")
    )
    result = core.recommend_turn(db, env)
    assert result.message != "Qualified!"
    assert result.extras["requirement_contract"]["failure_code"] == "selected_contract_not_compiled"
    assert result.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert result.extras["slate_disposition"] == "clear"


def test_selected_contract_requests_evidence_without_granting_fit(state):
    from src.app.services.recommendation_core.case_binding import bind_selected_contract_plan
    from src.app.services.recommendation_core.plan import Plan
    from src.app.services.semantic_resolution import validate_semantic_proposal
    db, env, selected = state
    result = bind_selected_contract_plan(db, Plan(), env)
    assert result.needs_concept_resolution
    assert result.semantic_authority_state == 'unresolved'
    assert result.external_research_authorized is False
    proposal = dict(result.semantic_proposal)
    proposal.pop('persisted_case_blocker')
    validated=validate_semantic_proposal(proposal,query=proposal['desired_outcome'])
    assert validated.outcome == 'valid'
    assert proposal['concepts'][0]['text'] == selected['context']['subject']


def test_contract_evidence_resolves_only_its_exact_subject_and_version():
    from types import SimpleNamespace
    from src.app.services.recommendation_core.case_binding import project_contract_workloads
    coverage=dict(compiled_complete=True,contract_id='unseen-v7',context=dict(subject='Unseen Tool',version='7'))
    stage=SimpleNamespace(compilation=SimpleNamespace(contract_coverage=coverage,requirements=[]),
        semantic_decision=SimpleNamespace(catalog_authority='permitted'),concept_data={})
    rows=[dict(requested_name=name,status='not_resolved') for name in
          ['Unseen Tool version 7','Unseen Tool version 8','Other Tool']]
    # Coverage metadata without compiled predicates never establishes a result.
    assert project_contract_workloads(rows,stage)==rows
    stage.compilation.requirements=[SimpleNamespace(model_dump=lambda:dict(attribute_key='ram_gb',value=32))]
    result=project_contract_workloads(rows,stage)
    assert result[0]['status']=='resolved'
    assert result[1:]==rows[1:]
    stage.semantic_decision.catalog_authority='blocked'
    assert project_contract_workloads(rows,stage)==rows


def test_revoked_binding_blocks_before_provider(state, monkeypatch):
    db, env, selected = state
    binding.revoke_case_contract(
        db,
        tenant_id="tenant",
        case_id="case",
        uid="buyer",
        expected_revision=2,
        binding_id=selected["binding_id"],
    )
    db.commit()
    calls = []
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: calls.append(True))
    result = core.recommend_turn(db, env)
    assert calls == []
    assert result.extras["requirement_contract"]["state"] == "revoked"


def test_revocation_during_core_execution_discards_result(state, monkeypatch):
    db, env, selected = state

    def execute(*a, **k):
        binding.revoke_case_contract(
            db,
            tenant_id="tenant",
            case_id="case",
            uid="buyer",
            expected_revision=2,
            binding_id=selected["binding_id"],
        )
        db.commit()
        return CoreResponse(envelope=env, message="Qualified!")

    monkeypatch.setattr(core, "_recommend_turn", execute)
    result = core.recommend_turn(db, env)
    assert result.message != "Qualified!"
    assert (
        result.extras["requirement_contract"]["failure_code"]
        == "case_contract_changed_during_research"
    )
    assert result.extras["requirement_contract"]["state"] == "revoked"


def test_evidence_stage_receives_only_database_selected_contract(state, monkeypatch):
    from src.app.services.recommendation_core.case_binding import resolve_bound_evidence_stage
    from src.app.services.recommendation_core import evidence_stage

    db, env, selected = state
    captured = {}

    def stage(*a, **kwargs):
        captured.update(kwargs)
        return "result"

    monkeypatch.setattr(evidence_stage, "resolve_semantic_evidence_stage", stage)
    assert resolve_bound_evidence_stage(db, None, env, None) == "result"
    assert captured["requirement_contract"].revision == selected["contract_revision"]
    assert captured["contract_context"].model_dump() == selected["context"]


def test_binding_hold_preserves_failure_and_stage_timing(state, monkeypatch):
    db, env, _ = state
    prior = CoreResponse(envelope=env, degraded=True, extras={"degraded_reason": "model_timeout"})
    prior.record_stage("route+intent", status="failed", latency_ms=121.5)
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: prior)
    result = core.recommend_turn(db, env)
    assert result.extras["degraded_reason"] == "model_timeout"
    assert result.stage_results[0].latency_ms == 121.5
    assert result.degraded


def test_unbound_exception_keeps_original_core_failure(state, monkeypatch):
    db, env, _ = state
    env.session.clear()

    def fail(*a, **k):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(core, "_recommend_turn", fail)
    result = core.recommend_turn(db, env)
    assert result.extras["degraded_reason"] == "core_error:TimeoutError"


def test_binding_receipt_crosses_compatibility_boundary(state, monkeypatch):
    from src.app.services.recommendation_core.legacy_adapter import to_legacy

    db, env, _ = state
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: CoreResponse(envelope=env))
    result = core.recommend_turn(db, env)
    payload = to_legacy(result)
    assert payload["requirement_contract"] == result.extras["requirement_contract"]
    assert payload["slate_disposition"] == "clear"
    step = next(row for row in payload["execution_steps"] if row["id"] == "case-contract-binding")
    assert step["output"] == payload["requirement_contract"]
    assert step["status"] == "blocked"


@pytest.mark.parametrize(
    "anchor", [dict(case_id="other", revision=2), dict(case_id="case", revision=1)]
)
def test_missing_or_stale_case_cannot_reach_provider(state, monkeypatch, anchor):
    db, env, _ = state
    env.session["case_anchor"] = anchor
    calls = []
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: calls.append(True))
    result = core.recommend_turn(db, env)
    assert not calls
    assert result.extras["semantic_resolution"]["catalog_authority"] == "blocked"


def test_facade_serves_binding_hold_without_legacy_fallback(state, monkeypatch):
    from src.app.services import recommendation_facade as facade

    db, env, _ = state
    monkeypatch.setenv("RECOMMEND_CORE_MODE", "primary")
    monkeypatch.setattr(facade, "_run_guard", lambda **kwargs: {"verdict": "allow"})
    monkeypatch.setattr(facade, "_read_session_slice", lambda *a, **k: env.session)
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: CoreResponse(envelope=env))
    outcome = facade.dispatch_recommendation_core_typed(
        db=db,
        redis=None,
        query=env.query,
        uid=env.uid,
        tenant_id=env.tenant_id,
        budget_min=None,
        budget_max=None,
        trace_id="binding-test",
        with_trace=lambda payload, _: payload,
        record_failure=lambda *a, **k: None,
    )
    assert outcome.status == "served"
    assert (
        outcome.payload["requirement_contract"]["failure_code"] == "selected_contract_not_compiled"
    )
    assert outcome.payload["products"] == []


def test_shadow_job_preserves_canonical_case_binding(state, monkeypatch):
    from src.app.services import recommendation_facade as facade

    db, env, _ = state
    captured = []
    monkeypatch.setenv("RECOMMEND_CORE_MODE", "shadow")
    monkeypatch.setattr(facade, "_read_session_slice", lambda *a, **k: {})
    monkeypatch.setattr(
        facade, "_enqueue_shadow", lambda *a, envelope, **k: captured.append(envelope.to_dict())
    )
    facade.dispatch_recommendation_core_typed(
        db=db,
        redis=None,
        query=env.query,
        uid=env.uid,
        tenant_id=env.tenant_id,
        budget_min=None,
        budget_max=None,
        trace_id="shadow-binding",
        canonical_case={"case_id": "case", "revision": 2},
        with_trace=lambda payload, _: payload,
        record_failure=lambda *a, **k: None,
    )
    restored = TurnEnvelope.from_dict(captured[0])
    assert restored.tenant_id == env.tenant_id
    assert restored.session["case_anchor"]["case_id"] == "case"
    assert restored.session["case_anchor"]["revision"] == 2


@pytest.mark.parametrize("with_product", [False, True])
def test_read_only_status_remains_usable_without_qualification_bypass(
    state, monkeypatch, with_product
):
    from src.app.services.recommendation_core.envelope import ProductCard

    db, env, _ = state
    result = CoreResponse(
        envelope=env,
        lane="PROCUREMENT",
        message="Your case is active.",
        products=[ProductCard(sku="fixture", title="Fixture", price_cents=100)]
        if with_product
        else [],
        extras={"case_operation": "status", "preserve_current_view": True, "state_changed": False},
    )
    monkeypatch.setattr(core, "_recommend_turn", lambda *a, **k: result)
    actual = core.recommend_turn(db, env)
    if with_product:
        assert (
            actual.extras["requirement_contract"]["failure_code"]
            == "selected_contract_not_compiled"
        )
        assert actual.products == []
    else:
        assert actual.message == "Your case is active."
        assert actual.extras["requirement_contract"]["state"] == "current"
        assert actual.extras["qualification_authority"] == "none"
