"""Phase 1d.4 — the unstocked-complement trust play. A declared complement (drawing → graphics
tablet) becomes a SOURCE-IT supplier-RFQ offer when not stocked, a bundle-upsell when stocked —
ONE KB declaration, stock truth (sells_within) picks the branch. Never blocks, never auto-sends."""
from types import SimpleNamespace

import src.app.services.taxonomy_registry as TR
from src.app.services import use_case_registry as R
from src.app.services.recommendation_core import core
from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope


def _env(**over):
    kw = dict(query="a laptop for drawing", uid="u", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


def _decision(**over):
    kw = dict(lane="SEARCH", requirements={"touchscreen": [("==", True)]},
              node_handle="el-6-6", use_cases=["drawing"])
    kw.update(over)
    return SimpleNamespace(**kw)


def test_registry_declares_drawing_complement():
    comps = R.complements("electronics", "drawing")
    assert comps and comps[0]["key"] == "graphics_tablet"
    assert comps[0]["node"] == "el-7-9-12-7"                       # the real Graphics Tablets node
    assert set(comps[0]["tags"]) == {"creative", "student", "hobby"}


def test_unstocked_complement_offers_to_source(monkeypatch):
    monkeypatch.setattr(TR, "sells_within", lambda db, h, tenant_id="default": False)   # not stocked
    resp = CoreResponse(envelope=_env(), lane="SEARCH")
    core._maybe_complement_offer(None, _env(), _decision(), resp)
    offers = resp.extras.get("complement_offers")
    assert offers and offers[0]["key"] == "graphics_tablet"
    assert offers[0]["mode"] == "source" and offers[0]["supplier_rfq_offer"] is True
    assert {o["id"] for o in offers[0]["options"]} == {"source_it", "in_catalog"}   # willing-to-wait CTA
    assert "creative" in offers[0]["tags"]


def test_stocked_complement_becomes_bundle_with_standalone(monkeypatch):
    monkeypatch.setattr(TR, "sells_within", lambda db, h, tenant_id="default": True)    # stocked
    resp = CoreResponse(envelope=_env(), lane="SEARCH")
    core._maybe_complement_offer(None, _env(), _decision(), resp)   # db=None → no price, still bundle
    off = resp.extras["complement_offers"][0]
    assert off["mode"] == "bundle" and off.get("supplier_rfq_offer") is None
    # bundle-with-your-laptop OR standalone (the complement-as-primary path for an existing device)
    assert {o["id"] for o in off["options"]} == {"add_bundle", "standalone"}


def test_no_declared_complement_no_offer(monkeypatch):
    monkeypatch.setattr(TR, "sells_within", lambda db, h, tenant_id="default": False)
    resp = CoreResponse(envelope=_env(), lane="SEARCH")
    core._maybe_complement_offer(None, _env(), _decision(use_cases=["gaming"]), resp)   # gaming: none
    assert "complement_offers" not in resp.extras


def test_guards_no_op(monkeypatch):
    monkeypatch.setattr(TR, "sells_within", lambda db, h, tenant_id="default": False)
    r = CoreResponse(envelope=_env(), lane="SEARCH", degraded=True)
    core._maybe_complement_offer(None, _env(), _decision(), r)
    assert "complement_offers" not in r.extras
    r2 = CoreResponse(envelope=_env(), lane="EXPLAIN")
    core._maybe_complement_offer(None, _env(), _decision(lane="EXPLAIN"), r2)
    assert "complement_offers" not in r2.extras
