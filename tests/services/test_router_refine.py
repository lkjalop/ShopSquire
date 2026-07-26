"""Phase 1d — the router emits a SOFT brand preference distinct from the HARD brand filter:
'ideally a Mac' → preferred_brand (keeps other options, lights the shelf's band 3), NOT brand_filter
(which would remove every non-Apple option)."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.turn_router import _instruction_prefix, route_turn


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT DEFAULT 'USD', brand TEXT, specs TEXT, "
        "product_type TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, brand, specs) VALUES "
        "('p1','MAC-1','Apple MacBook Air',129900,'Apple','{}'), "
        "('p2','DEL-1','Dell XPS 13',119900,'Dell','{}')"))
    yield s
    s.close()


def _env(q):
    return TurnEnvelope.from_suggest_params(query=q, uid="u1", tenant_id="default")


def _stub(**refine):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "use_cases": [], "requirements": {},
               "refine": refine, "compare_targets": [], "confidence": 0.9}
    return lambda p, t: json.dumps(payload)


def test_router_prompt_distinguishes_policy_from_active_procurement_changes():
    prompt = _instruction_prefix(("ram_gb",), ("office",))
    assert "general payment/delivery/returns policy only" in prompt
    assert "RFQ drafts, supplier channels, requested delivery dates" in prompt
    assert "keep/change-constraint turns" in prompt
    assert "has the supplier draft been sent?" in prompt
    assert "keep a sourcing request as a draft" in prompt
    assert "price-affordability question by itself" in prompt
    assert "requires a quantity, supplier" in prompt


def test_router_prompt_uses_sparse_json_to_bound_decode_work():
    prompt = _instruction_prefix(("ram_gb",), ("office",))

    assert "Always include lane" in prompt
    assert "Omit optional fields" in prompt
    assert "no [in catalog] candidate fits" in prompt
    assert "include either its offered unstocked handle" in prompt.lower()
    assert '"handle":null' not in prompt


def test_soft_preferred_brand_is_not_a_hard_filter(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    d = route_turn(db, _env("a laptop, ideally a mac"),
                   llm_fn=_stub(brand=None, prefer_brand="apple", sort=None))
    assert d.preferred_brand == "Apple"     # clamped to canonical catalog casing
    assert d.brand_filter is None           # soft preference does NOT become a hard filter


def test_brand_negation_extracted_and_clamped(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    # 'a laptop but not Apple' → exclude_brand, clamped to the catalog's canonical casing
    d = route_turn(db, _env("a laptop but not apple"),
                   llm_fn=_stub(brand=None, prefer_brand=None, exclude_brand="apple", sort=None))
    assert d.exclude_brand == "Apple"
    assert d.brand_filter is None and d.preferred_brand is None   # exclusion ≠ inclusion


def test_explicit_negation_repairs_model_positive_brand_contradiction(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    d = route_turn(
        db,
        _env("a work laptop under $1900, not Apple"),
        llm_fn=_stub(brand="apple", prefer_brand=None, exclude_brand=None, sort=None),
    )
    assert d.exclude_brand == "Apple"
    assert d.brand_filter is None


def test_no_brand_repairs_model_positive_brand_contradiction(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    d = route_turn(
        db,
        _env("show me game development laptops, no Apple"),
        llm_fn=_stub(brand="apple", prefer_brand=None, exclude_brand=None, sort=None),
    )
    assert d.exclude_brand == "Apple"
    assert d.brand_filter is None


def test_hard_filter_suppresses_duplicate_soft_band(db):
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")
    # 'only Apple' is a hard filter; the same brand as a soft preference is redundant → dropped
    d = route_turn(db, _env("only apple laptops"),
                   llm_fn=_stub(brand="apple", prefer_brand="apple", sort=None))
    assert d.brand_filter == "Apple" and d.preferred_brand is None


def test_typed_sort_on_same_prior_subject_is_authorized_as_filter(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    envelope = TurnEnvelope.from_suggest_params(
        query="show the cheapest laptop",
        uid="u1",
        tenant_id="default",
        session={"prior_node": "el-6-6"},
    )
    d = route_turn(
        db,
        envelope,
        llm_fn=_stub(brand=None, prefer_brand=None, sort="price_asc"),
    )

    assert d.lane == "FILTER"
    assert d.sort == "price_asc"
    assert d.subject_action == "continue"
    assert "typed_sort_refinement" in d.source


def test_typed_sort_on_child_of_prior_subject_is_authorized_as_filter(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    envelope = TurnEnvelope.from_suggest_params(
        query="show the cheapest gaming laptop",
        uid="u1",
        tenant_id="default",
        session={"prior_node": "el-6"},
    )
    payload = {
        "lane": "SEARCH",
        "handle": "el-6-6",
        "use_cases": [],
        "requirements": {},
        "refine": {"sort": "price_asc"},
        "confidence": 0.9,
    }
    d = route_turn(db, envelope, llm_fn=lambda _prompt, _timeout: json.dumps(payload))

    assert d.lane == "FILTER"
    assert d.node_handle == "el-6-6"


def test_sparse_procurement_proposal_recovers_only_named_sold_subject(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    payload = {
        "lane": "PROCUREMENT",
        "quantity": 20,
        "total_budget": 16000,
        "budget_scope": "total",
        "procurement_context": "current_order",
        "requirements": {},
        "confidence": 0.9,
    }
    d = route_turn(
        db,
        _env("I need 20 work laptops with a total order budget of $16000"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.lane == "PROCUREMENT"
    assert d.node_handle == "el-6-6"
    assert d.quantity == 20
    assert d.total_budget_cents == 1_600_000
    assert d.source == "model+catalog_subject_rescue"


def test_sparse_procurement_uses_clamped_workload_host_before_lexical_accessory(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    add_sold_node(db, node_handle="el-6-11-2")
    add_sold_node(db, node_handle="el-2-2-7-2-2")
    payload = {
        "lane": "PROCUREMENT",
        "quantity": 20,
        "total_budget": 55000,
        "budget_scope": "total",
        "procurement_context": "current_order",
        "use_cases": ["game_development"],
        "requirements": {},
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("I'm starting a gaming studio for 20 students, $55,000 total budget"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.lane == "PROCUREMENT"
    assert d.node_handle == "el-6-11-2"
    assert d.use_cases == ("game_development",)
    assert d.source == "model+use_case_host"


def test_category_rescue_does_not_treat_modifier_as_product_subject(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-2-2-7-2-2")
    payload = {
        "lane": "PROCUREMENT",
        "quantity": 20,
        "total_budget": 55000,
        "budget_scope": "total",
        "procurement_context": "current_order",
        "requirements": {},
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("I'm starting a gaming studio for 20 students, $55,000 total budget"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.lane == "PROCUREMENT"
    assert d.node_handle is None
    assert d.source == "model"


def test_explicit_product_category_precedes_workload_host_rescue(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-11-2")
    add_sold_node(db, node_handle="el-2-2-7-2-2")
    payload = {
        "lane": "PROCUREMENT",
        "quantity": 20,
        "total_budget": 10000,
        "budget_scope": "total",
        "use_cases": ["gaming"],
        "requirements": {},
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("I need 20 gaming headsets for the studio, $10,000 total"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.node_handle == "el-2-2-7-2-2"
    assert d.source == "model+catalog_subject_rescue"


def test_explain_with_material_refinements_decomposes_to_filter(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-11-2")
    payload = {
        "lane": "EXPLAIN",
        "handle": "el-6-11-2",
        "quantity": 22,
        "requirements": {
            "gpu_vram_gb": [">=", 12],
            "ram_gb": [">=", 32],
        },
        "use_cases": ["game_development"],
        "subject_action": "continue",
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("Why those? I need 22 laptops with 12 GB VRAM and 32 GB RAM."),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.lane == "FILTER"
    assert d.secondary_lanes == ("EXPLAIN",)
    assert d.quantity == 22
    assert "gpu_vram_gb" in d.requirements


def test_ambiguous_equipment_asks_product_type_instead_of_guessing_accessory(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-11-2")
    add_sold_node(db, node_handle="el-2-2-7-2-2")
    payload = {
        "lane": "PROCUREMENT",
        "handle": "el-2-2-7-2-2",
        "quantity": 20,
        "total_budget": 55000,
        "budget_scope": "total",
        "use_cases": ["game_development"],
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("I need equipment for a 20-person gaming studio, $55,000 total."),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.node_handle is None
    assert d.product_type_options == ("el-6-11-2", "el-2-2-7-2-2")
    assert d.source == "model+product_type_clarify"


def test_related_laptop_ancestor_resolves_to_specific_workload_host(db, monkeypatch):
    from src.app.services.taxonomy_registry import add_sold_node, get_node

    add_sold_node(db, node_handle="el-6-11-2")
    add_sold_node(db, node_handle="el-6-6")
    def _host(*_args, **_kwargs):
        return get_node("el-6-11-2")
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._grounded_use_case_host", _host)
    payload = {
        "lane": "FILTER",
        "handle": "el-6-6",
        "use_cases": ["game_development"],
        "subject_action": "continue",
        "confidence": 0.9,
    }

    d = route_turn(
        db,
        _env("Show stronger laptops for game development."),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert d.node_handle == "el-6-11-2"
    assert d.product_type_options == ()
    assert d.source == "model+specific_workload_host"


@pytest.mark.parametrize("model_lane", ["BULK", "BULK_QUOTE", "QUOTE", "RFQ"])
def test_procurement_lane_synonyms_are_clamped_to_existing_lane(db, model_lane):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-6")
    payload = {
        "lane": model_lane,
        "handle": "el-6-6",
        "use_cases": [],
        "requirements": {},
        "refine": {},
        "compare_targets": [],
        "confidence": 0.9,
    }
    decision = route_turn(
        db,
        _env("we need 25 laptops for our new office, can you do a bulk quote?"),
        llm_fn=lambda _prompt, _timeout: json.dumps(payload),
    )

    assert decision.lane == "PROCUREMENT"
    assert decision.source == "model"


def test_router_default_generation_budget_fits_bulk_decision(monkeypatch):
    from src.app.services.recommendation_core import turn_router

    seen = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"response": "{}"}

    def fake_post(url, json, timeout):
        seen.update(json)
        return _Response()

    monkeypatch.delenv("ROUTER_NUM_PREDICT", raising=False)
    monkeypatch.setattr("httpx.post", fake_post)
    turn_router._default_llm_fn("route this bulk request", 20)

    assert seen["options"]["num_predict"] == 320


def test_router_call_records_server_phase_metrics(monkeypatch):
    from src.app.services.recommendation_core import turn_router

    class _Response:
        status_code = 200

        def json(self):
            return {
                "response": "{}",
                "load_duration": 1_000_000,
                "prompt_eval_duration": 2_000_000,
                "eval_duration": 3_000_000,
                "prompt_eval_count": 40,
                "eval_count": 12,
            }

    monkeypatch.setattr("httpx.post", lambda *_args, **_kwargs: _Response())
    turn_router._default_llm_fn("route this", 20)

    metrics = turn_router.last_router_call_metrics()
    assert metrics["outcome"] == "ok"
    assert metrics["load_ms"] == 1.0
    assert metrics["prompt_eval_ms"] == 2.0
    assert metrics["decode_ms"] == 3.0
    assert metrics["prompt_tokens"] == 40
    assert metrics["output_tokens"] == 12


def test_custom_router_call_does_not_inherit_prior_model_metrics(db):
    from src.app.services.recommendation_core import turn_router

    turn_router._ROUTER_CALL_STATE.metrics = {"outcome": "stale", "wall_ms": 999}
    route_turn(
        db,
        _env("gaming laptop"),
        llm_fn=lambda _prompt, _timeout: json.dumps({
            "lane": "SEARCH", "handle": "el-6-6", "requirements": {},
        }),
    )

    assert turn_router.last_router_call_metrics() == {}


def test_router_failure_recovers_only_bounded_bulk_facts(db):
    from src.app.services.taxonomy_registry import add_sold_node

    add_sold_node(db, node_handle="el-6-11-2")
    decision = route_turn(
        db,
        _env("I need 20 gaming laptops for an esports lab, $1800 each within two weeks"),
        llm_fn=lambda _prompt, _timeout: '{"lane":"PROCUREMENT",',
    )

    assert decision.source == "fallback:model_unavailable"
    assert decision.lane == "PROCUREMENT"
    assert decision.node_handle == "el-6-11-2"
    assert decision.quantity == 20
    assert decision.budget_scope == "per_unit"
    assert decision.use_cases == ()
    assert decision.requirements == {}
