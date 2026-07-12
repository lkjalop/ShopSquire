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
