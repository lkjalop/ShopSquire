"""Phase 4 step 3: the bounded brain — router clamps, plan validation, and THE ACCEPTANCE:
the corpus's three known_wrongs pass their expect_v2 assertions through the full core
(route → plan → execute → finalize → legacy adapter)."""
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
        "'{\"ram_gb\": 16, \"gpu_vram_gb\": 8, \"refresh_hz\": 120}','MSI'), "
        "('p2','LAP-2','Asus TUF 16in 120Hz Gaming Laptop',209900,"
        "'{\"ram_gb\": 32, \"gpu_vram_gb\": 12, \"refresh_hz\": 120}','Asus')"))
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    add_sold_node(s, node_handle="el-6-6")      # Laptops sold
    add_sold_node(s, node_handle="el-6-11-2")   # Gaming Laptops sold
    # per-product taxonomy truth — the retrieval index the core keys on
    upsert_classification(s, sku="LAP-1", node_handle="el-6-6", source="test", status="approved")
    upsert_classification(s, sku="LAP-2", node_handle="el-6-11-2", source="test", status="approved")
    yield s
    s.close()


def _route_stub(lane, handle, requirements=None, conf=0.9):
    return lambda p, t: json.dumps({"lane": lane, "handle": handle,
                                    "requirements": requirements or {}, "confidence": conf})


def _env(q, **kw):
    return TurnEnvelope.from_suggest_params(query=q, uid="u1", **kw)


# ── router clamps ─────────────────────────────────────────────────────────────

def test_router_defaults_on_garbage_model(db):
    for bad in ("", "not json", json.dumps({"lane": "INVENTED_LANE"})):
        d = route_turn(db, _env("gaming laptop"), llm_fn=lambda p, t, b=bad: b)
        assert d.lane == "SEARCH" and d.source == "default"


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


def test_workload_vertical_node_never_refused(db):
    """GPT-5.6 review-3 #6 (valorant 2/3): the model correctly maps a game to a Software
    (so-*) node; that's a WORKLOAD, not a product gap. Never refuse; drop the content node so
    retrieval does device search; keep requirements. Vertical-blind, no game regex."""
    d = route_turn(db, _env("i want to play valorant at 144fps"),
                   llm_fn=_route_stub("OFF_CATALOG", "so-3-1", {"refresh_hz": [">=", 144]}))
    assert d.lane != "OFF_CATALOG" and not d.refusal_granted
    assert d.node_handle is None                          # content node dropped -> device search
    assert d.requirements == {"refresh_hz": [(">=", 144.0)]}  # workload requirement kept
    # a Media (me-*) node behaves the same; a real product gap (forklift/bi) still refuses
    d2 = route_turn(db, _env("stream movies"), llm_fn=_route_stub("SEARCH", "me-1"))
    assert d2.node_handle is None
    d3 = route_turn(db, _env("do you sell forklifts?"), llm_fn=_route_stub("OFF_CATALOG", "bi-18"))
    assert d3.refusal_granted


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


def test_known_wrong_valorant_now_answers_with_closest_match(db):
    resp = recommend_turn(db, _env("i want to play valorant at 144fps"),
                          llm_fn=_route_stub("SEARCH", "el-6-11-2", {"refresh_hz": [">=", 144]}))
    payload = to_legacy(resp)
    assert expectation_met(payload, {"nonempty_message": True, "products_min": 1})
    assert resp.fit_summary["closest_match_mode"] is True
    assert "144" in resp.message                       # says WHY these are closest, not silent


def test_core_never_raises_and_degrades_honestly():
    resp = recommend_turn(None, _env("anything"), llm_fn=lambda p, t: "")
    assert resp.degraded and resp.message and resp.products == []
