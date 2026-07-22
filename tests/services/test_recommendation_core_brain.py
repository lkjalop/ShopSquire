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


def _route_stub(lane, handle, requirements=None, conf=0.9, refine=None):
    return lambda p, t: json.dumps({"lane": lane, "handle": handle,
                                    "requirements": requirements or {}, "confidence": conf,
                                    **({"refine": refine} if refine else {})})


def _env(q, **kw):
    kw.setdefault("currency", "USD")
    return TurnEnvelope.from_suggest_params(query=q, uid="u1", **kw)


# ── router clamps ─────────────────────────────────────────────────────────────

def test_router_bounded_fallback_on_garbage_model(db):
    for bad in ("", "not json", json.dumps({"lane": "INVENTED_LANE"})):
        d = route_turn(db, _env("gaming laptop"), llm_fn=lambda p, t, b=bad: b)
        assert d.lane == "SEARCH" and d.source.startswith("fallback:")
        assert d.requirements == {} and d.use_cases == ()


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
    assert [p.sku for p in resp.products] == ["LAP-2"]             # the node's own subtree


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
    assert inferred == "el-6"

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
    # MSI exists in the catalog (clamp passes) but not under Gaming Laptops (el-6-11-2 has
    # only LAP-2/Asus classified) → zero matches within the node
    resp = recommend_turn(db, _env("only msi gaming laptops", session={}),
                          llm_fn=_route_stub("FILTER", "el-6-11-2", refine={"brand": "MSI"}))
    assert resp.products == []
    assert "MSI" in resp.message                                  # honest, names the brand


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
                                        "requirements": {"ram_gb": [[">=", 16]]}}}
    resp = recommend_turn(db, _env("gaming laptop", session=session),
                          llm_fn=_route_stub("SEARCH", "el-6-11-2"))
    cu = resp.extras["constraints_used"]
    assert cu["budget_max_cents"] is None and cu["budget_inherited"] is False
    assert "ram_gb" not in (cu["requirements"] or {})


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


def test_search_lane_continuation_inherits_prior_bulk_quantity(db):
    payload = {"lane": "SEARCH", "handle": "el-6-6", "requirements": {},
               "quantity": None, "subject_action": "continue", "confidence": 0.9}
    session = {"prior_node": "el-6-6", "accepted_constraints": {"quantity": 25}}
    resp = recommend_turn(
        db,
        _env("which of these has the best battery life?", session=session),
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


def test_active_procurement_uses_model_continuity_to_correct_policy_conflict(db):
    session = {"prior_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"]}

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
    session = {"active_workflow_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"]}
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
    session = {"active_workflow_lane": "PROCUREMENT", "shortlist_skus": ["LAP-1"]}
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
    llm = lambda _p, _t: json.dumps({
        "lane": "SEARCH", "handle": None, "requirements": {},
        "subject_action": "switch", "confidence": 0.9,
    })
    resp = recommend_turn(db, env, llm_fn=llm)
    decision = resp.extras["decision"]
    assert decision["node_handle"] == "el-6-6"
    assert decision["subject_from_session"] is True


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
