"""Phase 1b — the 3-band right-side shelf (extras["shelf"]): a PARTITION of the ranked cards into
best_fit / stretch-or-more-capable / preference. Core-agnostic, adaptive, deduped, honest. The key
sharpening under test: band 2 "more capable" is capability HEADROOM (exceeds a requirement), NEVER
merely pricier — a same-spec brand premium is not "more capable"."""
from types import SimpleNamespace

from src.app.services.catalog_read_model import VariantView
from src.app.services.recommendation_core import core
from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard, TurnEnvelope
from src.app.services.recommendation_core.fit import build_cards

REQ = {"ram_gb": [(">=", 16)]}


def _env(**over):
    kw = dict(query="gaming laptop", uid="u1", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


def _decision(**over):
    kw = dict(lane="SEARCH", requirements=REQ, node_handle="el-6-11", use_cases=["gaming"])
    kw.update(over)
    return SimpleNamespace(**kw)


def card(sku, price, overall="meets", exceeds=None, brand=""):
    return ProductCard(sku=sku, title=sku, price_cents=price, brand=brand,
                       fit={"overall": overall, "per_key": {}, "exceeds": list(exceeds or [])})


def _by_id(shelf, band_id):
    return next(b for b in shelf["bands"] if b["id"] == band_id)


# ── fit.py surfaces per-card capability headroom ────────────────────────────────

def test_build_cards_marks_capability_headroom():
    base = VariantView(sku="BASE", title="Laptop", price_cents=100000, specs={"ram_gb": 16, "gpu_vram_gb": 8})
    over = VariantView(sku="OVER", title="Laptop", price_cents=200000, specs={"ram_gb": 32, "gpu_vram_gb": 12})
    cards, _ = build_cards([base, over], {"ram_gb": [(">=", 16)], "gpu_vram_gb": [(">=", 8)]})
    by = {c.sku: c for c in cards}
    assert by["BASE"].fit["exceeds"] == []                         # meets exactly → no headroom
    assert set(by["OVER"].fit["exceeds"]) == {"ram_gb", "gpu_vram_gb"}


# ── within budget: band 2 is HEADROOM, not price; deduped; fails excluded ────────

def test_more_capable_is_headroom_not_just_pricier():
    env = _env(budget_max=2500)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [
        card("M1", 100000), card("M2", 110000), card("M3", 120000),        # cheapest meets, no headroom
        card("HDR1", 150000, exceeds=["ram_gb"]),
        card("HDR2", 180000, exceeds=["ram_gb", "gpu_vram_gb"]),
        card("PRICEY_NOHDR", 240000, exceeds=[]),                          # pricier, NO headroom
        card("FAIL", 90000, overall="fails"),
    ]
    resp.extras["capability"] = {"verdict": "within_budget", "floor_cents": 100000}
    resp.message = "in budget"
    core._build_shelf(None, env, _decision(), resp, 10)
    shelf = resp.extras["shelf"]
    assert [b["id"] for b in shelf["bands"]] == ["best_fit", "more_capable"]
    assert _by_id(shelf, "best_fit")["skus"] == ["M1", "M2", "M3"]
    assert _by_id(shelf, "more_capable")["skus"] == ["HDR2", "HDR1"]        # more headroom first, then price
    allskus = [s for b in shelf["bands"] for s in b["skus"]]
    assert "PRICEY_NOHDR" not in allskus            # pricier ≠ more capable (the sharpening)
    assert "FAIL" not in allskus                    # a failing product is never in a meets band
    assert len(allskus) == len(set(allskus))        # deduped: a product in exactly one band


# ── below budget: the stretch band = above-budget meets, cheapest (the floor) first ──

def test_below_budget_stretch_band(monkeypatch):
    env = _env(budget_max=900)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [card("CLAM", 65000, overall="fails")]                  # closest in budget (honest fail)
    resp.extras["capability"] = {"verdict": "below_budget", "floor_cents": 119900}
    resp.message = "nothing at $900..."
    monkeypatch.setattr(core, "_budget_free_cards", lambda *a, **k: [
        card("DELL", 119900), card("YOGA", 149900), card("CLAM", 65000, overall="fails")])
    core._build_shelf(None, env, _decision(), resp, 10)
    shelf = resp.extras["shelf"]
    assert [b["id"] for b in shelf["bands"]] == ["best_fit", "stretch"]
    assert _by_id(shelf, "best_fit")["skus"] == ["CLAM"]                    # closest-in-budget, labeled fail
    stretch = _by_id(shelf, "stretch")
    assert stretch["skus"] == ["DELL", "YOGA"]                             # cheapest meets first (the floor)
    assert "1,199" in stretch["label"]
    assert shelf["banner"]["kind"] == "below_budget" and shelf["banner"]["floor_cents"] == 119900


# ── the preference band lights up ONLY on a stated preference signal ────────────

def test_preference_band_only_on_signal():
    env = _env(budget_max=3000)
    products = [card("D1", 100000, brand="Dell"), card("D2", 110000, brand="HP"),
                card("D3", 120000, brand="Asus"), card("MAC", 287900, brand="Apple")]
    # with an Apple preference → the Mac (4th-ranked meets, not in band 1) becomes its own band
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = list(products)
    resp.extras["capability"] = {"verdict": "within_budget", "floor_cents": 100000}
    resp.message = "x"
    core._build_shelf(None, env, _decision(preferred_brand="apple"), resp, 10)
    shelf = resp.extras["shelf"]
    assert [b["id"] for b in shelf["bands"]] == ["best_fit", "preference"]
    pref = _by_id(shelf, "preference")
    assert pref["skus"] == ["MAC"] and pref["basis"] == "brand:apple"
    # without a preference → the band is simply omitted (adaptive)
    resp2 = CoreResponse(envelope=env, lane="SEARCH")
    resp2.products = list(products)
    resp2.extras["capability"] = {"verdict": "within_budget", "floor_cents": 100000}
    resp2.message = "x"
    core._build_shelf(None, env, _decision(), resp2, 10)
    assert "preference" not in [b["id"] for b in resp2.extras["shelf"]["bands"]]


# ── adaptive: a thin catalog collapses to a single band, never fabricates empties ──

def test_adaptive_single_band_when_thin():
    env = _env(budget_max=2000)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [card("ONLY", 150000)]         # one meets, no headroom, no preference
    resp.extras["capability"] = {"verdict": "within_budget", "floor_cents": 150000}
    resp.message = "x"
    core._build_shelf(None, env, _decision(), resp, 10)
    assert [b["id"] for b in resp.extras["shelf"]["bands"]] == ["best_fit"]


# ── guards: no shelf off the product lanes / degraded / no requirements ──────────

def test_shelf_guards_no_op():
    env = _env(budget_max=900)
    r = CoreResponse(envelope=env, lane="SEARCH", degraded=True)
    core._build_shelf(None, env, _decision(), r, 10)
    assert "shelf" not in r.extras
    r2 = CoreResponse(envelope=env, lane="SEARCH")
    core._build_shelf(None, env, _decision(requirements={}), r2, 10)
    assert "shelf" not in r2.extras
    r3 = CoreResponse(envelope=env, lane="EXPLAIN")
    core._build_shelf(None, env, _decision(lane="EXPLAIN"), r3, 10)
    assert "shelf" not in r3.extras
