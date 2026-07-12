"""Phase 4 step 2: evidence (tenant-scoped, budget-in-cents, degrade-on-error) and fit
(tri-state verdicts, unknown-honesty, closest-match) — the last stops before the brain."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core.evidence import (
    degraded_response,
    gather_evidence,
    refusal_allowed,
)
from src.app.services.recommendation_core.fit import build_cards, variant_attributes
from src.app.services.catalog_read_model import VariantView


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    s.execute(text(
        "CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "price_cents INT NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', image_url TEXT, specs TEXT, "
        "product_type TEXT, brand TEXT, category TEXT, attributes TEXT, active INTEGER DEFAULT 1, "
        "updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
    s.execute(text(
        "INSERT INTO products (id, sku, name, price_cents, specs, brand) VALUES "
        "('p1','LAP-1','MSI Thin 15in FHD 144Hz Gaming Laptop',169900,"
        "'{\"ram_gb\": 8, \"gpu_vram_gb\": 4}','MSI'), "
        "('p2','LAP-2','Asus TUF 16in 165Hz Gaming Laptop',209900,"
        "'{\"ram_gb\": 16, \"gpu_vram_gb\": 8}','Asus'), "
        "('p3','LAP-3','Mystery Laptop',99900,'{}','Acme')"))
    yield s
    s.close()


def _env(**over):
    kw = dict(query="gaming laptop", uid="u1", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


# ── evidence ──────────────────────────────────────────────────────────────────

def test_gather_evidence_budget_in_cents(db):
    b = gather_evidence(db, _env(budget_max=1800), text_query="laptop", mode="legacy")
    assert {v.sku for v in b.variants} == {"LAP-1", "LAP-3"}   # LAP-2 over $1800
    assert b.budget_filtered == 1 and b.total_before_budget == 3
    assert b.grounding in ("grounded", "empty")                # sqlite fixture has no sold set


def test_gather_evidence_never_raises_and_degrades():
    b = gather_evidence(None, _env())
    assert b.count == 0 and b.grounding == "error"
    resp = degraded_response(_env(), reason="db_unavailable")
    assert resp.degraded and resp.products == [] and "won't guess" in resp.message


def test_ungrounded_tenant_short_circuits_before_model(db):
    # M1.1: an un-onboarded tenant (no sold_taxonomy) must degrade WITHOUT a model call and
    # WITHOUT silent text-search garbage — grounding preserved as 'empty' for the facade/telemetry.
    from src.app.services.recommendation_core.core import recommend_turn
    called = {"model": False}
    def spy(p, t):
        called["model"] = True
        return "{}"
    r = recommend_turn(db, _env(), llm_fn=spy)   # db fixture has NO sold_taxonomy rows
    assert r.grounding == "empty" and r.degraded and r.products == []
    assert r.extras["degraded_reason"] == "catalog_not_onboarded"
    assert called["model"] is False              # short-circuited before the ~7s router call


def test_grounded_tenant_still_serves(db):
    from src.app.services.recommendation_core.core import recommend_turn
    from src.app.services.taxonomy_registry import add_sold_node
    add_sold_node(db, node_handle="el-6-6")      # onboard the tenant
    import json
    r = recommend_turn(db, _env(query="laptop"),
                       llm_fn=lambda p, t: json.dumps({"lane": "SEARCH", "handle": "el-6-6",
                                                       "use_cases": [], "confidence": 0.9}))
    assert r.grounding == "grounded" and not r.degraded   # grounded path unaffected by M1.1


def test_refusal_allowed_only_on_explicit_false(db):
    from src.app.services.taxonomy_registry import add_sold_node
    assert refusal_allowed(db, "el-6-2") is False      # ungrounded tenant: None -> never refuse
    add_sold_node(db, node_handle="el-6-6")
    assert refusal_allowed(db, "el-6-2") is True       # grounded + not covered -> refusable
    assert refusal_allowed(db, "el-6-6") is False      # sold -> never
    assert refusal_allowed(db, "not-a-node") is False  # unknown -> never


# ── fit ───────────────────────────────────────────────────────────────────────

REQ = {"ram_gb": (">=", 16), "gpu_vram_gb": (">=", 8)}


def _views(db):
    return gather_evidence(db, _env(), text_query="laptop", mode="legacy").variants


def test_fit_ranking_meets_then_unknown_then_fails(db):
    cards, summary = build_cards(_views(db), REQ)
    assert [c.sku for c in cards] == ["LAP-2", "LAP-3", "LAP-1"]
    assert summary["meets"] == 1 and summary["unknown"] == 1 and summary["fails"] == 1
    assert not summary["closest_match_mode"]
    assert cards[0].why == ["meets all 2 requirements"]
    assert "unverified" in cards[1].why[0]              # unknown ≠ fail, shown and labeled
    assert "below requirement" in cards[2].why[0]


def test_fit_closest_match_mode_when_nothing_meets(db):
    cards, summary = build_cards(_views(db), {"ram_gb": (">=", 64)})
    assert summary["meets"] == 0 and summary["closest_match_mode"] is True
    assert cards                                        # never an empty grid (valorant fix)


def test_variant_attributes_specs_win_title_backfills():
    v = VariantView(sku="X", title="Something 240Hz 17in", specs={"refresh_hz": 165})
    attrs = variant_attributes(v)
    assert attrs["refresh_hz"] == 165                   # structured beats marketing copy
    assert attrs["display_in"] == 17                    # but the title fills gaps


def test_integrated_gpu_derives_zero_vram_and_honestly_fails(db):
    """review-8 #5: an integrated laptop (gpu_discrete=false, no vram spec) derives gpu_vram_gb=0
    and FAILS a game's VRAM floor — an honest 'below requirement', not a wishy-washy 'unverified'.
    A discrete laptop with real vram MEETS. The derivation only fills MISSING keys."""
    integrated = VariantView(sku="IDEA", title="Lenovo IdeaPad 15 FHD Laptop", price_cents=90000,
                             specs={"gpu_discrete": False})
    discrete = VariantView(sku="LEGION", title="Lenovo Legion 15 Gaming Laptop", price_cents=190000,
                           specs={"gpu_discrete": True, "gpu_vram_gb": 8})
    assert variant_attributes(integrated)["gpu_vram_gb"] == 0        # derived: no discrete GPU ⇒ 0
    assert variant_attributes(discrete)["gpu_vram_gb"] == 8          # explicit vram untouched
    cards, summary = build_cards([discrete, integrated], {"gpu_vram_gb": (">=", 8)})
    by_sku = {c.sku: c for c in cards}
    assert by_sku["IDEA"].fit["overall"] == "fails"                  # honest fail, not "unknown"
    assert by_sku["LEGION"].fit["overall"] == "meets"
    assert [c.sku for c in cards] == ["LEGION", "IDEA"]              # meets ranks above fails


def test_derivation_never_overrides_explicit_vram(db):
    """An explicit catalog gpu_vram_gb wins even when gpu_discrete=false (contradictory catalog):
    structured data outranks the derivation (only_if_missing)."""
    v = VariantView(sku="ODD", title="Odd Laptop", specs={"gpu_discrete": False, "gpu_vram_gb": 6})
    assert variant_attributes(v)["gpu_vram_gb"] == 6


def test_workload_host_gate_separates_devices_from_accessories():
    """review-8 #4: a use-case/workload's device floors apply ONLY to a workload-host product.
    A gaming laptop (under el-6 Computers) is a host; a mouse (el-7-*), a bag (lb-*), and a laptop
    case (el-7-*) are not — so they never inherit gpu_vram_gb/ram_gb floors. Unknown/None node
    fails OPEN (never silently drop a floor we're unsure about)."""
    from src.app.services.recommendation_core.core import (_is_workload_host_product, _vertical_root)
    assert _is_workload_host_product("el-6-11-2") is True     # Gaming Laptops — a device
    assert _is_workload_host_product("el-7-9-12-11") is False  # Mice — an accessory
    assert _is_workload_host_product("lb-15") is False         # Laptop Bags — an accessory
    assert _is_workload_host_product("el-7-8-2-2") is False    # Laptop Hard Cases — an accessory
    assert _is_workload_host_product(None) is True             # unknown → fail-open


def test_vertical_root_keeps_broad_retry_in_vertical():
    """The empty-node broad retry is scoped to the vertical root so it can never cross verticals
    (electronics el-* vs pharmacy hb-*) — this is what killed the 'mouse → hand sanitiser' bleed."""
    from src.app.services.recommendation_core.core import _vertical_root
    assert _vertical_root("el-7-9-12-11") == "el"   # a mouse broadens within Electronics, not hb-*
    assert _vertical_root("el-6-11-2") == "el"
    assert _vertical_root(None) is None


def test_sort_price_asc_promotes_price_above_relevance_never_above_truth(db):
    """R9.2 'show me cheaper ones': sort reorders by price WITHIN fit-truth tiers — the cheap
    FAILING unit still ranks below meeting pricier ones; among meets, cheaper wins even when
    retrieval relevance says otherwise."""
    pricey = VariantView(sku="MEET-PRICEY", title="Big 32GB", price_cents=300000,
                         specs={"ram_gb": 32})
    cheap = VariantView(sku="MEET-CHEAP", title="Fine 16GB", price_cents=150000,
                        specs={"ram_gb": 16})
    cheapest_fail = VariantView(sku="FAIL-CHEAPEST", title="Weak 8GB", price_cents=90000,
                                specs={"ram_gb": 8})
    variants = [pricey, cheap, cheapest_fail]      # retrieval order: pricey most relevant
    default_cards, _ = build_cards(variants, {"ram_gb": (">=", 16)})
    assert [c.sku for c in default_cards] == ["MEET-PRICEY", "MEET-CHEAP", "FAIL-CHEAPEST"]
    sorted_cards, _ = build_cards(variants, {"ram_gb": (">=", 16)}, sort="price_asc")
    assert [c.sku for c in sorted_cards] == ["MEET-CHEAP", "MEET-PRICEY", "FAIL-CHEAPEST"]


def test_bind_compare_targets_df_discipline():
    """R9.3 binding: a df==1 token identifies; a tie never binds; <2 bound → None (keep slate)."""
    from src.app.services.recommendation_core.core import _bind_compare_targets
    a = VariantView(sku="A", title="Dell G16 7630 16in Gaming Laptop")
    b = VariantView(sku="B", title="Lenovo LOQ 15IRH8 Gaming Laptop")
    c = VariantView(sku="C", title="ASUS ROG Strix G16-ish Gaming Laptop RTX")
    slate = [a, b, c]
    # 'g16' appears in A and C (df=2) but '7630'/'dell' are unique → binds A; 'lenovo' unique → B
    pair = _bind_compare_targets(slate, ("dell g16", "lenovo legion"))
    assert [v.sku for v in pair] == ["A", "B"]          # target order, LAP names bound
    # only one target binds → None (never narrow a compare to a single unit)
    assert _bind_compare_targets(slate, ("dell 7630", "rolex submariner")) is None
    # ambiguous tie: twins share every token → target stays unbound → None
    t1 = VariantView(sku="T1", title="Acme Box 500")
    t2 = VariantView(sku="T2", title="Acme Box 500")
    assert _bind_compare_targets([t1, t2, a], ("acme box", "dell g16")) is None


def test_no_requirements_means_price_ranked_no_verdicts(db):
    cards, summary = build_cards(_views(db))
    assert [c.sku for c in cards] == ["LAP-3", "LAP-1", "LAP-2"]
    assert all(c.fit is None for c in cards) and summary["closest_match_mode"] is False


def test_preferred_nearness_never_outranks_fit_truth():
    """review-9 #3: preferred is a SOFT tiebreak — a FAILING product spot-on the preferred value
    still ranks below a MEETING product far from it (lexicographic guarantee)."""
    perfect_pref_but_fails = VariantView(sku="FAIL-PREF", title="Weak 16GB", price_cents=100000,
                                         specs={"ram_gb": 16, "gpu_vram_gb": 2})
    meets_far_from_pref = VariantView(sku="MEET-FAR", title="Big 64GB", price_cents=300000,
                                      specs={"ram_gb": 64, "gpu_vram_gb": 8})
    cards, _ = build_cards([perfect_pref_but_fails, meets_far_from_pref],
                           {"gpu_vram_gb": (">=", 8)}, preferred={"ram_gb": 16.0})
    assert [c.sku for c in cards] == ["MEET-FAR", "FAIL-PREF"]   # truth above preference


def test_preferred_breaks_ties_within_meets_above_relevance():
    """Among products that MEET, closer-to-recommended beats retrieval relevance."""
    far = VariantView(sku="MEET-64", title="Big 64GB", price_cents=200000,
                      specs={"ram_gb": 64, "gpu_vram_gb": 8})
    near = VariantView(sku="MEET-16", title="Right 16GB", price_cents=200000,
                       specs={"ram_gb": 16, "gpu_vram_gb": 8})
    # retrieval order favors the FAR one; preference flips it
    plain, _ = build_cards([far, near], {"gpu_vram_gb": (">=", 8)})
    assert [c.sku for c in plain] == ["MEET-64", "MEET-16"]      # relevance order without pref
    cards, _ = build_cards([far, near], {"gpu_vram_gb": (">=", 8)}, preferred={"ram_gb": 16.0})
    assert [c.sku for c in cards] == ["MEET-16", "MEET-64"]      # nearness wins the tiebreak


def test_explicit_sort_beats_preference():
    """'show me cheaper ones' is a STATED ask — it outranks the soft KB preference."""
    near_pricey = VariantView(sku="NEAR-PRICEY", title="Right 16GB", price_cents=300000,
                              specs={"ram_gb": 16, "gpu_vram_gb": 8})
    far_cheap = VariantView(sku="FAR-CHEAP", title="Big 64GB", price_cents=150000,
                            specs={"ram_gb": 64, "gpu_vram_gb": 8})
    cards, _ = build_cards([near_pricey, far_cheap], {"gpu_vram_gb": (">=", 8)},
                           sort="price_asc", preferred={"ram_gb": 16.0})
    assert [c.sku for c in cards] == ["FAR-CHEAP", "NEAR-PRICEY"]   # stated sort first
