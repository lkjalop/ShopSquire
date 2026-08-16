from src.app.services.recommendation_core.semantic_belief_persistence import (
    SemanticBeliefPersistenceCommand,
    persist_computed_semantic_belief,
    semantic_case_id,
)


def _command(**changes):
    values = {
        "tenant_id": "tenant-a",
        "uid": "buyer-a",
        "session_epoch": "epoch-a",
        "trace_id": "trace-a",
        "prior_case_anchor": {},
        "requested_quantity": 30,
        "budget_scope": "per_unit",
        "total_budget_cents": None,
        "currency": "AUD",
        "semantic_decision": {"catalog_authority": "blocked"},
        "accepted_evidence": ({"claim_type": "minimum_requirements"},),
        "compiled_requirements": (),
    }
    values.update(changes)
    return SemanticBeliefPersistenceCommand(**values)


def test_semantic_case_identity_is_stable_and_retains_existing_case():
    generated = semantic_case_id(_command())
    assert generated.startswith("semantic-")
    assert generated == semantic_case_id(_command())
    assert semantic_case_id(_command(
        prior_case_anchor={"case_id": "case-retained"},
    )) == "case-retained"


def test_persistence_boundary_receives_computed_evidence_without_recomputing(monkeypatch):
    observed = {}
    monkeypatch.setattr(
        "src.app.services.conversation_case_state.ensure_case_state",
        lambda _db, **kwargs: observed.setdefault("case", kwargs),
    )

    def persist(_db, **kwargs):
        observed["belief"] = kwargs
        return {"status": "persisted", "persisted": True}

    monkeypatch.setattr(
        "src.app.services.semantic_belief_state.persist_semantic_belief", persist,
    )
    command = _command(compiled_requirements=({
        "attribute_key": "ram_gb", "operator": ">=", "value": 32,
    },))
    result = persist_computed_semantic_belief(object(), command)

    assert result.projection == {"status": "persisted", "persisted": True}
    assert observed["belief"]["semantic_decision"] == command.semantic_decision
    assert observed["belief"]["compiled_requirements"] == [
        {"attribute_key": "ram_gb", "operator": ">=", "value": 32},
    ]


def test_persistence_failure_is_visible_and_never_grants_authority(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.conversation_case_state.ensure_case_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db_down")),
    )
    result = persist_computed_semantic_belief(object(), _command())

    assert result.projection == {
        "status": "persistence_failed",
        "persisted": False,
        "error_type": "RuntimeError",
    }
    assert "catalog_authority" not in result.projection
