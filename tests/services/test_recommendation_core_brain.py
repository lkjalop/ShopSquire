"""Phase 4 step 3: the bounded brain — router clamps, plan validation, and THE ACCEPTANCE:
the corpus's three known_wrongs pass their expect_v2 assertions through the full core
(route → plan → execute → finalize → legacy adapter)."""
import dataclasses
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommend_parity_full import expectation_met
from src.app.services.recommendation_core.core import recommend_turn
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.legacy_adapter import to_legacy
from src.app.services.recommendation_core.plan import derive_plan, validate_plan
from src.app.services.recommendation_core.turn_router import TurnDecision, route_turn


@pytest.fixture()
def db():
    """Demo-shaped world: laptops sold (incl. 120Hz gaming stock), servers NOT sold."""
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p1','LAP-1','MSI Thin 15in FHD 120Hz Gaming Laptop',169900,"
        "'{\"ram_gb\": 16, \"gpu_vram_gb\": 8, \"refresh_hz\": 120, "
        "\"storage_gb\": 512}','MSI'), "
        "('p2','LAP-2','Asus TUF 16in 120Hz Gaming Laptop',209900,"
        "'{\"ram_gb\": 32, \"gpu_vram_gb\": 12, \"refresh_hz\": 120, "
        "\"storage_gb\": 1024}','Asus')"))
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(s, node_handle="el-6-6")      # Laptops sold
    add_sold_node(s, node_handle="el-6-11-2")   # Gaming Laptops sold
    # per-product taxonomy truth — the retrieval index the core keys on
    upsert_classification(s, sku="LAP-1", node_handle="el-6-6", source="test", status="approved")
    upsert_classification(s, sku="LAP-2", node_handle="el-6-11-2", source="test", status="approved")
    yield s
    s.close()


def _route_stub(lane, handle, requirements=None, conf=0.9, refine=None):
    return lambda p, t: json.dumps({"lane": lane, "handle": handle,
                                    "requirements": requirements or {}, "confidence": conf,
                                    **({"refine": refine} if refine else {})})


def _env(q, **kw):
    kw.setdefault("currency", "USD")
    return TurnEnvelope.from_suggest_params(query=q, uid="u1", **kw)


