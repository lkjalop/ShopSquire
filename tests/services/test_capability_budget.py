"""Phase 1a — the budget × capability "smart moment". The capability FLOOR is DERIVED from the
real catalog (cheapest product that MEETS the resolved requirements), then the turn branches on
the shopper's budget: state the floor (no budget), confirm within budget, or offer an honest
tradeoff when budget < floor (never a silent empty grid). The drawing→touchscreen→$1199 scenario
the platform is meant to be smart about, proven at the branch level."""
from types import SimpleNamespace

from src.app.services.catalog_read_model import VariantView
from src.app.services.recommendation_core import core
from src.app.services.recommendation_core.core import _apply_capability_budget, _budget_free_floor
from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard, TurnEnvelope
from src.app.services.recommendation_core.evidence import EvidenceBundle
from src.app.services.recommendation_core.fit import build_cards

# drawing = a touchscreen 2-in-1/detachable with real RAM — the decision's authoritative shape
# ({key: [(op, thr), ...]}, M2-B1), NOT the registry's [op, value] shape.
DRAW_REQ = {"touchscreen": [("==", True)],
            "form_factor": [("in", ["convertible", "detachable", "tablet"])],
            "ram_gb": [(">=", 16)]}


def _env(**over):
    kw = dict(query="a laptop for drawing", uid="u1", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


def _decision(**over):
    kw = dict(lane="SEARCH", requirements=DRAW_REQ, node_handle="el-6-11", use_cases=["drawing"])
    kw.update(over)
    return SimpleNamespace(**kw)


# ── the floor is DERIVED from the candidate set, never stored ───────────────────

def test_build_cards_surfaces_capability_floor():
    clam = VariantView(sku="CLAM", title="Plain Clamshell Laptop", price_cents=65000, specs={"ram_gb": 16})
    dell = VariantView(sku="DELL", title="Dell Inspiron 14 2-in-1 Laptop", price_cents=119900, specs={"ram_gb": 16})
    yoga = VariantView(sku="YOGA", title="Lenovo Yoga Slim 7i 2-in-1 Laptop", price_cents=149900, specs={"ram_gb": 16})
    # cheapest MEETS = the Dell 2-in-1 ($1199); the cheaper clamshell fails the touch/form capability
    _, summary = build_cards([clam, dell, yoga], DRAW_REQ)
    assert summary["capability_floor_cents"] == 119900


# ── no budget → state the floor + the spread ────────────────────────────────────

def test_floor_stated_when_no_budget():
    env = _env()
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [ProductCard(sku="DELL", title="Dell 2-in-1", price_cents=119900, fit={"overall": "meets"}),
                     ProductCard(sku="YOGA", title="Yoga", price_cents=149900, fit={"overall": "meets"})]
    resp.fit_summary = {"meets": 2, "unknown": 0, "fails": 0, "capability_floor_cents": 119900,
                        "requirements": {}}
    _apply_capability_budget(None, env, _decision(), resp, 10)
    cap = resp.extras["capability"]
    assert cap["verdict"] == "floor_stated" and cap["floor_cents"] == 119900
    assert "1,199" in resp.message and "1,499" in resp.message and "drawing" in resp.message


# ── budget ≥ floor → within budget ──────────────────────────────────────────────

def test_within_budget_confirms_floor():
    env = _env(budget_max=2000)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [ProductCard(sku="DELL", title="Dell 2-in-1", price_cents=119900, fit={"overall": "meets"})]
    resp.fit_summary = {"meets": 1, "unknown": 0, "fails": 0, "capability_floor_cents": 119900,
                        "requirements": {}}
    _apply_capability_budget(None, env, _decision(), resp, 10)
    cap = resp.extras["capability"]
    assert cap["verdict"] == "within_budget" and cap["probed_budget_free"] is False
    assert "within your $2,000 budget" in resp.message


# ── budget < floor → honest tradeoff, never empty (the drawing $900 case) ───────

def test_below_budget_offers_tradeoff(monkeypatch):
    # nothing at $900 meets → the branch probes the budget-free cards and offers the tradeoff
    monkeypatch.setattr(core, "_budget_free_cards",
                        lambda *a, **k: [ProductCard(sku="DELL", title="Dell 2-in-1",
                                                     price_cents=119900, fit={"overall": "meets"})])
    env = _env(budget_max=900)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    resp.products = [ProductCard(sku="CLAM", title="Clamshell", price_cents=65000, fit={"overall": "fails"})]
    resp.fit_summary = {"meets": 0, "unknown": 0, "fails": 1, "capability_floor_cents": None,
                        "requirements": {}}
    _apply_capability_budget(None, env, _decision(), resp, 10)
    cap = resp.extras["capability"]
    assert cap["verdict"] == "below_budget" and cap["probed_budget_free"] is True
    assert "900" in resp.message and "1,199" in resp.message
    tradeoff = [c for c in resp.clarify if c.get("id") == "capability_budget_tradeoff"]
    assert tradeoff, "a structured tradeoff clarify is offered"
    assert {o["id"] for o in tradeoff[0]["options"]} == {"stretch", "relax", "closest"}


# ── the probe genuinely IGNORES the ceiling (finds the above-budget match) ───────

def test_budget_free_floor_ignores_ceiling(monkeypatch):
    seen = {}

    def fake_gather(db, env, *, node_handle=None, limit=50):
        seen["bmax"], seen["bmin"], seen["node"] = env.budget_max_cents, env.budget_min_cents, node_handle
        b = EvidenceBundle(status="ok")
        b.variants = [
            VariantView(sku="CLAM", title="Plain Clamshell Laptop", price_cents=65000, specs={"ram_gb": 16}),
            VariantView(sku="DELL", title="Dell Inspiron 14 2-in-1 Laptop", price_cents=119900, specs={"ram_gb": 16}),
        ]
        return b

    monkeypatch.setattr(core, "gather_evidence", fake_gather)
    floor = _budget_free_floor(None, _env(budget_max=900), _decision(), 10)
    assert seen["bmax"] is None and seen["bmin"] is None      # the probe cleared the ceiling
    assert seen["node"] is not None      # scoped to the device host FAMILY (union of host nodes)
    assert floor == 119900        # the $1199 2-in-1 above the $900 ceiling; the clamshell can't meet


def test_budget_free_probe_respects_hard_brand_filter(monkeypatch):
    """Review finding #1: on a HARD 'only Dell' filter the budget-free floor must be an in-BRAND
    product — never leak a cheaper off-brand one into 'the cheapest that meets is $X'."""
    def fake_gather(db, env, *, node_handle=None, limit=50):
        b = EvidenceBundle(status="ok")
        b.variants = [
            VariantView(sku="LENOVO", title="Lenovo 14 2-in-1 Laptop", price_cents=99900,
                        specs={"ram_gb": 16}, brand="Lenovo"),    # cheaper, meets, but OFF-brand
            VariantView(sku="DELL", title="Dell Inspiron 14 2-in-1 Laptop", price_cents=139900,
                        specs={"ram_gb": 16}, brand="Dell"),
        ]
        return b
    monkeypatch.setattr(core, "gather_evidence", fake_gather)
    floor = _budget_free_floor(None, _env(budget_max=900), _decision(brand_filter="Dell"), 10)
    assert floor == 139900        # the Dell, NOT the cheaper off-brand Lenovo


# ── guards: no-op off the product lanes / degraded / no requirements ─────────────

def test_no_op_when_degraded_or_no_requirements():
    env = _env(budget_max=900)
    # degraded turn: never claims a floor
    resp = CoreResponse(envelope=env, lane="SEARCH", degraded=True)
    resp.fit_summary = {"meets": 0, "capability_floor_cents": None}
    _apply_capability_budget(None, env, _decision(), resp, 10)
    assert "capability" not in resp.extras
    # no requirements asserted: nothing to price against
    resp2 = CoreResponse(envelope=env, lane="SEARCH")
    _apply_capability_budget(None, env, _decision(requirements={}), resp2, 10)
    assert "capability" not in resp2.extras
    # a COMPARE/EXPLAIN lane is not a fresh capability search
    resp3 = CoreResponse(envelope=env, lane="EXPLAIN")
    _apply_capability_budget(None, env, _decision(lane="EXPLAIN"), resp3, 10)
    assert "capability" not in resp3.extras
