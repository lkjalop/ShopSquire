"""Phase 1c — the intelligent variant clarifier. Ask ONE question only when a use-case's variants
(from use_case_registry) spread the floor materially AND the shopper hasn't anchored it: no budget
→ ask; budget given → state an assumption (the floor logic picks the tier); query already names a
level → pin it silently. Content-advisory (minor + mature game) surfaces, never blocks."""
from types import SimpleNamespace

from src.app.services.recommendation_core import core
from src.app.services.recommendation_core.envelope import CoreResponse, TurnEnvelope


def _env(**over):
    kw = dict(query="a gaming laptop", uid="u", tenant_id="default")
    kw.update(over)
    return TurnEnvelope.from_suggest_params(**kw)


def _decision(**over):
    kw = dict(lane="SEARCH", requirements={"ram_gb": [(">=", 16)]},
              node_handle="el-6-11", use_cases=["gaming"])
    kw.update(over)
    return SimpleNamespace(**kw)


def _clar(resp, cid):
    return next((c for c in resp.clarify if c.get("id") == cid), None)


# ── no budget + material variant spread → ask ONE question, labeled by band ──────

def test_no_budget_multi_variant_asks():
    env = _env()
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(), resp)
    q = _clar(resp, "variant_gaming")
    assert q and q["goal"] == "pick_use_case_variant"
    ids = {o["id"] for o in q["options"]}
    assert "base" in ids and "aaa_heavy" in ids               # standard + named levels offered
    assert any("$" in o["label"] for o in q["options"])       # each labeled by its band hint


def test_drawing_casual_vs_heavy():
    env = _env(query="a laptop for drawing")
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(use_cases=["drawing"]), resp)
    q = _clar(resp, "variant_drawing")
    assert q and {o["id"] for o in q["options"]} == {"base", "pen_precision"}   # standard vs heavy painting


# ── budget given → state an assumption, don't nag ───────────────────────────────

def test_with_budget_states_assumption_not_ask():
    env = _env(budget_max=1500)
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(), resp)
    assert not resp.clarify
    assert resp.extras["assumption"]["use_case"] == "gaming"
    assert resp.extras["assumption"]["variant"] is None


# ── the query already names a level → pin it silently ───────────────────────────

def test_query_names_variant_pins_silently():
    env = _env(query="a competitive gaming laptop")
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(), resp)
    assert not resp.clarify
    assert resp.extras["assumption"]["variant"] == "competitive"


# ── a single-variant / no-variant use-case never asks ───────────────────────────

def test_single_variant_usecase_does_not_ask():
    env = _env(query="an everyday laptop")
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(use_cases=["general"]), resp)   # general has no variants
    assert not resp.clarify and "assumption" not in resp.extras


# ── content-advisory surfaces (never blocks) ────────────────────────────────────

def test_content_advisory_surfaces_never_blocks():
    env = _env(query="a laptop for high school")
    resp = CoreResponse(envelope=env, lane="SEARCH")
    core._maybe_variant_clarify(env, _decision(use_cases=["high_school"]), resp)
    advs = resp.extras.get("advisories") or []
    assert any(a.get("persona") == "minor" for a in advs)
    assert _clar(resp, "variant_high_school") is not None      # still asks (multi-variant)
    assert not resp.off_catalog and not resp.degraded          # advisory never blocks


# ── guards: not a fresh search / degraded / a clarify already claimed the slot ──

def test_guards_no_op():
    env = _env()
    r = CoreResponse(envelope=env, lane="EXPLAIN")
    core._maybe_variant_clarify(env, _decision(lane="EXPLAIN"), r)
    assert not r.clarify
    r2 = CoreResponse(envelope=env, lane="SEARCH", degraded=True)
    core._maybe_variant_clarify(env, _decision(), r2)
    assert not r2.clarify
    r3 = CoreResponse(envelope=env, lane="SEARCH")
    r3.clarify = [{"id": "existing"}]
    core._maybe_variant_clarify(env, _decision(), r3)
    assert [c["id"] for c in r3.clarify] == ["existing"]        # conflict/tradeoff clarify wins