@pytest.mark.parametrize(
    ("query", "concept", "question", "expected_quantity"),
    [
        (
            "I need 30 laptops capable for digital twin simulations for an engine.",
            "digital twin simulations",
            "Which simulation software, model scale and execution location must be supported?",
            30,
        ),
        (
            "Find 20 chairs made from iron birch for a hotel refurbishment.",
            "iron birch",
            "Does iron birch mean a certified wood species or a supplier trade name?",
            20,
        ),
        (
            "I need 30 laptops for Path of Exile end-game play.",
            "end-game",
            "Which resolution, target frame rate and network conditions matter?",
            30,
        ),
    ],
)
def test_unresolved_fit_blocks_procurement_before_catalog_retrieval(
    db, query, concept, question, expected_quantity,
):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "quantity": 30,
        "confidence": 0.86,
        "semantic_proposal": {
            "desired_outcome": "find twenty chairs for a hotel refurbishment",
            "concepts": [{
                "text": concept,
                "status": "unresolved",
                "material": True,
                "interpretations": ["wood species", "supplier trade name"],
            }],
            "evidence_questions": [{
                "question_id": "material_identity",
                "question": question,
                "purpose": "resolve_concept",
                "material": True,
            }],
            "proposed_action": "research_then_clarify",
            "confidence": 0.75,
        },
    }

    response = recommend_turn(
        db,
        _env(query),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.clarify[0]["reason"] == "external_research_consent_required"
    assert response.clarify[0]["id"] == "external_research_consent"
    assert "approved official sources" in response.clarify[0]["text"]
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert response.extras["research_trigger"]["should_execute_external_research"] is False
    assert response.extras["research_trigger"]["route"] in {
        "request_authorization", "request_buyer_evidence",
    }
    assert response.extras["case_anchor"]["case_id"].startswith("semantic-")
    assert response.extras["case_anchor"]["catalog_authority"] == "blocked"
    assert "catalog_recommendation" in response.extras["semantic_resolution"]["state_prevented"]
    assert "supplier_enquiry" in response.extras["semantic_resolution"]["state_prevented"]
    assert response.extras["requested_quantity"] == expected_quantity
    assert not any(item.stage.startswith("plan:") for item in response.stage_results)


def test_authorized_research_that_cannot_resolve_concept_then_asks_material_question(db):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.86,
        "semantic_proposal": {
            "desired_outcome": "find a suitable simulation workstation",
            "concepts": [{
                "text": "digital twin simulation",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "evidence_questions": [{
                "question_id": "software_or_standard",
                "question": "Which software, standard, or workflow version must be supported?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
            "proposed_action": "research_then_clarify",
            "confidence": 0.75,
        },
    }

    response = recommend_turn(
        db,
        _env(
            "Recommend a laptop for digital twin simulation; check approved official sources.",
            external_research_consent=True,
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.clarify[0]["reason"] == "unresolved_material_concept"
    assert response.clarify[0]["id"] == "software_or_standard"
    assert response.extras["semantic_resolution"]["residual_route"] == "ASK"


def test_five_turn_unfamiliar_workload_keeps_authority_consent_and_commercial_state(db):
    from src.app.services.clarification_state import build_pending_clarification

    initial_model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.9,
        "semantic_proposal": {
            "desired_outcome": "qualify a portable workstation for a mechanical-maintenance digital twin",
            "concepts": [{
                "text": "mechanical-maintenance digital twin",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "evidence_questions": [{
                "question_id": "software_or_standard",
                "question": "Which software and version must be supported?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
            "proposed_action": "research_then_clarify",
            "confidence": 0.88,
        },
    }
    first = recommend_turn(
        db,
        _env("Please recommend a laptop for simulating a digital twin for maintenance of mechanical machines."),
        llm_fn=lambda *_: json.dumps(initial_model),
    )
    assert first.products == []
    assert first.extras["semantic_resolution"]["catalog_authority"] == "blocked"

    pending = build_pending_clarification(
        first.clarify[0],
        original_query=first.envelope.query,
        trace_id="trace-1",
        semantic_resolution=first.extras["semantic_resolution"],
        case_anchor=first.extras["case_anchor"],
        external_research_consent=True,
    )
    answer_model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "requirements": {},
        "clarification_relation": "answer",
        "confidence": 0.93,
    }
    third = recommend_turn(
        db,
        _env(
            "Use the named engineering software running locally for maintenance simulation.",
            external_research_consent=True,
            clarification_answer={
                "question_id": "software_or_standard",
                "value": "Local engineering simulation with 3D visualisation.",
                "authority": "buyer_authored_candidate",
            },
            session={"pending_clarification": pending},
        ),
        llm_fn=lambda *_: json.dumps(answer_model),
    )
    assert third.products == []
    assert third.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    slot = third.extras["plan"]["research_plan"]["material_slots"][0]
    assert slot["answer_status"] == "candidate"
    assert "3D visualisation" in slot["answer_candidate"]

    pending = build_pending_clarification(
        third.clarify[0],
        original_query=third.envelope.query,
        trace_id="trace-3",
        semantic_resolution=third.extras["semantic_resolution"],
        external_research_consent=True,
        commercial_state={
            "quantity": 30,
            "total_budget_cents": 7_500_000,
            "currency": "AUD",
            "selected_sku": None,
        },
    )
    fifth = recommend_turn(
        db,
        _env(
            "Actually reduce it by 10 units, but I do not think it is powerful enough.",
            external_research_consent=True,
            session={
                "pending_clarification": pending,
                # A stale accepted snapshot must not outrank the active blocker.
                "semantic_resolution": {"catalog_authority": "permitted"},
            },
        ),
        llm_fn=lambda *_: json.dumps({
            **answer_model,
            "quantity": 10,
        }),
    )

    assert fifth.products == []
    assert fifth.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    quantity_op = next(
        item for item in fifth.extras["case_obligations"]
        if item["kind"] == "quantity_amendment"
    )
    assert quantity_op["proposed_value"] == 20
    assert quantity_op["authorization_granted"] is False


def test_material_capability_relation_blocks_when_model_omits_semantic_proposal(db):
    """The live router may omit the optional proposal; omission must not grant fit."""
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "quantity": 30,
        "confidence": 0.91,
    }

    response = recommend_turn(
        db,
        _env("Please recommend 30 laptops capable of digital twin simulations for an engine."),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert response.extras["case_anchor"]["kind"] == "semantic_qualification"
    assert response.extras["semantic_resolution"]["desired_outcome"].startswith("Please recommend")
    questions = [item["question"] for item in response.extras["semantic_resolution"]["questions"]]
    assert any("software" in item.lower() and "version" in item.lower() for item in questions)
    assert any("time-to-result" in item.lower() for item in questions)
    assert "catalog_recommendation" in response.extras["semantic_resolution"]["state_prevented"]


def test_material_relation_reaches_model_before_deterministic_fallback(db):
    calls = []

    def interpret(_prompt, _timeout):
        calls.append(True)
        return json.dumps({
            "lane": "SEARCH",
            "handle": "el-6-6",
            "confidence": 0.84,
            "semantic_proposal": {
                "desired_outcome": "qualify a machine-maintenance simulation workstation",
                "concepts": [{
                    "text": "machine-maintenance simulation",
                    "status": "unresolved",
                    "material": True,
                    "interpretations": [],
                }],
                "evidence_questions": [{
                    "question_id": "model_scale",
                    "question": "What simulation scale and time-to-result target is required?",
                    "purpose": "resolve_performance_target",
                    "material": True,
                }],
                "proposed_action": "research_then_clarify",
                "confidence": 0.84,
            },
        })

    decision = route_turn(
        db,
        _env("Recommend a laptop capable of machine-maintenance simulation."),
        llm_fn=interpret,
    )

    assert calls == [True]
    assert decision.source == "model"
    assert decision.semantic_proposal["desired_outcome"].startswith("qualify")


def test_model_outage_still_blocks_material_capability_fit(db):
    response = recommend_turn(
        db,
        _env("Recommend a laptop for simulating a digital twin model."),
        llm_fn=lambda _prompt, _timeout: "",
    )

    assert response.products == []
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"


def test_model_outage_cannot_reopen_catalog_behind_active_semantic_clarification(db):
    """A stale sold node must not outrank the current unresolved workload."""
    pending = {
        "question_id": "software_or_standard",
        "question": "Which software, standard, or workflow must be supported?",
        "state": "pending",
        "semantic_context": {
            "desired_outcome": (
                "qualify a portable workstation for a mechanical-maintenance digital twin"
            ),
            "catalog_authority": "blocked",
            "outcome": "needs_clarification",
            "concepts": [{
                "text": "mechanical-maintenance digital twin",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "questions": [{
                "question_id": "software_or_standard",
                "question": "Which software, standard, or workflow must be supported?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
        },
        "commercial_context": {
            "quantity": 30,
            "total_budget_cents": 7_500_000,
            "currency": "AUD",
        },
    }
    response = recommend_turn(
        db,
        _env(
            "The workflow runs locally for maintenance simulation and 3D visualisation.",
            external_research_consent=True,
            session={
                "pending_clarification": pending,
                "prior_node": "el-6-6",
                "accepted_constraints": {
                    "requirements": {"ram_gb": ((">=", 16),)},
                    "quantity": 30,
                    "total_budget_cents": 7_500_000,
                    "budget_scope": "total",
                },
                # This older permissive snapshot is intentionally stale.
                "semantic_resolution": {"catalog_authority": "permitted"},
            },
        ),
        llm_fn=lambda _prompt, _timeout: "",
    )

    assert response.products == []
    assert response.extras["slate_disposition"] == "clear"
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert response.extras["semantic_resolution"]["desired_outcome"].startswith("qualify")
    assert response.extras["decision"]["node_handle"] is None


def test_model_product_route_cannot_omit_active_semantic_authorization_hold(db):
    """Valid router JSON cannot erase a stricter server-held workload blocker."""
    pending = {
        "question_id": "software_or_standard",
        "question": "Which software, standard, or workflow must be supported?",
        "state": "active",
        "semantic_context": {
            "desired_outcome": (
                "qualify a portable workstation for a mechanical-maintenance digital twin"
            ),
            "catalog_authority": "blocked",
            "concepts": [{
                "text": "mechanical-maintenance digital twin",
                "query_span": "mechanical-maintenance digital twin",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "questions": [{
                "question_id": "software_or_standard",
                "question": "Which software, standard, or workflow must be supported?",
                "purpose": "resolve_compatibility",
                "material": True,
            }],
            "state_prevented": ["catalog_recommendation", "commerce_execution"],
        },
        "commercial_context": {
            "quantity": 30,
            "total_budget_cents": 7_500_000,
            "currency": "AUD",
        },
    }
    model = {
        "lane": "PROCUREMENT",
        "handle": "el-6-6",
        "requirements": {},
        "quantity": 30,
        "total_budget": 75_000,
        "budget_scope": "total",
        "subject_action": "continue",
        "confidence": 0.95,
        # Deliberately omit semantic_proposal, reproducing the live leak.
    }

    response = recommend_turn(
        db,
        _env(
            "I need about 30 of those and the total budget is AUD 75,000.",
            external_research_consent=True,
            session={
                "pending_clarification": pending,
                "prior_node": "el-6-6",
                "semantic_resolution": {"catalog_authority": "permitted"},
            },
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.extras["slate_disposition"] == "clear"
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert response.extras["semantic_resolution"]["desired_outcome"].startswith("qualify")


def test_model_outage_on_ordinary_query_is_typed_and_visibly_degraded(db):
    response = recommend_turn(
        db,
        _env("Show me ordinary work laptops."),
        llm_fn=lambda _prompt, _timeout: "",
    )

    assert response.degraded is True
    assert response.extras["router_outcome"]["status"] == "source_unavailable"
    assert response.extras["router_outcome"]["late_results_accepted"] is False
    assert response.extras["router_outcome"]["fallback_authority"] == "deterministic_only"


def test_unresolved_named_software_cannot_fall_through_to_generic_profile(db):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "use_cases": ["engineering_student"],
        "workload_entities": [{"kind": "software", "name": "Siemens NX 2025"}],
        "clarification_relation": "answer",
        "confidence": 0.92,
    }

    response = recommend_turn(
        db,
        _env(
            "Use Siemens NX 2025 locally for maintenance simulation.",
            external_research_consent=True,
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.clarify[0]["reason"] == "named_workload_evidence_unresolved"
    assert response.extras["workload_authorization"]["status"] == "blocked"
    assert "catalog_qualification" in response.extras["workload_authorization"]["state_prevented"]
    assert not any(item.stage.startswith("plan:") for item in response.stage_results)
    assert "generic profile" in response.message


def test_named_workload_without_consent_requests_research_before_catalog(db):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "use_cases": ["engineering_student"],
        "workload_entities": [{"kind": "software", "name": "Siemens NX 2025"}],
        "confidence": 0.9,
    }

    response = recommend_turn(
        db,
        _env("A laptop for Siemens NX 2025."),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.clarify[0]["missing_slots"] == ["external_research_consent"]
    assert "official sources" in response.message


def test_plan_and_core_share_the_research_authority_contract(db):
    """A partial deploy must not crash before ordinary catalog retrieval.

    The core immutably adds the request's research authority to its Plan.  If
    the Plan schema is older, ``dataclasses.replace`` raises and the facade can
    silently fall through to compatibility behavior.  Keep this deployment
    boundary under a direct contract test.
    """
    response = recommend_turn(
        db,
        _env("gaming laptop under 2000", external_research_consent=True),
        llm_fn=_route_stub("SEARCH", "el-6-11-2"),
    )

    assert response.grounding != "error"
    assert response.extras["plan"]["external_research_authorized"] is True
    assert response.extras["plan"]["plan_version"] == "core-v2-semantic"


def test_confirm_purchase_order_without_selected_sku_cannot_retrieve_or_commit(db):
    response = recommend_turn(
        db,
        _env("Confirm the purchase order."),
        llm_fn=_route_stub("PROCUREMENT", "el-6-6"),
    )

    assert response.products == []
    assert response.extras["case_obligations"][0]["kind"] == "buyer_commitment"
    assert response.extras["case_obligations"][0]["status"] == "blocked"
    assert response.extras["semantic_resolution"]["residual_route"] == "ASK"
    assert "purchase_order" in response.extras["semantic_resolution"]["state_prevented"]


def test_resolved_concept_shows_only_evidence_qualified_catalog_alternative(db, monkeypatch):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.9,
        "semantic_proposal": {
            "desired_outcome": "find a laptop for digital twin simulation",
            "concepts": [{
                "text": "digital twin simulation",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.8,
        },
    }
    evidence = {
        "selected": ["concept_resolution"],
        "legs": {"concept_resolution": {"data": {
            "status": "resolved",
            "normalized_evidence": [{
                "concept": "digital twin simulation",
                "status": "resolved",
                "claim": "The enrolled software profile requires an evidence-qualified device.",
                "claim_type": "minimum_requirements",
                "source_id": "tenant-vendor-docs",
                "source_record_id": "software-profile-1",
                "source_revision": "2026.08",
                "observed_at": "2026-08-05T00:00:00Z",
                "citation_id": "cite:software-profile-1:2026.08",
                "source_policy": {
                    "policy_version": "semantic-source-v1",
                    "review_status": "approved",
                    "reviewer_type": "independent_human",
                    "reviewed_by": "tenant-engineering-reviewer",
                    "licence": "tenant-authorized",
                    "trust_tier": "authoritative",
                    "allowed_claim_types": ["minimum_requirements"],
                    "freshness_status": "fresh",
                },
            }],
            "catalog_qualifications": [{
                "sku": "LAP-1",
                "alignment_status": "alternative",
                "evidence_refs": ["cite:software-profile-1:2026.08"],
            }],
        }}},
        "citations": [],
        "source_health": "healthy",
        "ms": 4,
    }
    monkeypatch.setattr(
        "src.app.services.evidence_orchestrator.gather_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    response = recommend_turn(
        db,
        _env(
            "Find a laptop for digital twin simulation.",
            external_research_consent=True,
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert [item.sku for item in response.products] == ["LAP-1"], response.extras
    assert response.extras["catalog_qualification_candidates"] == ["LAP-1"]
    assert response.extras["catalog_alignment"]["status"] == "no_exact_catalog_match"
    assert response.extras["supplier_enquiry_option"] == {
        "status": "available_after_buyer_commitment",
        "auto_sent": False,
        "evidence_refs": ["cite:software-profile-1:2026.08"],
    }
    assert "qualified alternatives" in response.message.lower()


def test_authoritative_semantic_claims_compile_before_catalog_fit(db, monkeypatch):
    model = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.9,
        "semantic_proposal": {
            "desired_outcome": "find a laptop for an unfamiliar simulation workload",
            "concepts": [{
                "text": "unfamiliar simulation workload",
                "status": "unresolved",
                "material": True,
                "interpretations": [],
            }],
            "evidence_questions": [],
            "proposed_action": "research",
            "confidence": 0.86,
        },
    }
    source_policy = {
        "policy_version": "semantic-source-v1",
        "review_status": "approved",
        "reviewer_type": "independent_human",
        "reviewed_by": "tenant-engineering-reviewer",
        "licence": "tenant-authorized",
        "trust_tier": "authoritative",
        "allowed_claim_types": ["minimum_requirements"],
        "freshness_status": "fresh",
    }
    evidence = {
        "selected": ["concept_resolution"],
        "legs": {"concept_resolution": {"data": {
            "status": "resolved",
            "normalized_evidence": [{
                "concept": "unfamiliar simulation workload",
                "status": "resolved",
                "claim": "The approved requirements specify at least 32 GB RAM.",
                "claim_type": "minimum_requirements",
                "source_id": "official-requirements-provider",
                "source_record_id": "requirements-2026",
                "source_revision": "2026.08",
                "observed_at": "2026-08-06T00:00:00Z",
                "citation_id": "cite:requirements-2026:2026.08",
                "source_policy": source_policy,
            }],
            "claims": [{
                "need_id": "minimum-memory",
                "subject_span": "unfamiliar simulation workload",
                "claim_type": "minimum_requirements",
                "status": "accepted",
                "source_id": "official-requirements-provider",
                "source_record_id": "requirements-2026:ram",
                "observed_at": "2026-08-06T00:00:00Z",
                "confidence": 0.94,
                "attribute_key": "ram_gb",
                "operator": ">=",
                "value": 32,
                "unit": "GB",
                "authority": "official_requirements",
                "lineage_root": "official-requirements-provider",
            }],
            "catalog_qualifications": [],
        }}},
        "citations": [],
        "source_health": "healthy",
        "ms": 4,
    }
    monkeypatch.setattr(
        "src.app.services.evidence_orchestrator.gather_evidence",
        lambda *_args, **_kwargs: evidence,
    )

    response = recommend_turn(
        db,
        _env(
            "Find a laptop for an unfamiliar simulation workload.",
            external_research_consent=True,
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert [item.sku for item in response.products] == ["LAP-2"]
    assert response.products[0].fit["overall"] == "meets"
    assert response.extras["decision"]["requirements"]["ram_gb"] == [[">=", 32.0]]
    compilation = response.extras["semantic_requirement_compilation"]
    assert compilation["status"] == "accepted"
    assert compilation["compiled_requirements"][0]["attribute_key"] == "ram_gb"
    assert compilation["rejected_claims"] == []
    assert response.extras["catalog_alignment"]["status"] == "qualified_catalog_match"


def test_ambiguous_workload_product_type_stops_before_retrieval(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-2-2-7-2-2")
    model = {
        "lane": "PROCUREMENT",
        "handle": "el-2-2-7-2-2",
        "quantity": 20,
        "total_budget": 55000,
        "budget_scope": "total",
        "use_cases": ["game_development"],
        "confidence": 0.9,
    }

    response = recommend_turn(
        db,
        _env("Equipment for a 20-person gaming studio, $55,000 total."),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.products == []
    assert response.clarify[0]["reason"] == "missing_material_product_type"
    assert {o["label"] for o in response.clarify[0]["options"]} == {
        "Gaming Laptops",
        "Gaming Headsets",
    }


def test_procurement_primary_shelf_excludes_capability_failures(db):
    model = {
        "lane": "PROCUREMENT",
        "handle": "el-6-11-2",
        "quantity": 2,
        "requirements": {
            "gpu_vram_gb": {"operator": ">=", "number": 12},
            "ram_gb": {"operator": ">=", "number": 32},
        },
        "use_cases": ["game_development"],
        "confidence": 0.9,
    }

    response = recommend_turn(
        db,
        _env("Two laptops for professional game development with 12 GB VRAM and 32 GB RAM"),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert [card.sku for card in response.products] == ["LAP-2"]
    assert response.extras["shelf"]["bands"][0]["id"] == "best_fit"
    assert response.extras["shelf"]["bands"][0]["skus"] == ["LAP-2"]


def test_compound_refine_and_explain_answers_from_authorized_fit(db):
    model = {
        "lane": "EXPLAIN",
        "handle": "el-6-11-2",
        "requirements": {
            "gpu_vram_gb": {"operator": ">=", "number": 12},
            "ram_gb": {"operator": ">=", "number": 32},
        },
        "use_cases": ["game_development"],
        "confidence": 0.9,
    }

    response = recommend_turn(
        db,
        _env("I need at least 12 GB VRAM and 32 GB RAM. Why is the better fit?"),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.lane == "FILTER"
    assert response.extras["secondary_lanes"] == ["EXPLAIN"]
    assert response.extras["explanation"]["sku"] == "LAP-2"
    assert "Why Asus TUF" in response.message
    assert "32 GB" in response.message
    assert "12 GB" in response.message
    assert "meets all" not in response.message


def test_compound_explain_stays_anchored_to_persisted_cart_product(db):
    """An uncertain model cannot replace the buyer's one persisted cart selection."""
    model = {
        "lane": "EXPLAIN",
        "handle": "el-6-11-2",
        "requirements": {
            "gpu_vram_gb": [">=", 12],
            "ram_gb": [">=", 32],
        },
        "quantity": 30,
        "subject_action": "uncertain",
        "procurement_context": "current_order",
        "confidence": 0.9,
    }
    session = {
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["LAP-1", "LAP-2"],
        "accepted_constraints": {
            "exact_product_sku": "LAP-2",
            "product_selection_authority": "persisted_cart",
            "quantity": 1,
            "requirements": {
                "gpu_vram_gb": [[">=", 12]],
                "ram_gb": [[">=", 32]],
            },
        },
        "semantic_resolution": {
            "outcome": "proceed_catalog",
            "catalog_authority": "permitted",
            "desired_outcome": "simulate mechanical-machine maintenance",
            "interpretation_confidence": 0.83,
            "material_unknowns": [],
        },
        "semantic_requirement_compilation": {
            "status": "accepted",
            "compiled_requirements": [
                {
                    "attribute_key": "gpu_vram_gb",
                    "operator": ">=",
                    "value": 12,
                    "unit": "GB",
                    "source_claim_ids": ["official:vram"],
                },
                {
                    "attribute_key": "ram_gb",
                    "operator": ">=",
                    "value": 32,
                    "unit": "GB",
                    "source_claim_ids": ["official:ram"],
                },
            ],
            "commercial_authority_granted": False,
        },
    }

    response = recommend_turn(
        db,
        dataclasses.replace(
            _env_session(
                "Why is this a good choice? I need about 30 of those in 2 days.",
                session,
            ),
            currency="USD",
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(model),
    )

    assert response.extras["decision"]["exact_product_sku"] == "LAP-2"
    assert [card.sku for card in response.products] == ["LAP-2"]
    assert response.extras["explanation"]["sku"] == "LAP-2"
    assert response.extras["explanation"]["fit_ledger"]
    assert all(row["observed_source"] == "catalog_attribute" for row in response.extras["explanation"]["fit_ledger"])
    assert response.extras["explanation"]["workload_summary"] == (
        "simulate mechanical-machine maintenance"
    )
    assert response.extras["explanation"]["qualification_scope"] == "bounded_requirements"
    assert {
        ref
        for row in response.extras["explanation"]["fit_ledger"]
        for ref in row["requirement_evidence_refs"]
    } == {"official:vram", "official:ram"}
    assert "simulate mechanical-machine maintenance" in response.message
    assert "32 GB" in response.message and "12 GB" in response.message
    assert "meets all" not in response.message
    assert not any(question.get("id") == "ask_budget" for question in response.clarify)


def test_deadline_preview_is_unknown_without_date_qualified_arrival_evidence():
    from src.app.services.recommendation_core.core import _deadline_feasibility_from_preview

    result = _deadline_feasibility_from_preview(
        quantity=30,
        horizon_days=2,
        availability={
            "inventory_snapshot": {
                "local_atp": 3,
                "transferable": 27,
                "unconfirmed_shortfall": 0,
                "source_version": "atp-42",
            },
        },
    )

    assert result["feasibility"] == "unknown"
    assert result["quantity_confirmed_by_deadline"] == 0
    assert result["unknown_quantity"] == 30
    assert result["human_review_required"] is True
    assert "arrival_evidence_missing" in result["reason_codes"]


def test_deadline_preview_uses_only_explicit_dated_supply_lines():
    from src.app.services.recommendation_core.core import _deadline_feasibility_from_preview

    result = _deadline_feasibility_from_preview(
        quantity=10,
        horizon_days=2,
        availability={
            "inventory_snapshot": {
                "source_version": "atp-43",
                "supply_lines": [
                    {"source_ref": "local_atp", "quantity": 4, "status": "confirmed",
                     "arrival_max": "2026-08-09T00:00:00+00:00",
                     "authority": "dated_atp"},
                    {"source_ref": "supplier:SUP-1", "quantity": 6, "status": "unconfirmed",
                     "arrival_max": "2026-08-09T00:00:00+00:00",
                     "authority": "supplier_enquiry"},
                ],
            },
        },
    )

    assert result["quantity_confirmed_by_deadline"] == 4
    assert result["unknown_quantity"] == 6
    assert result["feasibility"] == "unknown"


# ── router clamps ─────────────────────────────────────────────────────────────

def test_router_bounded_fallback_on_garbage_model(db):
    for bad in ("", "not json", json.dumps({"lane": "INVENTED_LANE"})):
        d = route_turn(db, _env("gaming laptop"), llm_fn=lambda p, t, b=bad: b)
        assert d.lane == "SEARCH" and d.source.startswith("fallback:")
        assert d.requirements == {} and d.use_cases == ("gaming",)


def test_router_records_bounded_proposal_and_authorization_changes(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "invented-root-node",
        "requirements": {"invented_spec": [">=", 999999], "ram_gb": [">=", 999999]},
        "use_cases": ["invented_workload"],
        "refine": {"brand": "Invented Brand", "exclude_brand": "Invented Brand"},
        "quantity": 999999999, "budget_scope": "unbounded",
        "subject_action": "delete", "procurement_context": "auto_send",
    })

    decision = route_turn(db, _env("gaming laptop"), llm_fn=lambda _p, _t: raw)

    assert decision.model_proposal["handle"] == "invented-root-node"
    assert decision.node_handle is None
    assert decision.requirements == {}
    # The invented model workload is rejected, while the buyer's exact phrase
    # independently resolves to the enrolled local gaming profile.
    assert decision.use_cases == ("gaming",)
    assert decision.brand_filter is None and decision.exclude_brand is None
    assert decision.quantity is None
    assert {"handle:clamped", "requirements:clamped", "use_cases:clamped", "brand:clamped",
            "exclude_brand:clamped", "quantity:clamped"}.issubset(
        set(decision.authorization_changes))


def test_legacy_adapter_exposes_truthful_execution_boundaries(db):
    response = recommend_turn(db, _env("gaming laptop"), llm_fn=_route_stub(
        "SEARCH", "el-6-11-2", {"gpu_vram_gb": [">=", 8]}))

    steps = to_legacy(response)["execution_steps"]

    assert steps[0]["kind"] == "model" and steps[0]["authority"] == "proposes"
    assert steps[1]["kind"] == "gate" and steps[1]["authority"] == "authorizes"
    assert any(step["authority"] == "executes" for step in steps)
    assert steps[-1]["authority"] == "presents"


def test_material_bulk_budget_ambiguity_clarifies_before_retrieval(db):
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": "el-6-6", "requirements": {},
        "use_cases": ["general_office"], "quantity": 20,
        "total_budget": None, "budget_scope": None,
    })
    response = recommend_turn(
        db,
        _env("I need 20 laptops, budget 41000", budget_max=41000),
        llm_fn=lambda _p, _t: raw,
    )

    assert response.products == []
    assert response.clarify[0]["reason"] == "missing_material_budget_scope"
    assert response.extras["stage_results"][-1]["stage"] == "clarify:pre_retrieval"
    assert "per item" in response.message.lower() and "total" in response.message.lower()


def test_non_product_service_scope_gets_bounded_explanation(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": None, "wanted_category": None,
        "request_scope": "service_or_place", "requirements": {}, "confidence": 0.0,
    })
    resp = recommend_turn(db, _env("find a pizza place near me"), llm_fn=lambda p, t: raw)

    assert resp.products == []
    assert resp.extras["decision"]["request_scope"] == "service_or_place"
    assert resp.extras["unsupported_scope"]["kind"] == "service_or_place"
    assert "local services or places" in resp.message
    assert "catalog match" not in resp.message.lower()


def test_service_scope_cannot_hide_a_grounded_product(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-6", "wanted_category": None,
        "request_scope": "service_or_place", "requirements": {}, "confidence": 0.9,
    })
    decision = route_turn(db, _env("show me laptops"), llm_fn=lambda p, t: raw)

    assert decision.node_handle == "el-6-6"
    assert decision.request_scope == "product"


def test_recommendation_excludes_products_outside_store_currency(db):
    from sqlalchemy import text as _t
    from src.app.services.taxonomy_registry import upsert_classification

    db.execute(_t(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, brand) VALUES "
        "('p-aud','LAP-AUD','AUD Gaming Laptop',120000,'AUD',"
        "'{\"ram_gb\": 32, \"gpu_vram_gb\": 12}','Other')"
    ))
    upsert_classification(db, sku="LAP-AUD", node_handle="el-6-11-2",
                          source="test", status="approved")

    resp = recommend_turn(
        db, _env("gaming laptop", currency="USD"),
        llm_fn=_route_stub("SEARCH", "el-6-11-2"),
    )

    assert resp.products
    assert {product.currency for product in resp.products} == {"USD"}
    assert resp.extras["currency_policy"] == {
        "currency": "USD", "excluded_mismatched": 1, "fx_applied": False,
    }


def test_router_drops_invented_handle_keeps_registry_real(db):
    # an INVENTED handle is dropped (registry clamp)…
    d = route_turn(db, _env("gaming laptop"), llm_fn=_route_stub("SEARCH", "not-a-node-99"))
    assert d.lane == "SEARCH" and d.node_handle is None
    # …but a registry-real handle outside the candidate list is KEPT for routing — queries
    # name intents, not product titles; refusal safety lives in sells_within, not this clamp.
    # And the PLATFORM decides refusal from the node: the model hedging lane=SEARCH on a
    # not-sold node still refuses (the live forklift finding — the model can't know the
    # sold set, so it doesn't get to decide)
    d = route_turn(db, _env("do you sell forklifts?"), llm_fn=_route_stub("SEARCH", "bi-18"))
    assert d.node_handle == "bi-18" and d.lane == "OFF_CATALOG" and d.refusal_granted


def test_router_clamps_requirements(db):
    d = route_turn(db, _env("laptop for gaming at 144fps"), llm_fn=_route_stub(
        "SEARCH", None, {"refresh_hz": [">=", 144], "invented_key": [">=", 5],
                         "ram_gb": ["~=", 16], "gpu_vram_gb": [">=", 9999]}))
    assert d.requirements == {"refresh_hz": [(">=", 144.0)]}   # bad key/op/bounds all dropped


def test_router_separates_delivery_window_from_product_fit_requirements(db):
    raw = json.dumps({
        "lane": "PROCUREMENT",
        "handle": "el-6-11-2",
        "requirements": {"delivery_days": "2"},
        "operational_constraints": {
            "delivery_window_days": 2,
            "payment_plan": "balance_after_confirmation",
        },
        "quantity": 80,
        "subject_action": "continue",
        "procurement_context": "current_order",
        "confidence": 0.9,
    })

    decision = route_turn(
        db,
        _env("Keep the order. Delivery within two business days; deposit now and balance later."),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.requirements == {}
    assert decision.operational_constraints == {
        "delivery_window_days": 2,
        "payment_plan": "balance_after_confirmation",
    }
    assert decision.model_proposal["requirements"]["delivery_days"] == "2"


def test_explicit_delivery_and_deposit_survive_a_model_that_omits_optional_fields(db):
    raw = json.dumps({
        "lane": "PROCUREMENT",
        "handle": "el-6-11-2",
        "requirements": {},
        "subject_action": "continue",
        "procurement_context": "current_order",
        "confidence": 0.9,
    })

    decision = route_turn(
        db,
        _env("Keep this cart. Delivery within two business days; deposit now, balance later."),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.operational_constraints == {
        "delivery_window_days": 2,
        "payment_plan": "balance_after_confirmation",
    }


def test_core_uses_workload_as_primary_context_when_audience_is_also_present(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "requirements": {},
        "use_cases": ["game_development"], "audience_contexts": ["university"],
        "confidence": 0.9,
    })

    response = recommend_turn(
        db,
        _env("I study game development and need a laptop for engine builds"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert response.extras["intent"]["primary_use_case"] == "game_development"
    assert response.extras["decision"]["use_cases"] == ["game_development", "university"]
    assert response.extras["decision"]["audience_contexts"] == ["university"]
    assert response.extras["constraints_used"]["requirements"]["gpu_vram_gb"] == [[">=", 6.0]]
    assert "university general" not in response.message.lower()


def test_router_clamps_audience_context_independently(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "requirements": {},
        "use_cases": ["game_development", "university"],
        "audience_contexts": ["invented_audience", "university"],
        "confidence": 0.9,
    })

    decision = route_turn(
        db, _env("university game development laptop"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.use_cases == ("game_development", "university")
    assert decision.audience_contexts == ("university",)


def test_router_clamps_and_core_applies_game_development_variant(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "requirements": {},
        "use_cases": ["game_development"],
        "use_case_variant": "unreal_realtime",
        "confidence": 0.9,
    })

    response = recommend_turn(
        db, _env("laptop for complex Unreal Engine work"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert response.extras["decision"]["use_case_variants"] == {
        "game_development": "unreal_realtime"
    }
    requirements = response.extras["constraints_used"]["requirements"]
    assert requirements["gpu_vram_gb"] == [[">=", 8.0]]
    assert requirements["ram_gb"] == [[">=", 32.0]]
    assert requirements["storage_gb"] == [[">=", 1024.0]]


def test_router_drops_invented_use_case_variant(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "requirements": {},
        "use_cases": ["game_development"],
        "use_case_variants": {"game_development": "ultra_magic"},
        "confidence": 0.9,
    })

    decision = route_turn(db, _env("game development laptop"),
                          llm_fn=lambda _prompt, _timeout: raw)

    assert decision.use_case_variants == {}


def test_game_development_primary_slate_excludes_known_integrated_gpu_when_fit_exists(db):
    from src.app.services.taxonomy_registry import upsert_classification

    insert = text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) "
        "VALUES (:id, :sku, :name, :price, :specs, :brand)"
    )
    db.execute(insert, [
        {"id": "p-dev", "sku": "DEV-RTX", "name": "Creator RTX Laptop",
         "price": 220000, "brand": "Creator",
         "specs": json.dumps({"ram_gb": 32, "storage_gb": 1024,
                               "gpu_discrete": True, "gpu_vram_gb": 8})},
        {"id": "p-igpu", "sku": "DEV-IGPU", "name": "Integrated Graphics Laptop",
         "price": 120000, "brand": "Budget",
         "specs": json.dumps({"ram_gb": 32, "storage_gb": 1024,
                               "gpu_discrete": False})},
    ])
    upsert_classification(db, sku="DEV-RTX", node_handle="el-6-11-2",
                          source="test", status="approved")
    upsert_classification(db, sku="DEV-IGPU", node_handle="el-6-11-2",
                          source="test", status="approved")
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "requirements": {},
        "use_cases": ["game_development"], "confidence": 0.9,
    })

    response = recommend_turn(
        db,
        _env("laptop for game development"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert "DEV-RTX" in {product.sku for product in response.products}
    assert "DEV-IGPU" not in {product.sku for product in response.products}
    assert all((product.fit or {}).get("overall") == "meets" for product in response.products)


def test_refusal_needs_the_sold_set_not_the_model(db):
    # forklift: bi-18 offered by candidates, model proposes OFF_CATALOG, sold set grants it
    d = route_turn(db, _env("do you sell forklifts?"), llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    assert d.lane == "OFF_CATALOG" and d.refusal_granted
    # same proposal on an UNGROUNDED tenant → downgraded, never refused
    s2 = sessionmaker(bind=create_engine("sqlite://"))()
    d2 = route_turn(s2, _env("do you sell forklifts?"), llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    assert d2.lane == "SEARCH" and not d2.refusal_granted
    s2.close()
    # and a SOLD category can never be refused, whatever the model says
    d3 = route_turn(db, _env("gaming laptops"), llm_fn=_route_stub("OFF_CATALOG", "el-6-11-2"))
    assert d3.lane == "SEARCH" and not d3.refusal_granted


def test_off_catalog_null_handle_is_repaired_through_taxonomy_then_sellability(db, monkeypatch):
    """Candidate recall may miss an absent category, but the model still cannot authorize it."""
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.semantic_top_k",
        lambda wanted, *, top_k: [("bi-18", 0.8)],
    )
    raw = json.dumps({
        "lane": "OFF_CATALOG", "handle": None, "wanted_category": "forklifts",
        "requirements": {}, "confidence": 0.8,
    })
    decision = route_turn(db, _env("do you sell forklifts?"), llm_fn=lambda p, t: raw)

    assert decision.node_handle == "bi-18"
    assert decision.lane == "OFF_CATALOG" and decision.refusal_granted
    assert decision.source == "model+taxonomy_semantic"
    assert decision.requested_category_label == "forklifts"

    # The same bridge cannot turn a sold node into a refusal.
    sold_raw = json.dumps({
        "lane": "OFF_CATALOG", "handle": None, "wanted_category": "Laptops",
        "requirements": {}, "confidence": 0.8,
    })
    sold = route_turn(db, _env("do you sell laptops?"), llm_fn=lambda p, t: sold_raw)
    assert sold.node_handle == "el-6-6"
    assert sold.lane == "SEARCH" and not sold.refusal_granted


def test_off_catalog_semantic_repair_accepts_separated_unsold_leader(db, monkeypatch):
    """A distant sold neighbor must not veto a clearly separated unsold subject."""
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.semantic_top_k",
        lambda wanted, *, top_k: [("el-6-2", 0.76), ("el-6-11-2", 0.61)],
    )
    raw = json.dumps({
        "lane": "OFF_CATALOG", "wanted_category": "Computing > GPU Servers",
    })

    decision = route_turn(db, _env("quote rackmount accelerator servers"),
                          llm_fn=lambda _prompt, _timeout: raw)

    assert decision.node_handle == "el-6-2"
    assert decision.lane == "OFF_CATALOG" and decision.refusal_granted
    assert decision.source == "model+taxonomy_semantic"


def test_off_catalog_semantic_repair_abstains_on_ambiguous_sold_neighbor(db, monkeypatch):
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.semantic_top_k",
        lambda wanted, *, top_k: [("el-6-2", 0.71), ("el-6-11-2", 0.68)],
    )
    raw = json.dumps({
        "lane": "OFF_CATALOG", "wanted_category": "Computing > Accelerator Systems",
    })

    decision = route_turn(db, _env("quote accelerator systems"),
                          llm_fn=lambda _prompt, _timeout: raw)

    assert decision.node_handle is None
    assert decision.lane == "SEARCH" and not decision.refusal_granted


def test_off_catalog_exact_category_avoids_semantic_repair(db, monkeypatch):
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.semantic_top_k",
        lambda wanted, *, top_k: pytest.fail("exact taxonomy name must not use semantic repair"),
    )
    raw = json.dumps({
        "lane": "OFF_CATALOG", "handle": None, "wanted_category": "Computer Servers",
        "requirements": {}, "confidence": 0.95,
    })
    decision = route_turn(db, _env("quote rackmount GPU nodes"), llm_fn=lambda p, t: raw)
    assert decision.lane == "OFF_CATALOG" and decision.refusal_granted
    assert decision.node_handle == "el-6-2"
    assert decision.source == "model+taxonomy_exact"


def test_search_repairs_model_named_taxonomy_path(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": None,
        "wanted_category": "Electronics > Computers > Laptops",
        "request_scope": "product", "requirements": {},
        "refine": {"exclude_brand": "Apple"}, "confidence": 0.8,
    })
    decision = route_turn(db, _env("a good laptop but not Apple"), llm_fn=lambda p, t: raw)

    assert decision.node_handle == "el-6-6"
    assert decision.source == "model+taxonomy_exact"
    assert decision.exclude_brand == "Apple" or decision.exclude_brand is None


def test_procurement_accepts_registry_handle_from_category_slot(db):
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": None, "wanted_category": "el-6-6",
        "request_scope": "product", "requirements": {}, "quantity": 20,
        "confidence": 0.9,
    })
    decision = route_turn(
        db, _env("quote 20 work laptops"), llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.lane == "PROCUREMENT"
    assert decision.node_handle == "el-6-6"
    assert decision.node_path and "Laptops" in decision.node_path
    assert decision.source == "model+taxonomy_handle"


def test_fresh_quantity_free_workload_search_cannot_activate_procurement(db):
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": "el-6-6",
        "wanted_category": "Electronics > Computers > Laptops",
        "request_scope": "product",
        "requirements": {"gpu_tier": [{"op": "eq", "value": "discrete"}]},
        "use_cases": ["game_development"],
        "quantity": None,
        "subject_action": "switch",
        # A model may claim this, but only server-side workflow state can authorize it.
        "procurement_context": "current_order",
        "confidence": 0.9,
    })

    decision = route_turn(
        db,
        _env("professional Unreal Engine 5 game development laptop under AUD 3500"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.lane == "SEARCH"
    assert decision.node_handle is not None
    assert "game_development" in decision.use_cases


def test_stale_procurement_lane_without_consequential_state_cannot_reactivate(db):
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": "el-6-6",
        "requirements": {}, "quantity": None,
        "subject_action": "uncertain",
        "procurement_context": "current_order",
        "confidence": 0.9,
    })
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "accepted_constraints": {},
    }

    decision = route_turn(
        db,
        _env("professional game development laptop", session=session),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.lane == "SEARCH"


def test_typed_active_case_keeps_quantity_free_current_order_turn_in_procurement(db):
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": None,
        "requirements": {}, "quantity": None,
        "subject_action": "continue",
        "procurement_context": "current_order",
        "confidence": 0.9,
    })
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "procurement_case_state": {
            "case_id": "case-60", "revision": 1,
            "objective": "Unreal Engine fleet",
        },
    }

    decision = route_turn(
        db,
        _env("What is the best delivery approach?", session=session),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.lane == "PROCUREMENT"
    assert decision.procurement_context == "current_order"


def test_invalid_case_patch_is_visible_rejection_not_legacy_degradation(db, monkeypatch):
    from src.app.services import procurement_case_preflight

    def reject_patch(*_args, **_kwargs):
        raise ValueError("source_destination_not_found")

    monkeypatch.setattr(
        procurement_case_preflight, "apply_case_patches_before_evaluation", reject_patch,
    )
    raw = json.dumps({
        "lane": "PROCUREMENT", "handle": None,
        "requirements": {}, "quantity": None,
        "subject_action": "continue", "procurement_context": "current_order",
        "case_patches": [{
            "operation": "move_quantity", "path": "destinations", "quantity": 5,
            "from_ref": "Perth", "to_ref": "Sydney",
        }],
        "confidence": 0.9,
    })
    envelope = _env("Move 5 from Perth to Sydney", session={
        "active_workflow_lane": "PROCUREMENT",
        "session_epoch": "epoch-1",
        "procurement_case_state": {
            "case_id": "case-60", "revision": 1,
            "objective": "Unreal Engine fleet",
        },
    })

    response = recommend_turn(db, envelope, llm_fn=lambda _prompt, _timeout: raw)

    assert response.grounding == "unverified"
    assert response.extras["case_patch_application"] == {
        "status": "rejected",
        "reason": "source_destination_not_found",
        "state_changed": False,
        "commerce_authority": False,
    }
    assert "did not apply" in response.message.lower()


def test_full_laptop_intake_survives_model_case_patch_omissions(db):
    query = (
        "We need 60 engineering laptops for Unreal Engine, large CAD models and simulation. "
        "Send 40 to Sydney and 20 to Perth. At least 30 must arrive within four days. "
        "Budget is AUD 220,000 total."
    )
    raw = json.dumps({
        "lane": "PROCUREMENT",
        "handle": "el-6-6",
        "requirements": {},
        "quantity": 60,
        "total_budget": 220_000,
        "budget_scope": "total",
        "use_cases": ["game_development", "engineering_simulation"],
        "subject_action": "switch",
        "procurement_context": "new_order",
        # Simulate the observed live-model defect: only destinations were copied
        # into durable patches even though the top-level extraction was correct.
        "case_patches": [{
            "operation": "set",
            "path": "destinations",
            "value": [
                {"location_ref": "Sydney", "quantity": 40},
                {"location_ref": "Perth", "quantity": 20},
            ],
        }],
        "confidence": 0.9,
    })

    decision = route_turn(
        db, _env(query, currency="AUD"),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    by_path = {}
    for patch in decision.case_patches:
        by_path.setdefault(patch["path"], []).append(patch)

    assert by_path["requested_quantity"][0]["value"] == 60
    assert by_path["budget.amount_minor"][0]["value"] == 22_000_000
    assert by_path["budget.currency"][0]["value"] == "AUD"
    assert by_path["temporal.original_expression"][0]["value"] == "within four days"
    assert [patch["value"] for patch in by_path["workloads"]] == [
        "game_development", "engineering_simulation",
    ]
    assert decision.model_proposal["case_patches"] == [
        dict(patch) for patch in decision.case_patches
    ]


def test_procurement_plan_retrieves_before_advisory_handoff():
    decision = TurnDecision(
        lane="PROCUREMENT", node_handle="el-6-6", requirements={}, quantity=20,
    )

    assert derive_plan(decision).steps == ["retrieve", "handoff_procurement"]

    with_requirements = dataclasses.replace(
        decision, requirements={"ram_gb": ((">=", 16.0),)},
    )
    assert derive_plan(with_requirements).steps == [
        "retrieve", "fit_check", "handoff_procurement",
    ]


def test_inventory_plan_retrieves_then_explains_authoritative_stock():
    decision = TurnDecision(
        lane="INVENTORY", node_handle="el-6-6", requirements={},
    )

    assert derive_plan(decision).steps == ["retrieve", "inventory_summary"]


def test_currency_amount_cannot_authorize_model_proposed_quantity(db):
    raw = json.dumps({
        "lane": "FILTER", "handle": "el-6-6", "requirements": {},
        "quantity": 700, "total_budget": 700, "budget_scope": "per_unit",
        "subject_action": "continue", "confidence": 0.9,
    })
    decision = route_turn(
        db,
        _env(
            "keep it under $700 and prioritise reliable video calls",
            session={"prior_node": "el-6-6"},
        ),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert decision.quantity is None
    assert decision.budget_scope == "per_unit"


def test_procurement_turn_returns_authorized_slate_without_executing(db):
    payload = {
        "lane": "PROCUREMENT", "handle": "el-6-6", "requirements": {},
        "quantity": 20, "total_budget": 41000, "budget_scope": "total",
        "subject_action": "switch", "confidence": 0.9,
    }
    envelope = dataclasses.replace(
        _env("quote 20 laptops with an AUD 41000 total budget"),
        currency="USD", budget_max_cents=4_100_000,
    )

    response = recommend_turn(db, envelope, llm_fn=lambda _p, _t: json.dumps(payload))

    assert response.lane == "PROCUREMENT"
    assert response.products
    assert response.extras["requested_quantity"] == 20
    assert response.extras["execution_authority"] == "fulfillment_cases"
    assert response.extras["external_send_gate"] == "human_approval"
    assert response.extras["plan"]["steps"] == ["retrieve", "handoff_procurement"]
    assert all((product.price_cents or 0) <= 205_000 for product in response.products)


def test_nothing_from_brand_is_a_continuation_not_subject_switch(db):
    raw = json.dumps({
        "lane": "SEARCH", "handle": "el-6-6", "wanted_category": None,
        "request_scope": "product", "requirements": {}, "confidence": 0.8,
        "subject_action": "switch",
        "refine": {"brand": None, "prefer_brand": None,
                   "exclude_brand": None, "sort": None},
    })
    env = _env("nothing from MSI", session={
        "prior_node": "el-6-6",
        "accepted_constraints": {"budget_max_cents": 180000},
    })

    response = recommend_turn(db, env, llm_fn=lambda _prompt, _timeout: raw)

    assert response.extras["decision"]["exclude_brand"] == "MSI"
    assert response.extras["decision"]["subject_action"] == "continue"
    assert response.extras["constraints_used"]["budget_max_cents"] == 180000
    assert all(product.brand != "MSI" for product in response.products)


def test_off_catalog_distinct_lexical_category_avoids_semantic_repair(db, monkeypatch):
    monkeypatch.setattr(
        "src.app.services.taxonomy_embedding_index.semantic_top_k",
        lambda wanted, *, top_k: pytest.fail("distinct lexical category must not use semantic repair"),
    )
    raw = json.dumps({
        "lane": "OFF_CATALOG", "handle": None,
        "wanted_category": "Computers > Servers > GPU Servers",
        "requirements": {}, "confidence": 0.95,
    })
    decision = route_turn(db, _env("need rackmount GPU servers"), llm_fn=lambda p, t: raw)
    assert decision.lane == "OFF_CATALOG" and decision.refusal_granted
    assert decision.node_handle == "el-6-2"
    assert decision.source == "model+taxonomy_lexical"


def test_wrongful_refusal_guard_spec_turns_never_platform_refused(db):
    """Shadow census finding: fragmentary spec turns ('only ones with 16GB RAM or more')
    mapped to unsold component nodes and got platform-refused. Requirements present +
    model did NOT propose refusal -> never refuse; closest-match honesty instead."""
    d = route_turn(db, _env("only ones with 16GB RAM or more"),
                   llm_fn=_route_stub("FILTER", "el-7-12-3", {"ram_gb": [">=", 16]}))
    assert d.lane != "OFF_CATALOG" and not d.refusal_granted
    # but a model-PROPOSED refusal with requirements still refuses when the sold set grants
    # it ('$80k rack-mount A100 servers' can carry specs AND deserve refusal)
    d2 = route_turn(db, _env("five rack-mount A100 servers under $80k"),
                    llm_fn=_route_stub("OFF_CATALOG", "el-6-2", {"gpu_vram_gb": [">=", 40]}))
    assert d2.lane == "OFF_CATALOG" and d2.refusal_granted


def test_bare_software_purchase_still_refuses(db):
    """review #4: a BARE purchase ask for unsold software (no capability verb/use-case/reqs)
    must still get an honest refusal, not a blanket workload-strip to empty device search."""
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")   # sells laptops, NOT software
    d = route_turn(db, _env("do you sell photoshop licenses"),
                   llm_fn=_route_stub("OFF_CATALOG", "so-1"))
    # so-1 stands (no capability signal) → refusal gate grants (software not sold)
    assert d.node_handle == "so-1" and d.refusal_granted and d.lane == "OFF_CATALOG"


def test_budget_number_with_storage_unit_is_kept(db):
    # review #3: '1TB laptop under $1000' — storage_gb 1000 is a REAL spec, not the price
    d = route_turn(db, _env("1TB laptop under $1000", budget_max=1000),
                   llm_fn=_route_stub("SEARCH", "el-6-6", {"storage_gb": [">=", 1000]}))
    assert d.requirements.get("storage_gb") == [(">=", 1000.0)]
    # but a bare budget bleed is still dropped
    d2 = route_turn(db, _env("laptop under $1500", budget_max=1500),
                    llm_fn=_route_stub("SEARCH", "el-6-6", {"storage_gb": [">=", 1500]}))
    assert "storage_gb" not in d2.requirements


def test_budget_bleed_regression_battery(db):
    """review-8 root-cause 1: a PRICE the model mis-reads as a GB spec must be dropped even with
    a NATURAL-LANGUAGE budget (no structured envelope budget). Only a number the query states
    WITH a size unit survives. These four are GPT-5.6's exact regression set."""
    # $ values bled into storage_gb — all DROPPED (no size unit in the query)
    for q, thr in [("laptop between $1200 and $1800", 1800),
                   ("is $1800 enough for gaming?", 1800),
                   ("gaming laptop under $2000", 2000)]:
        d = route_turn(db, _env(q), llm_fn=_route_stub("SEARCH", "el-6-6", {"storage_gb": [">=", thr]}))
        assert "storage_gb" not in d.requirements, f"price bled into storage_gb for: {q}"
    # the ONLY one that keeps storage_gb — the query actually says '1TB'
    d = route_turn(db, _env("1TB laptop under $1000"),
                   llm_fn=_route_stub("SEARCH", "el-6-6", {"storage_gb": [">=", 1000]}))
    assert d.requirements.get("storage_gb") == [(">=", 1000.0)]
    # ram_gb without a unit is also dropped; with '16GB' it's kept
    d = route_turn(db, _env("gaming laptop around $1600"),
                   llm_fn=_route_stub("SEARCH", "el-6-6", {"ram_gb": [">=", 1600]}))
    assert "ram_gb" not in d.requirements
    d = route_turn(db, _env("laptop with 16GB RAM"),
                   llm_fn=_route_stub("SEARCH", "el-6-6", {"ram_gb": [">=", 16]}))
    assert d.requirements.get("ram_gb") == [(">=", 16.0)]


def test_workload_reroutes_to_primary_sold_device(db):
    """M3-C1 (was: valorant 2/3): the model maps a game to a Software (so-*) node — a WORKLOAD,
    not a product gap. The OLD fix dropped the node to None → a broad LIKE-search that found
    nothing. Now it REROUTES retrieval to the store's primary sold DEVICE node (a real catalog
    leg), records the workload + relationship=run_on, and never refuses. Vertical-blind."""
    d = route_turn(db, _env("i want to play valorant at 144fps"),
                   llm_fn=_route_stub("OFF_CATALOG", "so-3-1", {"refresh_hz": [">=", 144]}))
    assert d.lane != "OFF_CATALOG" and not d.refusal_granted
    assert d.node_handle == "el-6-11-2"                   # rerouted to the primary sold device
    assert d.requested_product_node == "el-6-11-2"
    assert d.workloads == ("so-3-1",) and d.relationship == "run_on"
    assert d.requirements == {"refresh_hz": [(">=", 144.0)]}  # workload requirement kept
    # a Media (me-*) node behaves the same (capability verb 'stream')
    d2 = route_turn(db, _env("stream movies"), llm_fn=_route_stub("SEARCH", "me-1"))
    assert d2.node_handle == "el-6-11-2" and d2.relationship == "run_on"
    # a real product gap (forklift/bi) is NOT a workload vertical → still refuses, buy relationship
    d3 = route_turn(db, _env("do you sell forklifts?"), llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    assert d3.refusal_granted and d3.relationship == "buy" and d3.workloads == ()


def test_compare_named_units_narrows_to_exactly_those(db):
    """R9.3 e2e (the compare_two_models case): 'compare the MSI Thin and the Acer Nitro' over
    Computers narrows to EXACTLY those two, in named order — not the whole category."""
    from sqlalchemy import text as _t
    from src.app.services.taxonomy_registry import upsert_classification
    db.execute(_t("INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
                  "('p3','LAP-3','Acer Nitro 17in 144Hz Gaming Laptop',189900,"
                  "'{\"ram_gb\": 16, \"gpu_vram_gb\": 8}','Acer')"))
    upsert_classification(db, sku="LAP-3", node_handle="el-6-11-2", source="t", status="approved")
    db.commit()
    resp = recommend_turn(db, _env("compare the msi thin and the acer nitro"),
                          llm_fn=_route_stub_ct("COMPARE", "el-6", ["msi thin", "acer nitro"]))
    assert [p.sku for p in resp.products] == ["LAP-1", "LAP-3"]    # named order, LAP-2 excluded
    assert resp.extras.get("compare_bound") == ["LAP-1", "LAP-3"]
    assert "MSI Thin" in resp.message and "Acer Nitro" in resp.message


def test_compare_named_units_without_shared_taxonomy_node_retrieves_each_target(db):
    """A model may identify both real products but return no common category node. The core
    retrieves the bounded target names independently instead of searching the non-matching
    phrase 'X versus Y'."""
    resp = recommend_turn(
        db,
        _env("compare the msi thin versus the asus tuf"),
        llm_fn=_route_stub_ct("COMPARE", None, ["msi thin", "asus tuf"]),
    )

    assert [p.sku for p in resp.products] == ["LAP-1", "LAP-2"]
    assert (resp.extras.get("evidence") or {}).get("retrieval_mode") == "named_compare_union"
    assert resp.extras.get("compare_bound") == ["LAP-1", "LAP-2"]


def test_compare_uses_taxonomy_to_disambiguate_same_brand_accessories(db):
    """An unambiguous leg supplies the product type for a brand-family leg containing
    a laptop, monitor, and bag; unrelated variants cannot hijack the comparison."""
    db.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p3','LAP-3','Dell G16 Gaming Laptop',179900,'{}','Dell'), "
        "('p4','LAP-4','Lenovo Legion Gaming Laptop',189900,'{}','Lenovo'), "
        "('p5','MON-1','Lenovo Legion Gaming Monitor',49900,'{}','Lenovo'), "
        "('p6','BAG-1','Lenovo Legion Laptop Backpack',9900,'{}','Lenovo')"))
    from src.app.services.taxonomy_registry import upsert_classification
    upsert_classification(db, sku="LAP-3", node_handle="el-6-11-2", source="test",
                          status="approved")
    upsert_classification(db, sku="LAP-4", node_handle="el-6-11-2", source="test",
                          status="approved")
    upsert_classification(db, sku="MON-1", node_handle="el-17-1", source="test",
                          status="approved")
    upsert_classification(db, sku="BAG-1", node_handle="lb-1-16", source="test",
                          status="approved")
    db.commit()

    resp = recommend_turn(
        db,
        _env("Dell G16 versus Lenovo Legion"),
        llm_fn=_route_stub_ct("COMPARE", None, ["Dell G16", "Lenovo Legion"]),
    )

    assert [p.sku for p in resp.products] == ["LAP-3", "LAP-4"]
    assert resp.extras.get("compare_bound") == ["LAP-3", "LAP-4"]


def test_compare_unbindable_targets_keep_whole_slate(db):
    """<2 targets bind ('the rolex') → the whole slate stands — never narrow to wrong units."""
    resp = recommend_turn(db, _env("compare the msi thin and the rolex"),
                          llm_fn=_route_stub_ct("COMPARE", "el-6", ["msi thin", "rolex"]))
    assert len(resp.products) == 2                                  # full el-6 slate (LAP-1+LAP-2)
    assert resp.extras.get("compare_bound") is None


def _route_stub_ct(lane, handle, targets):
    return lambda p, t: json.dumps({"lane": lane, "handle": handle, "requirements": {},
                                    "confidence": 0.9, "compare_targets": targets})


def test_explain_consumes_prior_shortlist(db):
    """R9.4 (review-6 #17 closed): 'why is the first one better for me?' retrieves EXACTLY the
    items shown last turn, in shown order, and explains the top pick from its fit verdicts —
    never a fresh category sweep that may not contain 'the first one'."""
    sess = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-2", "LAP-1"],
            "accepted_constraints": {"budget_max_cents": None,
                                     "requirements": {"ram_gb": [[">=", 16]]}}}
    resp = recommend_turn(db, _env("why is the first one better for me?", session=sess),
                          llm_fn=_route_stub("EXPLAIN", None))
    assert [p.sku for p in resp.products] == ["LAP-2", "LAP-1"]   # the SHOWN items, shown order
    assert (resp.extras.get("evidence") or {}).get("retrieval_mode") == "prior_shortlist"
    assert "Asus TUF" in resp.message                              # explains the ACTUAL top pick
    d = resp.extras["decision"]
    assert d["subject_from_session"] is True


def test_compare_with_own_node_keeps_node_retrieval(db):
    """A COMPARE that names its own subject ('compare X vs Y' fresh) is NOT a shortlist turn —
    node retrieval stands; the shortlist path fires only for session-subject turns."""
    sess = {"prior_node": "el-6-6", "shortlist_skus": ["LAP-1"]}
    resp = recommend_turn(db, _env("compare the gaming laptops", session=sess),
                          llm_fn=_route_stub("COMPARE", "el-6-11-2"))
    assert (resp.extras.get("evidence") or {}).get("retrieval_mode") != "prior_shortlist"
    assert [p.sku for p in resp.products] == ["LAP-2", "LAP-1"]
    # LAP-1 is classified broadly but has direct product-title evidence that it
    # is a gaming laptop; this remains a fresh node/text retrieval, not leakage
    # from the one-item prior shortlist.


def test_continuation_fragment_drift_keeps_prior_subject(db):
    """R9.2 live finding: 'show me cheaper ONES' embedding-grounded to Swimwear > One-Pieces.
    On a continuation lane, a model node UNRELATED to the prior subject is drift — prior wins;
    a related node (narrowing to a child / widening to an ancestor) stands."""
    sess = {"prior_node": "el-6-11-2"}
    d = route_turn(db, _env("show me cheaper ones", session=sess),
                   llm_fn=_route_stub("FILTER", "aa-1-20-22"))     # the swimwear drift
    assert d.node_handle == "el-6-11-2"                            # prior subject kept
    d2 = route_turn(db, _env("just the gaming computers", session={"prior_node": "el-6-11-2"}),
                    llm_fn=_route_stub("FILTER", "el-6-11"))       # ancestor = widening, stands
    assert d2.node_handle == "el-6-11"
    d3 = route_turn(db, _env("office chairs actually", session=sess),
                    llm_fn=_route_stub("SEARCH", "fr-7-7"))        # SEARCH = real pivot, untouched
    assert d3.node_handle == "fr-7-7"
    d4 = route_turn(db, _env("the gaming ones", session={"prior_node": "el-6-6"}),
                    llm_fn=_route_stub("FILTER", "el-6-11-2"))     # same el-6 family = refinement
    assert d4.node_handle == "el-6-11-2"                           # sibling-family jump stands


def test_refine_clamps_brand_to_catalog_and_sort_to_vocabulary(db):
    """R9.2 clamps: a model-named brand maps to the CATALOG's canonical casing; an invented
    brand and an out-of-vocabulary sort are dropped, never guessed."""
    d = route_turn(db, _env("only asus, cheapest first"),
                   llm_fn=_route_stub("FILTER", "el-6-11-2",
                                      refine={"brand": "asus", "sort": "price_asc"}))
    assert d.brand_filter == "Asus" and d.sort == "price_asc"    # canonical casing from catalog
    d2 = route_turn(db, _env("only rolex, alphabetical"),
                    llm_fn=_route_stub("FILTER", "el-6-11-2",
                                       refine={"brand": "Rolex", "sort": "alphabetical"}))
    assert d2.brand_filter is None and d2.sort is None           # invented → dropped


def test_filter_only_brand_narrows_to_that_brand(db):
    """R9.2 e2e: 'only Asus' over Computers (el-6 holds MSI LAP-1 + Asus LAP-2 in its
    subtree) returns ONLY the Asus unit."""
    resp = recommend_turn(db, _env("only asus", session={"prior_node": "el-6"}),
                          llm_fn=_route_stub("FILTER", None, refine={"brand": "asus"}))
    skus = [p.sku for p in resp.products]
    assert skus == ["LAP-2"]                                     # MSI LAP-1 filtered out


def test_text_retrieval_persists_subject_for_brand_only_followup(db):
    first = recommend_turn(
        db,
        _env("gaming laptop", budget_max=2300),
        llm_fn=_route_stub("SEARCH", None),
    )
    inferred = first.extras["constraints_used"]["node_handle"]
    assert inferred == "el-6-11-2"

    session = {
        "prior_node": inferred,
        "shortlist_skus": [product.sku for product in first.products],
        "accepted_constraints": {"budget_max_cents": 230000},
    }
    raw = json.dumps({
        "lane": "FILTER", "handle": None, "requirements": {},
        "subject_action": "switch", "confidence": 0.9,
        "refine": {"brand": None, "prefer_brand": None,
                   "exclude_brand": "MSI", "sort": None},
    })
    second = recommend_turn(
        db,
        _env("Exclude MSI and keep the same budget", session=session),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert second.products
    assert {product.brand for product in second.products} == {"Asus"}
    assert second.extras["constraints_used"]["budget_max_cents"] == 230000
    assert second.extras["decision"]["subject_action"] == "continue"


def test_brand_filter_zero_match_is_honest_not_ignored(db):
    """A brand filter that matches nothing shows an honest empty + message — NEVER the
    unfiltered slate (a grid that silently ignored the filter is the answer-shape lie)."""
    # Keep the brand real while placing its product outside the requested taxonomy.
    # MSI is no longer suitable test data here because its product name itself is
    # strong gaming-laptop retrieval evidence even though its stored node is broad.
    db.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p3','CHR-1','Lenovo Executive Office Chair',89900,'{}','Lenovo')"
    ))
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(db, node_handle="fr-7-7")
    upsert_classification(
        db, sku="CHR-1", node_handle="fr-7-7", source="test", status="approved",
    )
    resp = recommend_turn(db, _env("only lenovo gaming laptops", session={}),
                          llm_fn=_route_stub("FILTER", "el-6-11-2", refine={"brand": "Lenovo"}))
    assert resp.products == []
    assert "Lenovo" in resp.message                               # honest, names the brand


def test_filter_continuation_inherits_budget_and_requirements(db):
    """R9.1 (screenshot 30 budget-loss): 'show me cheaper ones' restates nothing — the session's
    accepted constraints carry forward on a CONTINUATION lane, with provenance flags."""
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-2"],
               "accepted_constraints": {"budget_min_cents": None, "budget_max_cents": 230000,
                                        "requirements": {"ram_gb": [[">=", 16]]}}}
    resp = recommend_turn(db, _env("show me cheaper ones", session=session),
                          llm_fn=_route_stub("FILTER", None))
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] == 230000 and cu["budget_inherited"] is True
    assert "ram_gb" in cu["requirements"] and cu["requirements_inherited"] is True
    assert [p.sku for p in resp.products]           # still a real product turn (both under $2300)
    assert all((p.fit or {}).get("overall") for p in resp.products)   # fit_check ran on inherited reqs


def test_active_procurement_continuation_inherits_budget_and_use_case(db):
    """A sparse current-order turn keeps already-authorized commercial context.

    Procurement continuity is bounded by the active workflow marker; a fresh procurement
    search without that marker cannot inherit an old budget or workload.
    """
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "budget_min_cents": None,
            "budget_max_cents": 140000,
            "budget_scope": "per_unit",
            "quantity": 15,
            "requirements": {},
            "use_cases": ["office"],
        },
    }
    payload = {
        "lane": "PROCUREMENT",
        "handle": None,
        "requirements": {},
        "use_cases": [],
        "quantity": 20,
        "budget_scope": None,
        "subject_action": "uncertain",
        "procurement_context": "current_order",
        "confidence": 0.9,
    }
    resp = recommend_turn(
        db,
        _env("actually make that 20 people", session=session),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    constraints = resp.extras["constraints_used"]
    assert constraints["budget_max_cents"] == 140000
    assert constraints["budget_inherited"] is True
    assert "office" in resp.extras["decision"]["use_cases"]
    assert all(question.get("id") not in {"ask_budget", "ask_use_case"}
               for question in resp.clarify)


def test_stated_constraints_beat_session(db):
    """Adopt-if-absent: a budget/requirement stated THIS turn always wins over the session."""
    session = {"prior_node": "el-6-11-2",
               "accepted_constraints": {"budget_max_cents": 230000,
                                        "requirements": {"ram_gb": [[">=", 16]]}}}
    resp = recommend_turn(db, _env("only ones with 32GB RAM under $2000", budget_max=2000.0,
                                   session=session),
                          llm_fn=_route_stub("FILTER", None, {"ram_gb": [">=", 32]}))
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] == 200000 and cu["budget_inherited"] is False
    assert cu["requirements"]["ram_gb"] == [[">=", 32]] and cu["requirements_inherited"] is False


def test_fresh_search_never_inherits_session_constraints(db):
    """Context-rot guard: a NEW search resets — yesterday's budget must not haunt a new hunt."""
    session = {"accepted_constraints": {"budget_max_cents": 230000,
                                        "requirements": {"ram_gb": [[">=", 64]]}}}
    resp = recommend_turn(db, _env("gaming laptop", session=session),
                          llm_fn=_route_stub("SEARCH", "el-6-11-2"))
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] is None and cu["budget_inherited"] is False
    assert cu["requirements_inherited"] is False
    assert cu["requirements"]["ram_gb"] == [[">=", 16.0]]


def test_explicit_subject_switch_does_not_inherit_on_explain_lane(db):
    session = {"prior_node": "el-6-11-2",
               "accepted_constraints": {"budget_max_cents": 230000,
                                        "requirements": {"ram_gb": [[">=", 32]]}}}
    payload = {"lane": "EXPLAIN", "handle": "el-6-6", "requirements": {},
               "subject_action": "switch", "confidence": 0.9}
    resp = recommend_turn(db, _env("switch products: show laptops and explain", session=session),
                          llm_fn=lambda p, t: json.dumps(payload))
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] is None
    assert cu["budget_inherited"] is False
    assert cu["requirements_inherited"] is False


def test_explain_named_alternatives_cannot_silently_drop_accepted_budget(db):
    """Screenshot 30: naming brands/products in a why-question is comparison evidence,
    not buyer authorization to release the accepted monetary constraint."""
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-2"],
               "accepted_constraints": {"budget_max_cents": 230000,
                                        "requirements": {"ram_gb": [[">=", 16]]}}}
    payload = {"lane": "EXPLAIN", "handle": "el-6-11-2", "requirements": {},
               "subject_action": "switch", "confidence": 0.9}
    resp = recommend_turn(
        db,
        _env("why Lenovo and not MSI or Alienware?", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] == 230000
    assert cu["budget_inherited"] is True
    assert cu["requirements_inherited"] is True
    assert all((p.price_cents or 0) <= 230000 for p in resp.products)


def test_model_total_budget_becomes_per_unit_retrieval_cap(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": 2, "total_budget": 3500, "budget_scope": "total",
               "subject_action": "switch", "confidence": 0.9}
    resp = recommend_turn(db, _env("two laptops, $3500 total"),
                          llm_fn=lambda p, t: json.dumps(payload))
    assert resp.extras["constraints_used"]["budget_max_cents"] == 175000
    assert all((p.price_cents or 0) <= 175000 for p in resp.products)


def test_text_parsed_total_budget_is_normalized_before_retrieval(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": 10, "total_budget": 25000, "budget_scope": "total",
               "subject_action": "switch", "confidence": 0.9}
    envelope = dataclasses.replace(
        _env("ten laptops, $25000 total"),
        budget_min_cents=20_000_00,
        budget_max_cents=25_000_00,
    )
    resp = recommend_turn(db, envelope, llm_fn=lambda p, t: json.dumps(payload))
    constraints = resp.extras["constraints_used"]
    assert constraints["budget_min_cents"] == 200_000
    assert constraints["budget_max_cents"] == 250_000
    assert all((product.price_cents or 0) <= 250_000 for product in resp.products)


def test_bulk_budget_range_defaults_to_per_unit_despite_model_total_claim(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": 25, "total_budget": 1900, "budget_scope": "total",
               "subject_action": "switch", "confidence": 0.9}
    envelope = dataclasses.replace(
        _env("what laptops for work? budget 1500 to 1900, I need about 25"),
        budget_min_cents=150_000,
        budget_max_cents=190_000,
    )
    resp = recommend_turn(db, envelope, llm_fn=lambda p, t: json.dumps(payload))
    decision = resp.extras["decision"]
    assert decision["budget_scope"] == "per_unit"
    assert decision["total_budget_cents"] is None
    assert resp.products
    assert all(150_000 <= (product.price_cents or 0) <= 190_000 for product in resp.products)


def test_model_unavailable_bulk_search_keeps_quantity_while_scope_is_blocked(db):
    """The production-shaped demo deliberately disables the optional router model.

    Explicit tenant-sold product language and bounded quantity/budget facts remain
    sufficient to preserve the request, but an unresolved budget scope still blocks
    retrieval.  The follow-up can resolve it without losing the quantity.
    """
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    envelope = dataclasses.replace(
        _env("I need 25 work laptops, budget 1200 to 1500"),
        budget_min_cents=120_000,
        budget_max_cents=150_000,
    )
    response = recommend_turn(db, envelope, llm_fn=lambda _prompt, _timeout: "")

    assert response.extras["requested_quantity"] == 25
    assert response.extras["decision"]["budget_scope"] == "unknown"
    assert response.clarify and response.clarify[0]["id"] == "budget_scope"
    assert response.products == []


def test_budget_scope_answer_preserves_explicit_bulk_quantity(db):
    session = {
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "budget_min_cents": 120_000,
            "budget_max_cents": 150_000,
            "quantity": 25,
        },
        "pending_clarification": {
            "question_id": "budget_scope",
            "state": "pending",
        },
    }
    payload = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "requirements": {},
        "quantity": None,
        "budget_scope": "per_unit",
        "subject_action": "switch",
        "clarification_relation": "answer",
        "confidence": 0.9,
    }

    response = recommend_turn(
        db,
        _env("per item", session=session),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert response.extras["requested_quantity"] == 25
    assert response.extras["decision"]["subject_action"] == "continue"
    assert response.extras["decision"]["budget_scope"] == "per_unit"


def test_mixed_choose_confirm_preserves_original_evidence_blocker_in_trace(db):
    blocked = {
        "outcome": "clarify",
        "catalog_authority": "blocked",
        "desired_outcome": "recommend a laptop for simulating a digital twin",
        "concepts": [{
            "text": "digital twin simulation",
            "status": "unresolved",
            "material": True,
            "interpretations": [],
        }],
        "questions": [{
            "question_id": "software_or_standard",
            "question": "Which exact software and version must be supported?",
            "material": True,
        }],
        "state_prevented": ["catalog_recommendation", "commerce_execution"],
    }
    response = recommend_turn(
        db,
        _env(
            "Choose a laptop and confirm the purchase order.",
            session={"semantic_resolution": blocked},
        ),
        llm_fn=lambda _prompt, _timeout: "",
    )

    semantic = response.extras["semantic_resolution"]
    assert "digital twin" in semantic["desired_outcome"]
    assert semantic["questions"][0]["question_id"] == "software_or_standard"
    assert semantic["catalog_authority"] == "blocked"
    assert "buyer_commitment" in semantic["state_prevented"]
    assert semantic["case_obligations"]


def test_explicit_per_unit_budget_does_not_inherit_prior_total_budget(db):
    payload = {"lane": "FILTER", "handle": "el-6-6", "requirements": {},
               "quantity": 25, "total_budget": None, "budget_scope": "per_unit",
               "subject_action": "continue", "use_cases": ["office"], "confidence": 0.9}
    session = {
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["GAM-0001"],
        "accepted_constraints": {
            "budget_max_cents": 230000,
            "total_budget_cents": 230000,
            "quantity": 1,
            "requirements": {},
        },
    }
    envelope = _env(
        "office laptops budget 1500 to 1900 per laptop, I need 25", session=session,
    )
    resp = recommend_turn(db, envelope, llm_fn=lambda p, t: json.dumps(payload))
    assert resp.extras["decision"]["total_budget_cents"] is None
    assert resp.extras["constraints_used"]["budget_max_cents"] == 190000


def test_explicit_bulk_fields_survive_when_model_omits_them(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6",
               "requirements": {"ram_gb": [">=", 16]},
               "subject_action": "switch", "confidence": 0.9}
    envelope = dataclasses.replace(
        _env("suggest 10 suitable laptops with 16GB RAM under a $25,000 total budget"),
        budget_max_cents=25_000_00,
    )
    resp = recommend_turn(db, envelope, llm_fn=lambda p, t: json.dumps(payload))
    assert resp.extras["requested_quantity"] == 10
    assert resp.extras["constraints_used"]["budget_max_cents"] == 250_000
    assert all((product.price_cents or 0) <= 250_000 for product in resp.products)
    legacy = to_legacy(resp)
    assert legacy["requested_quantity"] == 10
    assert "bulk_budget" in legacy
    shown_floor = min(p.price_cents for p in resp.products if p.price_cents is not None)
    assert legacy["bulk_budget"]["floor_cents"] == shown_floor


def test_descriptive_continuation_surfaces_bulk_context_without_promoting_decision(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": None, "subject_action": "continue", "confidence": 0.9}
    session = {"prior_node": "el-6-6", "accepted_constraints": {"quantity": 25}}
    resp = recommend_turn(
        db,
        _env("which of these has the best battery life?", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    assert resp.extras["decision"]["quantity"] is None
    assert resp.extras["requested_quantity"] == 25
    assert resp.extras["quantity_inherited"] is True


def test_current_procurement_continuation_inherits_prior_bulk_quantity(db):
    payload = {"lane": "PROCUREMENT", "handle": "el-6-6", "requirements": {},
               "quantity": None, "subject_action": "continue",
               "procurement_context": "current_order", "confidence": 0.9}
    session = {
        "prior_node": "el-6-6", "active_workflow_lane": "PROCUREMENT",
        "accepted_constraints": {"quantity": 25},
    }
    resp = recommend_turn(
        db,
        _env("which supplier is handling the current request?", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    assert resp.extras["requested_quantity"] == 25


def test_fresh_search_does_not_inherit_prior_bulk_quantity(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": None, "subject_action": "switch", "confidence": 0.9}
    session = {"prior_node": "el-6-6", "accepted_constraints": {"quantity": 25}}
    resp = recommend_turn(
        db,
        _env("show me laptops for professional game development", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    assert resp.extras.get("requested_quantity") is None


def test_uncovered_workload_abstains_and_does_not_inherit_stale_quantity(db):
    """Screenshot 45: category recognition cannot launder workload identity or old quantity."""
    payload = {
        "lane": "SEARCH",
        "handle": "el-6-11-2",
        "use_cases": ["gaming"],
        # Reproduce the live weak-model failure: the model copied the previous
        # quantity even though the current buyer turn did not state one.
        "quantity": 30,
        "subject_action": "continue",
        "clarification_relation": "interrupt",
        "confidence": 0.91,
    }
    session = {
        "prior_node": "el-6-11-2",
        "accepted_constraints": {"quantity": 30},
        "pending_clarification": {
            "version": 2,
            "state": "active",
            "question_id": "gaming_tier",
            "question": "For gaming, which level fits?",
            "original_query": "I need 30 gaming laptops under AUD 2500 each.",
        },
    }
    response = recommend_turn(
        db,
        _env(
            "I need 30 gaming laptops under AUD 2500 each. "
            "Buyer clarification to 'For gaming, which level fits?': "
            "I need help with a laptop for digital twin simulation? "
            "I need it to simulate a cyber attack?.",
            buyer_query=(
                "I need help with a laptop for digital twin simulation? "
                "I need it to simulate a cyber attack?"
            ),
            session=session,
        ),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert response.products == []
    semantic = response.extras["semantic_resolution"]
    assert semantic["catalog_authority"] == "blocked"
    assert {item["text"] for item in semantic["concepts"]} == {
        "digital twin simulation", "simulate a cyber attack",
    }
    assert response.extras.get("requested_quantity") is None
    assert response.extras.get("quantity_inherited") is not True
    assert "catalog_recommendation" in semantic["state_prevented"]
    assert "30 gaming laptops" not in semantic["desired_outcome"]


def test_unresolved_workload_preserves_quantity_stated_in_current_turn(db):
    payload = {
        "lane": "SEARCH",
        "handle": "el-6-11-2",
        "quantity": 12,
        "subject_action": "switch",
        "confidence": 0.91,
    }
    response = recommend_turn(
        db,
        _env("I need 12 laptops for an unfamiliar vibration simulation workflow."),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert response.products == []
    assert response.extras["semantic_resolution"]["catalog_authority"] == "blocked"
    assert response.extras["requested_quantity"] == 12


def test_uncovered_workload_abstains_when_router_model_is_unavailable(db):
    response = recommend_turn(
        db,
        _env(
            "I need help with a laptop for digital twin simulation? "
            "I need it to simulate a cyber attack?",
        ),
        llm_fn=lambda _prompt, _timeout: "",
    )

    assert response.products == []
    semantic = response.extras["semantic_resolution"]
    assert semantic["catalog_authority"] == "blocked"
    assert {item["text"] for item in semantic["concepts"]} == {
        "digital twin simulation", "simulate a cyber attack",
    }
    assert semantic["next_permitted_action"] == "ask_material_clarification"


@pytest.mark.parametrize(
    ("query", "use_case"),
    [
        ("I need a laptop for gaming", "gaming"),
        ("I need a laptop for university study", "student"),
    ],
)
def test_registry_covered_purpose_does_not_trigger_open_world_abstention(
    db, query, use_case,
):
    payload = {
        "lane": "SEARCH", "handle": "el-6-6", "use_cases": [use_case],
        "subject_action": "switch", "confidence": 0.91,
    }
    response = recommend_turn(
        db, _env(query), llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert response.extras.get("semantic_resolution") is None
    assert response.products


def test_complete_brand_excluded_search_does_not_reactivate_prior_bulk_quantity(db):
    payload = {
        "lane": "SEARCH", "handle": "el-6-6", "requirements": {},
        "use_cases": ["game_development"], "quantity": None,
        "subject_action": "switch", "confidence": 0.9,
        "refine": {"brand": "MSI", "exclude_brand": None},
    }
    session = {"prior_node": "el-6-6", "accepted_constraints": {"quantity": 20}}
    resp = recommend_turn(
        db,
        _env("professional game development under $2500, no MSI",
             session=session, budget_max=2500),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    assert resp.extras["decision"]["exclude_brand"] == "MSI"
    assert resp.extras["decision"]["subject_action"] == "switch"
    assert resp.extras.get("requested_quantity") is None


def test_model_cannot_invent_budget_on_keep_total_followup(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": None, "total_budget": 950, "budget_scope": "total",
               "subject_action": "switch", "confidence": 0.9}
    session = {
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "quantity": 15,
            "total_budget_cents": 1_900_000,
            "budget_scope": "total",
        },
    }
    resp = recommend_turn(
        db,
        _env("show a cheaper configuration but keep the total budget", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    decision = resp.extras["decision"]
    assert decision["total_budget_cents"] == 1_900_000
    assert decision["quantity"] == 15
    assert decision["budget_scope"] == "total"
    assert decision["node_handle"] == "el-6-6"


def test_constraint_refinement_preserves_prior_total_budget_for_new_quantity(db):
    payload = {
        "lane": "FILTER",
        "handle": "el-6-6",
        "requirements": {"ram_gb": [">=", 32], "gpu_vram_gb": [">=", 12]},
        "quantity": 15,
        "total_budget": None,
        "budget_scope": "unknown",
        "subject_action": "continue",
        "confidence": 0.9,
    }
    session = {
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "quantity": 20,
            "total_budget_cents": 5_500_000,
            "budget_scope": "total",
        },
    }
    resp = recommend_turn(
        db,
        _env("reduce to 15 with 32 GB RAM and 12 GB VRAM", session=session),
        llm_fn=lambda p, t: json.dumps(payload),
    )
    decision = resp.extras["decision"]
    assert decision["quantity"] == 15
    assert decision["total_budget_cents"] == 5_500_000
    assert decision["budget_scope"] == "total"


def test_stocked_handles_within_contains_and_ungrounded(db):
    """R8.2 marker logic: WITHIN a sold subtree marks, a subtree CONTAINING a sold node marks
    (retrieval reads subtrees), unrelated taxonomy does not, and an ungrounded tenant marks
    NOTHING (no markers beat wrong markers)."""
    from src.app.services.recommendation_core.turn_router import _stocked_handles
    got = _stocked_handles(db, "default", ["el-6-11-2-9", "el-6-11", "fr-7-7", "el-6-11-2"])
    assert got == frozenset({"el-6-11-2-9", "el-6-11", "el-6-11-2"})   # fr-7-7 unmarked
    s2 = sessionmaker(bind=create_engine("sqlite://"))()               # ungrounded: no sold set
    assert _stocked_handles(s2, "default", ["el-6-11-2"]) == frozenset()
    s2.close()


def test_router_prompt_marks_sold_candidates(db):
    """R8.2 (bag→sleeve mis-ground): candidates the store stocks carry [in catalog] in the
    routing prompt — platform truth beside the model's judgment; taxonomy-only siblings do not."""
    seen = {}
    def capture(prompt, timeout):
        seen["p"] = prompt
        return json.dumps({"lane": "SEARCH", "handle": "el-6-11-2",
                           "requirements": {}, "confidence": 0.9})
    route_turn(db, _env("gaming laptop"), llm_fn=capture)
    marked, unmarked = [], []
    for line in seen["p"].splitlines():
        t = line.strip()
        if " : " in t and (t.startswith("el-") or t.startswith("fr-") or t.startswith("so-")
                           or t.startswith("lb-") or t.startswith("sg-") or t.startswith("ae-")):
            (marked if "[in catalog]" in t else unmarked).append(t.split(" : ")[0].strip())
    assert any(h.startswith("el-6") for h in marked)          # the sold subtree is marked
    assert unmarked                                            # taxonomy-only candidates are not
    assert not any(h.startswith("fr-") or h.startswith("so-") for h in marked)  # never mismarked
    assert "lane itself is never null" in seen["p"]
    assert "Do not copy the schema's example values" in seen["p"]


def test_named_catalog_brand_repairs_unstocked_persona_category(db):
    """A school-context word must not turn a named stocked graphics tablet into a toy.

    The repair is driven by the tenant catalog's brand + approved taxonomy evidence.  Neither
    Wacom nor either category is encoded in the router.
    """
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification

    db.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, brand) VALUES "
        "('w1','WAC-1','Wacom Intuos Small Graphics Tablet',7900,'USD','{}','Wacom')"
    ))
    add_sold_node(db, node_handle="el-7-9-12-7")
    upsert_classification(db, sku="WAC-1", node_handle="el-7-9-12-7",
                          source="test", status="approved")

    seen = {}
    def wrong_persona_route(prompt, _timeout):
        seen["prompt"] = prompt
        return json.dumps({"lane": "SEARCH", "handle": "tg-5-2-11",
                           "use_cases": ["digital_art"], "requirements": {},
                           "confidence": 0.8})

    decision = route_turn(
        db,
        _env("a Wacom drawing tablet for high school digital art under $500"),
        llm_fn=wrong_persona_route,
    )

    assert "el-7-9-12-7" in seen["prompt"]
    assert decision.node_handle == "el-7-9-12-7"
    assert decision.source == "model+catalog_brand_anchor"


def test_brand_anchor_does_not_replace_different_product_category(db):
    """A brand association is corroboration, not permission to rewrite a different product."""
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification

    db.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, currency, specs, brand) VALUES "
        "('a1','APL-1','Apple Laptop',190000,'USD','{}','Apple')"
    ))
    upsert_classification(db, sku="APL-1", node_handle="el-6-6",
                          source="test", status="approved")
    add_sold_node(db, node_handle="el-6-6")

    decision = route_turn(
        db,
        _env("do you sell Apple phones?"),
        llm_fn=_route_stub("OFF_CATALOG", "el-4-5"),
    )

    assert decision.node_handle == "el-4-5"
    assert decision.refusal_granted is True


def test_router_clamps_wrong_requirements_container_to_empty(db):
    """A BYO model may return the right keys with the wrong JSON shape; degrade, never raise."""
    def malformed(_prompt, _timeout):
        return json.dumps({"lane": "SEARCH", "handle": "el-6-6", "use_cases": [],
                           "requirements": ["ram_gb", ">=", 16], "confidence": 0.7})
    decision = route_turn(db, _env("a laptop"), llm_fn=malformed)
    assert decision.lane == "SEARCH" and decision.requirements == {}


def test_workload_reroute_uses_declared_host_not_dominant_node(db):
    """review-8 #3 (pharmacy reroute): the reroute target is the store-profile DECLARED
    capability host (Gaming Laptops), NOT merely the most-classified sold node — so a workload
    can never land on whatever category happens to dominate the catalog (pharmacy/accessories)."""
    from src.app.services.taxonomy_registry import primary_sold_node, upsert_classification
    # make el-6-6 (Laptops) dominate classification — 6 vs el-6-11-2's 1
    for sku in ("X1", "X2", "X3", "X4", "X5"):
        upsert_classification(db, sku=sku, node_handle="el-6-6", source="t", status="approved")
    db.commit()
    assert primary_sold_node(db) == "el-6-6"          # the dominant node
    d = route_turn(db, _env("i want to play valorant at 144fps"),
                   llm_fn=_route_stub("OFF_CATALOG", "so-3-1", {"refresh_hz": [">=", 144]}))
    assert d.node_handle == "el-6-11-2"               # the DECLARED host wins over the dominant node
    assert d.relationship == "run_on"


def test_ungrounded_workload_reroutes_to_declared_host(db):
    """review-8 pharmacy-bleed (2nd hole): the model returns node=None for a BARE workload ('i want
    to play valorant' — no device word) but device requirements still resolve. core reroutes to the
    declared host (Gaming Laptops) so retrieval is a REAL device leg — LAP-2 (el-6-11-2), never the
    broad catalog search that returned 10 pharmacy SKUs in the live diagnose."""
    resp = recommend_turn(db, _env("i want to play valorant at 144fps"),
                          llm_fn=_route_stub("SEARCH", "not-a-node-99", {"gpu_vram_gb": [">=", 4]}))
    dec = resp.extras.get("decision") or {}
    assert dec.get("node_handle") == "el-6-11-2"        # rerouted to the declared gaming host
    assert dec.get("relationship") == "run_on"
    assert "LAP-2" in [p.sku for p in resp.products]    # a real device leg, not empty/broad-catalog


def test_ungrounded_no_requirements_stays_empty(db):
    """The reroute must NOT over-fire: node=None with NO requirements (an off-domain ask like a pizza
    place) stays ungrounded — we never reroute a non-workload to the gaming host."""
    resp = recommend_turn(db, _env("recommend a good pizza place near me"),
                          llm_fn=_route_stub("SEARCH", "not-a-node-99"))
    dec = resp.extras.get("decision") or {}
    assert dec.get("node_handle") is None               # no requirements → no reroute


def test_workload_reroute_is_none_when_ungrounded(db):
    """A run_on turn on an UNGROUNDED tenant has no device to reroute to → node None (broad
    search), never a crash and never a refusal."""
    s2 = sessionmaker(bind=create_engine("sqlite://"))()
    d = route_turn(s2, _env("play valorant at 144fps"),
                   llm_fn=_route_stub("OFF_CATALOG", "so-3-1", {"refresh_hz": [">=", 144]}))
    assert d.node_handle is None and d.relationship == "run_on" and not d.refusal_granted
    s2.close()


def test_bare_device_purchase_is_buy_relationship(db):
    """A shopper who names a DEVICE (not a workload) keeps buy relationship + the named node."""
    d = route_turn(db, _env("gaming laptop"), llm_fn=_route_stub("SEARCH", "el-6-11-2"))
    assert d.node_handle == "el-6-11-2" and d.relationship == "buy" and d.workloads == ()


# ── M3-C2: session consumption (multi-turn made real) ───────────────────────────

def _env_session(query, session):
    return TurnEnvelope.from_suggest_params(query=query, uid="u1", tenant_id="default",
                                            session=session)


def test_nodeless_filter_inherits_prior_node(db):
    """'only the 16GB ones' (FILTER, no node of its own) refines the PRIOR search — inherits
    the last turn's node instead of an empty grid. The model's lane is the signal."""
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-1", "LAP-2"]}
    d = route_turn(db, _env_session("only the 16GB ones", session),
                   llm_fn=_route_stub("FILTER", None, {"ram_gb": [">=", 16]}))
    assert d.node_handle == "el-6-11-2"                 # inherited prior subject
    assert d.prior_shortlist == ("LAP-1", "LAP-2")
    assert d.requirements == {"ram_gb": [(">=", 16.0)]}  # fragment's own req still applies


def test_compare_explain_carry_prior_shortlist(db):
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-1", "LAP-2"]}
    d = route_turn(db, _env_session("why is the first one better", session),
                   llm_fn=_route_stub("EXPLAIN", None))
    assert d.prior_shortlist == ("LAP-1", "LAP-2")      # referents resolvable
    assert d.node_handle == "el-6-11-2"


def test_edge_explain_hint_corrects_policy_misroute_only_with_prior_shortlist(db):
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["GAM-0001", "GAM-0002"]}
    env = TurnEnvelope.from_suggest_params(
        query="why Lenovo and not MSI?", uid="u1", tenant_id="default",
        intent_hint="EXPLAIN", session=session,
    )
    d = route_turn(db, env, llm_fn=_route_stub("POLICY_QUESTION", None))
    assert d.lane == "EXPLAIN"
    assert d.prior_shortlist == ("GAM-0001", "GAM-0002")
    assert d.node_handle == "el-6-11-2"

    fresh = TurnEnvelope.from_suggest_params(
        query="what is your return policy?", uid="u1", tenant_id="default",
        intent_hint="EXPLAIN", session={},
    )
    d2 = route_turn(db, fresh, llm_fn=_route_stub("POLICY_QUESTION", None))
    assert d2.lane == "POLICY_QUESTION"


def test_approved_policy_hint_clamps_model_search_misroute(db):
    env = TurnEnvelope.from_suggest_params(
        query="What is your returns policy?",
        uid="u1",
        tenant_id="default",
        intent_hint="POLICY_QUESTION",
        session={},
    )

    decision = route_turn(
        db,
        env,
        llm_fn=_route_stub("SEARCH", None),
    )

    assert decision.lane == "POLICY_QUESTION"


def test_approved_policy_hint_survives_model_unavailable_fallback(db):
    env = TurnEnvelope.from_suggest_params(
        query="What is your returns policy?",
        uid="u1",
        tenant_id="default",
        intent_hint="POLICY_QUESTION",
        session={},
    )

    decision = route_turn(db, env, llm_fn=lambda _prompt, _timeout: "")

    assert decision.lane == "POLICY_QUESTION"
    assert decision.source == "fallback:model_unavailable"


def test_active_procurement_uses_model_continuity_to_correct_policy_conflict(db):
    session = {
        "prior_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"],
        "accepted_constraints": {"quantity": 20},
        "procurement_case_id": "case-1",
    }

    def model(subject_action, procurement_context):
        return lambda _prompt, _timeout: json.dumps({
            "lane": "POLICY_QUESTION", "handle": None, "requirements": {},
            "subject_action": subject_action, "confidence": 0.9,
            "procurement_context": procurement_context,
        })

    sourcing = route_turn(
        db, _env_session("what is the delivery and sourcing tradeoff?", session),
        llm_fn=model("continue", "current_order"),
    )
    policy = route_turn(
        db, _env_session("what is your general returns policy?", session),
        llm_fn=model("uncertain", "general_policy"),
    )

    assert sourcing.lane == "PROCUREMENT"
    assert sourcing.subject_action == "continue"
    assert policy.lane == "POLICY_QUESTION"


def test_active_procurement_can_use_bounded_context_judgment_when_subject_is_uncertain(db):
    session = {
        "active_workflow_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"],
        "accepted_constraints": {"quantity": 20},
        "procurement_case_id": "case-1",
    }
    raw = json.dumps({
        "lane": "POLICY_QUESTION", "handle": None, "requirements": {},
        "subject_action": "uncertain", "procurement_context": "current_order",
        "confidence": 0.9,
    })
    decision = route_turn(
        db, _env_session("what is the delivery and sourcing tradeoff?", session),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    assert decision.lane == "PROCUREMENT"


@pytest.mark.parametrize(
    "query",
    [
        "ship the order to Sydney",
        "we need delivery by 18 September",
        "include a three year onsite warranty",
        "use supplier-direct shipping if it is faster",
        "what is the status of this order?",
        "summarise the sourcing plan so far",
        "that budget is total for all 30",
    ],
)
def test_active_procurement_context_amendments_cannot_change_product_anchor(db, query):
    """Closed context/status operations amend the active case; they are not product searches.

    This clamp is deliberately tested against a hostile/weak router response because product
    identity and case continuity cannot depend on a model interpreting words such as Sydney,
    Teams, warranty, or supplier correctly.
    """
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0002"],
        "accepted_constraints": {
            "quantity": 30,
            "budget_scope": "unknown",
            "total_budget_cents": 20_000_000,
        },
        "procurement_case_id": "case-30",
    }
    hostile = json.dumps({
        "lane": "SEARCH",
        "handle": "el-7-1",
        "subject_action": "switch",
        "procurement_context": "none",
        "confidence": 0.99,
    })

    decision = route_turn(
        db,
        _env_session(query, session),
        llm_fn=lambda _prompt, _timeout: hostile,
    )

    assert decision.lane == "PROCUREMENT"
    assert decision.subject_action == "continue"
    assert decision.procurement_context == "current_order"
    assert decision.node_handle == "el-6-11-2"
    assert decision.quantity == 30


def test_active_procurement_status_is_deterministic_and_retrieval_free(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0007"],
        "accepted_constraints": {"quantity": 80, "budget_scope": "total"},
        "procurement_case_id": "case-7",
    }
    calls = {"model": 0}

    def should_not_run(_prompt, _timeout):
        calls["model"] += 1
        raise AssertionError("status must not invoke classification")

    decision = route_turn(
        db,
        _env_session("what is the status?", session),
        llm_fn=should_not_run,
    )

    assert calls["model"] == 0
    assert decision.case_operation == "status"
    assert decision.exact_product_sku == "RGAM-0007"
    assert decision.quantity == 80
    assert derive_plan(decision).steps == ["handoff_procurement"]


def test_delivery_and_payment_amendment_is_deterministic_and_retrieval_free(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "accepted_constraints": {
            "exact_product_sku": "RGAM-0007",
            "quantity": 80,
            "product_selection_authority": "persisted_cart",
        },
    }
    calls = {"model": 0}

    def should_not_run(_prompt, _timeout):
        calls["model"] += 1
        raise AssertionError("a server-anchored operational amendment must not reopen routing")

    decision = route_turn(
        db,
        _env_session(
            "Keep this exact cart. Deliver within two business days; "
            "deposit now and balance after confirmation.",
            session,
        ),
        llm_fn=should_not_run,
    )

    assert calls["model"] == 0
    assert decision.case_operation == "amendment"
    assert decision.exact_product_sku == "RGAM-0007"
    assert decision.quantity == 80
    assert decision.operational_constraints == {
        "delivery_window_days": 2,
        "payment_plan": "balance_after_confirmation",
    }
    assert derive_plan(decision).steps == ["handoff_procurement"]


def test_post_purchase_failure_outranks_remembered_procurement_status(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0007"],
        "accepted_constraints": {"quantity": 20, "budget_scope": "total"},
        "procurement_case_id": "case-7",
    }
    calls = {"model": 0}

    def should_not_run(_prompt, _timeout):
        calls["model"] += 1
        raise AssertionError("post-purchase claim must not invoke product routing")

    decision = route_turn(
        db,
        _env_session(
            "My laptop failed after three weeks; what is my warranty or return status?",
            session,
        ),
        llm_fn=should_not_run,
    )

    assert calls["model"] == 0
    assert decision.lane == "SUPPORT_CLAIM"
    assert decision.source == "deterministic_post_purchase_claim"
    assert derive_plan(decision).steps == ["handoff_support"]


def test_explicit_sku_suffix_cannot_replace_bulk_quantity(db):
    decision = route_turn(
        db,
        _env("I need 30 HP OMEN MAX 16 RGAM-0007 laptops. AUD 140000 total."),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "PROCUREMENT",
            "handle": "el-6-11-2",
            "quantity": 7,
            "total_budget": 140000,
            "budget_scope": "total",
            "confidence": 0.99,
        }),
    )

    assert decision.quantity == 30


def test_single_prior_sku_is_preserved_on_context_amendment(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0007"],
        "accepted_constraints": {"quantity": 30},
    }
    decision = route_turn(
        db,
        _env_session("ship the order to Sydney", session),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH",
            "handle": "el-7-1",
            "subject_action": "switch",
            "confidence": 0.9,
        }),
    )

    assert decision.subject_action == "continue"
    assert decision.exact_product_sku == "RGAM-0007"


def test_deadline_context_cannot_accept_model_invented_quantity(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0007"],
        "accepted_constraints": {"quantity": 18, "exact_product_sku": "RGAM-0007"},
    }
    decision = route_turn(
        db,
        _env_session("need them by 25 September with colour-accurate display support", session),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "PROCUREMENT", "handle": "el-6-11-2", "quantity": 1,
            "subject_action": "continue", "procurement_context": "current_order",
            "confidence": 0.99,
        }),
    )

    assert decision.quantity == 18
    assert decision.exact_product_sku == "RGAM-0007"


def test_total_for_all_settles_scope_without_reopening_disambiguation(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "accepted_constraints": {
            "quantity": 30,
            "budget_scope": "unknown",
            "total_budget_cents": 20_000_000,
        },
        "procurement_case_id": "case-30",
    }
    decision = route_turn(
        db,
        _env_session("yes, the AUD 200k budget is total for all 30", session),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH", "handle": "el-7-1", "subject_action": "switch",
            "budget_scope": "per_unit", "confidence": 0.99,
        }),
    )

    assert decision.node_handle == "el-6-11-2"
    assert decision.quantity == 30
    assert decision.budget_scope == "total"
    assert decision.total_budget_cents == 20_000_000


def test_total_budget_for_all_preserves_sealed_exact_sku(db):
    session = {
        "active_workflow_lane": "PROCUREMENT",
        "prior_node": "el-6-11-2",
        "shortlist_skus": ["RGAM-0007", "SIBLING-2"],
        "accepted_constraints": {
            "quantity": 18,
            "exact_product_sku": "RGAM-0007",
            "budget_scope": "unknown",
            "total_budget_cents": 8_500_000,
        },
    }
    decision = route_turn(
        db,
        _env_session("total budget for all 18", session),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH", "handle": "el-7-1", "subject_action": "switch",
            "budget_scope": "per_unit", "confidence": 0.99,
        }),
    )

    assert decision.subject_action == "continue"
    assert decision.exact_product_sku == "RGAM-0007"
    assert decision.quantity == 18
    assert decision.budget_scope == "total"


