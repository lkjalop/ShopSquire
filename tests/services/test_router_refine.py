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
