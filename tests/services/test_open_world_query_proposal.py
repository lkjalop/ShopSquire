import json
from concurrent.futures import Future

from src.app.services.case_research_plan import build_case_research_plan
from src.app.services import open_world_query_proposal as subject
from src.app.services.open_world_query_proposal import (
    consume_open_world_query_proposal,
    propose_open_world_queries,
)


def _plan():
    plan = build_case_research_plan(
        "Can this laptop run coupled FEA and CFD simulations?", allow_open_world=True,
    )
    assert plan is not None
    return plan


def test_local_model_can_expand_vocabulary_but_gains_no_authority():
    result = {
        "interpretations": ["coupled finite element and computational fluid dynamics"],
        "shared_concepts": ["multiphysics simulation"],
        "divergent_axes": ["named solver", "vendor certification"],
        "queries": [
            {"axis": "concept_and_software", "query": "FEA CFD multiphysics solver official documentation"},
            {"axis": "requirements_and_compatibility", "query": "FEA CFD solver system requirements compatibility"},
            {"axis": "support_and_constraints", "query": "FEA CFD solver certified hardware support matrix"},
        ],
    }
    planned, receipt = propose_open_world_queries(
        _plan(), model_fn=lambda prompt, timeout: json.dumps(result),
    )

    assert receipt["status"] == "accepted"
    assert receipt["authority"] == "discovery_proposal_only"
    assert len(planned.discovery_queries) == 3
    assert planned.external_calls == 0
    assert planned.authority == "proposal_only"


def test_unanchored_or_hardware_inventing_model_output_falls_back():
    original = _plan()
    bad = {
        "interpretations": ["unrelated"], "shared_concepts": ["unrelated"],
        "queries": [
            {"axis": "concept_and_software", "query": "unrelated vendor documentation"},
            {"axis": "requirements_and_compatibility", "query": "unrelated 64GB requirements"},
        ],
    }
    planned, receipt = propose_open_world_queries(
        original, model_fn=lambda prompt, timeout: json.dumps(bad),
    )

    assert receipt["status"] == "rejected_or_unavailable"
    assert planned.discovery_queries == original.discovery_queries
    assert receipt["authority"] == "none"


def test_model_timeout_or_invalid_json_falls_back_without_hanging_contract():
    original = _plan()
    planned, receipt = propose_open_world_queries(
        original, model_fn=lambda prompt, timeout: "not-json", timeout_s=1,
    )
    assert planned == original
    assert receipt["status"] == "rejected_or_unavailable"


def test_model_timeout_falls_back_without_stranding_the_buyer():
    original = _plan()

    def timed_out(_prompt: str, _timeout_s: float) -> str:
        raise TimeoutError("local model deadline exceeded")

    planned, receipt = propose_open_world_queries(
        original, model_fn=timed_out, timeout_s=1,
    )

    assert planned == original
    assert receipt["status"] == "rejected_or_unavailable"
    assert receipt["reason"] == "TimeoutError"
    assert receipt["authority"] == "none"


def test_incomplete_shadow_never_blocks_the_consent_request(monkeypatch):
    original = _plan()
    pending: Future = Future()
    monkeypatch.setitem(subject._SHADOW_FUTURES, original.plan_id, pending)

    planned, receipt = consume_open_world_query_proposal(original)

    assert planned == original
    assert receipt["status"] == "scheduled_shadow"
    assert receipt["model_calls"] == 0
    subject._SHADOW_FUTURES.pop(original.plan_id, None)


def test_completed_valid_shadow_can_improve_the_later_discovery_plan(monkeypatch):
    original = _plan()
    proposed = original.model_copy(update={
        "discovery_queries": [
            original.discovery_queries[0].model_copy(update={"query": "FEA CFD solver docs"}),
            original.discovery_queries[1],
        ],
    })
    ready: Future = Future()
    ready.set_result((proposed, {
        "status": "accepted", "model_calls": 1,
        "authority": "discovery_proposal_only",
    }))
    monkeypatch.setitem(subject._SHADOW_FUTURES, original.plan_id, ready)

    planned, receipt = consume_open_world_query_proposal(original)

    assert planned.discovery_queries[0].query == "FEA CFD solver docs"
    assert receipt["status"] == "accepted_shadow"
    assert original.plan_id not in subject._SHADOW_FUTURES


def test_completed_unconsumed_shadow_results_are_bounded(monkeypatch):
    monkeypatch.setenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "1")
    original = _plan()
    monkeypatch.setattr(subject, "_SHADOW_MAX_RETAINED", 4)
    subject._SHADOW_FUTURES.clear()
    for index in range(4):
        ready: Future = Future()
        ready.set_result((original, {"status": "accepted", "model_calls": 1}))
        subject._SHADOW_FUTURES[f"stale-{index}"] = ready
    pending: Future = Future()
    monkeypatch.setattr(subject, "_submit_shadow", lambda _plan: pending)

    receipt = subject.schedule_open_world_query_proposal(original)

    assert receipt["status"] == "scheduled_shadow"
    assert len(subject._SHADOW_FUTURES) <= 2
    subject._SHADOW_FUTURES.clear()