def test_explicit_catalog_model_reference_deterministically_binds_its_taxonomy_node(db):
    """A model name is catalog identity evidence; a stochastic router cannot redirect it."""
    weak_router = json.dumps({
        "lane": "SEARCH", "handle": "el-6-11-2", "subject_action": "uncertain",
        "confidence": 0.99,
    })
    decision = route_turn(
        db,
        _env("show me the MSI Thin 15in FHD 120Hz Gaming Laptop"),
        llm_fn=lambda _prompt, _timeout: weak_router,
    )

    assert decision.node_handle == "el-6-6"
    assert decision.subject_action == "switch"
    assert "explicit_catalog_product" in decision.source


@pytest.mark.parametrize(
    ("subject_action", "procurement_context", "expected_lane"),
    [
        ("continue", "current_order", "PROCUREMENT"),
        ("uncertain", "current_order", "PROCUREMENT"),
        ("continue", "general_policy", "POLICY_QUESTION"),
        ("uncertain", "general_policy", "POLICY_QUESTION"),
    ],
)
def test_active_procurement_policy_clamp_requires_non_policy_context(
    db, subject_action, procurement_context, expected_lane,
):
    session = {
        "active_workflow_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"],
        "accepted_constraints": {"quantity": 20},
        "procurement_case_id": "case-1",
    }
    raw = json.dumps({
        "lane": "POLICY_QUESTION", "handle": None, "requirements": {},
        "subject_action": subject_action, "procurement_context": procurement_context,
        "confidence": 0.9,
    })
    decision = route_turn(
        db, _env_session("follow-up", session),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    assert decision.lane == expected_lane


def test_brand_clear_is_a_bounded_explicit_operation(db):
    session = {
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "brand_filter": "Lenovo",
            "exclude_brand": "Apple",
            "preferred_brand": "Dell",
        },
    }
    raw = json.dumps({
        "lane": "FILTER", "handle": "el-6-6", "requirements": {},
        "refine": {
            "brand": None, "prefer_brand": None, "exclude_brand": None,
            "sort": None, "brand_action": "clear",
        },
        "subject_action": "continue", "confidence": 0.9,
    })
    decision = route_turn(
        db, _env_session("any brand is fine", session),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    assert decision.brand_action == "clear"
    assert decision.brand_filter is None
    assert decision.exclude_brand is None
    assert decision.preferred_brand is None


def test_brand_clear_prevents_core_from_reinheriting_prior_constraints(db):
    session = {
        "prior_node": "el-6-6",
        "accepted_constraints": {
            "brand_filter": "Asus",
            "exclude_brand": "MSI",
            "preferred_brand": "Asus",
        },
    }
    raw = json.dumps({
        "lane": "FILTER", "handle": "el-6-6", "requirements": {},
        "refine": {
            "brand": None, "prefer_brand": None, "exclude_brand": None,
            "sort": None, "brand_action": "clear",
        },
        "subject_action": "continue", "confidence": 0.9,
    })
    response = recommend_turn(
        db, _env("any brand is fine", session=session),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    decision = response.extras["decision"]
    assert decision["brand_action"] == "clear"
    assert decision["brand_filter"] is None
    assert decision["exclude_brand"] is None
    assert {product.brand for product in response.products} == {"MSI"}


def test_no_cart_mutation_downgrade_carries_authorized_prior_node(db):
    env = _env("cut it to 1000 max")
    env = __import__("dataclasses").replace(
        env,
        session={"prior_node": "el-6-6", "shortlist_skus": ["LAP-1"],
                 "accepted_constraints": {}},
        cart=[],
    )
    d = route_turn(db, env, llm_fn=_route_stub("CART_MUTATE", None))
    assert d.lane == "FILTER"
    assert d.node_handle == "el-6-6"
    assert d.subject_from_session is True


def test_budget_only_revision_overrides_incorrect_model_switch(db):
    env = dataclasses.replace(
        _env("cut it to 1000 max"),
        session={"prior_node": "el-6-6", "shortlist_skus": ["LAP-1"],
                 "accepted_constraints": {}},
    )
    def llm(_prompt, _timeout):
        return json.dumps({
            "lane": "SEARCH", "handle": None, "requirements": {},
            "subject_action": "switch", "confidence": 0.9,
        })
    resp = recommend_turn(db, env, llm_fn=llm)
    decision = resp.extras["decision"]
    assert decision["node_handle"] == "el-6-6"
    assert decision["subject_from_session"] is True


def test_budget_only_revision_preserves_answered_scope_when_model_is_unavailable(db):
    env = dataclasses.replace(
        _env("actually budget is now 1800 max"),
        session={
            "prior_node": "el-6-6",
            "shortlist_skus": ["LAP-1"],
            "accepted_constraints": {
                "quantity": 10,
                "budget_scope": "per_unit",
                "budget_min_cents": 120_000,
                "budget_max_cents": 150_000,
            },
        },
    )

    decision = recommend_turn(
        db,
        env,
        llm_fn=lambda *_args: (_ for _ in ()).throw(ConnectionError("offline")),
    ).extras["decision"]

    assert decision["node_handle"] == "el-6-6"
    assert decision["subject_action"] == "continue"
    assert decision["budget_scope"] == "per_unit"



def test_fresh_search_does_not_inherit_prior_node(db):
    """A NEW search (not a narrowing lane) must NOT drag the prior subject in — context-rot
    guard: only FILTER/COMPARE/EXPLAIN continuations inherit."""
    session = {"prior_node": "el-6-11-2", "shortlist_skus": ["LAP-1"]}
    d = route_turn(db, _env_session("show me monitors", session),
                   llm_fn=_route_stub("SEARCH", None))
    assert d.node_handle is None                        # fresh SEARCH, prior node NOT inherited
    assert d.prior_shortlist == ("LAP-1",)             # shortlist still carried (referent-only)


def test_cold_start_filter_fragment_still_never_refused(db):
    """C2-KEEP: with NO session, a bare filter fragment mapped to an unsold component node is
    the COLD-START floor the FILTER-guard protects — still never refused."""
    d = route_turn(db, _env("only ones with 16GB RAM or more"),
                   llm_fn=_route_stub("FILTER", "el-7-12-3", {"ram_gb": [">=", 16]}))
    assert d.lane != "OFF_CATALOG" and not d.refusal_granted


def test_explicit_keyed_quantity_cannot_be_weakened_by_model(db):
    d = route_turn(
        db,
        _env("only ones with 16GB RAM or more"),
        llm_fn=_route_stub("FILTER", "el-6-11-2", {"ram_gb": [">=", 8]}),
    )
    assert d.requirements["ram_gb"] == [(">=", 16.0)]


def test_sold_name_veto_blocks_refusal_when_query_names_sold_category(db):
    """Census: 'laptop for fine-tuning LLMs' — numberless, model itself proposed refusal via
    a datacenter mapping. The query NAMES 'laptop' (a sold category) → refusal vetoed by the
    same sold set that grants refusals. Deterministic symmetry, no model opinion."""
    d = route_turn(db, _env("laptop for fine-tuning small language models locally"),
                   llm_fn=_route_stub("OFF_CATALOG", "el-6-2"))
    assert d.lane != "OFF_CATALOG" and not d.refusal_granted
    # and the veto does NOT protect things the store doesn't sell by name
    d2 = route_turn(db, _env("do you sell forklifts?"), llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    assert d2.refusal_granted


# ── plan ──────────────────────────────────────────────────────────────────────

def test_derived_plans_respect_refusal_grant():
    granted = TurnDecision(lane="OFF_CATALOG", refusal_granted=True)
    assert derive_plan(granted).steps == ["off_catalog_honesty"]
    ungranted = TurnDecision(lane="OFF_CATALOG", refusal_granted=False)
    assert "off_catalog_honesty" not in derive_plan(ungranted).steps


def test_validate_plan_clamps():
    d = TurnDecision(lane="SEARCH", refusal_granted=False)
    assert validate_plan(["retrieve", "fit_check"], d).source == "model"
    assert validate_plan(["retrieve", "invented_tool"], d) is None
    assert validate_plan(["retrieve", "retrieve"], d) is None
    assert validate_plan(["off_catalog_honesty"], d) is None          # ungranted refusal
    assert validate_plan(["handoff_support"], d) is None              # wrong lane


# ── THE ACCEPTANCE: the three known_wrongs, end-to-end through core + adapter ─

def test_known_wrong_forklift_now_refuses_honestly(db):
    resp = recommend_turn(db, _env("do you sell forklifts?"),
                          llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    payload = to_legacy(resp)
    assert expectation_met(payload, {"message_class": "off_catalog", "products_max": 0})
    assert payload["off_catalog"]["supplier_rfq_offer"] is True


def test_known_wrong_a100_spec_laptop_now_sells(db):
    resp = recommend_turn(db, _env("a laptop with performance close to an A100 for local AI work"),
                          llm_fn=_route_stub("SEARCH", "el-6-6", {"gpu_vram_gb": [">=", 8]}))
    payload = to_legacy(resp)
    assert expectation_met(payload, {"message_class_in": ["answer", "answer_with_clarify"],
                                     "products_min": 1})


def test_model_floors_do_not_become_workload_fit_authority(db):
    resp = recommend_turn(
        db,
        _env("Which laptop should I buy with 8 GB RAM and 256 GB storage?"),
        llm_fn=_route_stub(
            "SEARCH", "el-6-6", {"ram_gb": [">=", 8], "storage_gb": [">=", 256]},
        ),
    )
    payload = to_legacy(resp)

    assert payload["qualification_authority"] == "none"
    assert payload["post_catalog_adjudication"]["research_needed"] is True
    assert "no_normalized_requirements" in payload["post_catalog_adjudication"]["reason_codes"]
    assert payload["products"]
    buyer_step = next(
        step for step in payload["execution_steps"] if step["id"] == "buyer-response"
    )
    assert buyer_step["label"] == "Present provisional catalog exploration"


def test_known_wrong_valorant_now_answers_with_closest_match(db):
    resp = recommend_turn(db, _env("i want to play valorant at 144fps"),
                          llm_fn=_route_stub("SEARCH", "el-6-11-2", {"refresh_hz": [">=", 144]}))
    payload = to_legacy(resp)
    assert expectation_met(payload, {"nonempty_message": True, "products_min": 1})
    assert resp.fit_summary["closest_match_mode"] is True
    assert "144" in resp.message                       # says WHY these are closest, not silent


def test_expanded_search_slate_excludes_known_capability_failures_when_matches_exist(db):
    resp = recommend_turn(
        db,
        _env("laptop with at least 32 GB RAM"),
        llm_fn=_route_stub("SEARCH", "el-6-6", {"ram_gb": [">=", 32]}),
    )
    assert [p.sku for p in resp.products] == ["LAP-2"]
    assert all((p.fit or {}).get("overall") == "meets" for p in resp.products)


def test_core_never_raises_and_degrades_honestly():
    resp = recommend_turn(None, _env("anything"), llm_fn=lambda p, t: "")
    assert resp.degraded and resp.message and resp.products == []
# Product-category recognition must not suppress open-world purpose coverage. These
# two cases freeze the browser D/E regression independently of model availability.
def test_product_noun_does_not_disable_material_purpose_abstention(db):
    raw = json.dumps({
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.92,
    })

    decision = route_turn(
        db,
        _env("I need a laptop for digital twin simulation of a cyber attack"),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    plan = derive_plan(decision)

    assert decision.node_handle == "el-6-6"
    assert decision.coverage_abstention_shadow["proposal_origin"] == "coverage_abstention"
    assert plan.semantic_authority_state == "uninterpreted_material"
    assert plan.needs_concept_resolution is True


def test_product_noun_negative_battery_keeps_ordinary_search_authorized(db):
    raw = json.dumps({
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.92,
    })

    decision = route_turn(
        db,
        _env("show me a laptop under $1000"),
        llm_fn=lambda _prompt, _timeout: raw,
    )
    plan = derive_plan(decision)

    assert decision.coverage_abstention_shadow == {}
    assert plan.semantic_authority_state == "not_material"
    assert plan.needs_concept_resolution is False


def test_explicit_gaming_laptop_phrase_uses_enrolled_profile_for_local_exploration(db):
    decision = route_turn(
        db,
        _env("I need gaming laptops for a studio."),
        llm_fn=lambda _prompt, _timeout: "",
    )

    assert decision.use_cases == ("gaming",)
    assert decision.semantic_proposal["proposal_origin"] == "coverage_abstention"

    response = recommend_turn(
        db,
        _env("I need gaming laptops for a studio."),
        llm_fn=lambda _prompt, _timeout: "",
    )
    assert response.extras["provisional_catalog_authority"]["covered_profiles"] == ["gaming"]
    assert all(
        "needs current external requirements" not in item["text"].lower()
        for item in response.clarify
    )


def test_product_noun_unresolved_purpose_cannot_emit_catalog_products(db):
    raw = json.dumps({
        "lane": "SEARCH",
        "handle": "el-6-6",
        "confidence": 0.92,
    })

    response = recommend_turn(
        db,
        _env("I need a laptop for digital twin simulation of a cyber attack"),
        llm_fn=lambda _prompt, _timeout: raw,
    )

    assert response.products == []
    assert response.extras["slate_disposition"] == "clear"
    assert response.extras["plan"]["semantic_authority_state"] == "uninterpreted_material"
    trigger = response.extras["research_trigger_shadow"]
    assert trigger["state"] == "uninterpreted_material"
    assert trigger["recommendation"] == "research_candidate"
