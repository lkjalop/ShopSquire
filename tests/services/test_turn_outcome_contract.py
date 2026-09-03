import ast
from dataclasses import replace
from pathlib import Path

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_outcome import TurnFacts, finalize_turn_decision
from src.app.services.recommendation_core.turn_router import DEFAULT_DECISION, route_turn_outcome


def _envelope(query: str) -> TurnEnvelope:
    return TurnEnvelope.from_suggest_params(
        query=query,
        uid="outcome-contract",
        tenant_id="default",
        currency="AUD",
    )


def test_every_exit_recovers_canonical_total_budget_and_quantity():
    envelope = _envelope("I need 10 laptops with a total budget of AUD 30,000")
    branch = replace(DEFAULT_DECISION, quantity=10, budget_scope="unknown")

    outcome = finalize_turn_decision(branch, envelope)

    assert outcome.facts.quantity == 10
    assert outcome.facts.budget_scope == "total"
    assert outcome.facts.total_budget_cents == 3_000_000
    assert outcome.decision.total_budget_cents == 3_000_000


def test_facts_recover_enterprise_quantity_without_a_router_decision():
    envelope = _envelope("Buy 200 CRM seats with a total annual budget of AUD 120,000")

    facts = TurnFacts.from_envelope(envelope)

    assert facts.quantity == 200
    assert facts.commercial_terms.quantity == 200
    assert facts.budget_scope == "total"


def test_unseen_entity_frame_survives_as_a_validated_semantic_role():
    envelope = _envelope("Procure AsterCAD for 40 designers under AUD 100,000")
    branch = replace(DEFAULT_DECISION, model_proposal={
        "entity_frame": {
            "identity": "AsterCAD",
            "buyer_span": "AsterCAD",
            "entity_category": "software",
            "turn_role": "PROCURE_SUBJECT",
            "confidence": 0.91,
        },
    })

    outcome = finalize_turn_decision(branch, envelope)

    assert outcome.semantic.entity.identity == "AsterCAD"
    assert outcome.decision.subject_role == "PROCURE_SUBJECT"


def test_model_cannot_invent_entity_identity():
    envelope = _envelope("Procure AsterCAD")
    branch = replace(DEFAULT_DECISION, model_proposal={
        "entity_frame": {
            "identity": "Invented ERP",
            "entity_category": "software",
            "turn_role": "PROCURE_SUBJECT",
        },
    })
    outcome = finalize_turn_decision(branch, envelope)
    assert outcome.semantic.entity.identity is None
    assert outcome.decision.subject_role == "PROCURE_SUBJECT"


def test_public_outcome_boundary_returns_the_full_reduced_contract():
    outcome = route_turn_outcome(
        None,
        _envelope("I need 10 laptops with a total budget of AUD 30,000"),
        llm_fn=lambda *_args: "",
    )

    assert outcome.decision.subject_role == "PROCURE_SUBJECT"
    assert outcome.facts.quantity == 10
    assert outcome.facts.total_budget_cents == 3_000_000


def test_production_modules_do_not_construct_turn_decisions_outside_router():
    root = Path(__file__).resolve().parents[2] / "src" / "app"
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "turn_router.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "TurnDecision":
                    violations.append(f"{path.relative_to(root)}:{node.lineno}")
    assert violations == []

    router_source = (
        root / "services" / "recommendation_core" / "turn_router.py"
    ).read_text(encoding="utf-8-sig")
    assert router_source.count("TurnDecision(") == 1
