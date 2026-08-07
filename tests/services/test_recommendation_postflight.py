"""Shared postflight: session writeback (the multi-turn memory the facade reads) + telemetry,
best-effort and round-trippable through the facade's session reader."""
from src.app.services import recommendation_facade as F
from src.app.services.memory import Memory
from src.app.services.recommendation_postflight import run_postflight, write_session
from src.app.services.recommendation_core.envelope import CoreResponse, ProductCard, TurnEnvelope


class _Redis:
    def __init__(self): self.store = {}
    def get(self, k): return self.store.get(k)
    def setex(self, k, ttl, v): self.store[k] = v
    def set(self, k, v): self.store[k] = v


def _env(**o):
    return TurnEnvelope.from_suggest_params(query="gaming laptop", uid="u1", tenant_id="t1", **o)


def _core(env, **o):
    c = CoreResponse(envelope=env, lane="SEARCH",
                     products=[ProductCard(sku="LAP-1", title="X"), ProductCard(sku="LAP-2", title="Y")])
    c.extras["decision"] = {"node_handle": "el-6-6", "requirements": {"ram_gb": [">=", 16]}}
    c.extras["intent"] = {"use_cases": ["gaming"]}
    for k, v in o.items():
        setattr(c, k, v)
    return c


def _raw(redis, *, tenant_id="t1", uid="u1"):
    return Memory(redis, tenant_id=tenant_id).get_structured_state(uid)


def test_session_write_roundtrips_through_facade_reader():
    r = _Redis()
    env = _env(budget_max=2000)
    assert write_session(r, env, _core(env)) is True
    # the facade reads it back next turn (tenant-scoped key)
    slice_ = F._read_session_slice(r, "u1", "t1")
    assert slice_["prior_node"] == "el-6-6" and slice_["shortlist_skus"] == ["LAP-1", "LAP-2"]
    assert slice_["prior_lane"] == "SEARCH"
    assert slice_["active_workflow_lane"] is None
    # persisted content is complete for prior-subject resolution
    raw = _raw(r)
    assert raw["last_lane"] == "SEARCH" and raw["constraints"]["use_cases"] == ["gaming"]
    assert raw["constraints"]["budget_max_cents"] == 200000


def test_followup_without_budget_refreshes_not_wipes():
    """R9.1 (screenshot 30's loss point): T1 'show me cheaper' has NO envelope budget, but the
    core inherited the session's — constraints_used carries what was USED, and the writeback
    persists THAT, so the remembered budget survives the follow-up instead of being nulled."""
    r = _Redis()
    env = _env()                       # no budget on the follow-up envelope
    core = _core(env)
    core.extras["constraints_used"] = {"budget_min_cents": None, "budget_max_cents": 230000,
                                       "requirements": {"ram_gb": [[">=", 16]]},
                                       "budget_inherited": True}
    assert write_session(r, env, core) is True
    raw = _raw(r)
    assert raw["constraints"]["budget_max_cents"] == 230000        # refreshed, not wiped
    assert raw["constraints"]["requirements"] == {"ram_gb": [[">=", 16]]}


def test_inferred_retrieval_subject_is_persisted():
    r = _Redis()
    env = _env()
    core = _core(env)
    core.extras["decision"]["node_handle"] = None
    core.extras["constraints_used"] = {"node_handle": "el-6-6"}

    assert write_session(r, env, core) is True
    raw = _raw(r)
    assert raw["last_node_handle"] == "el-6-6"


def test_followup_without_products_or_quantity_preserves_prior_slice():
    import dataclasses
    r = _Redis()
    env = dataclasses.replace(_env(), session={
        "prior_node": "el-6-6",
        "shortlist_skus": ["LAP-OLD"],
        "accepted_constraints": {"quantity": 25, "total_budget_cents": 4000000,
                                 "budget_scope": "total"},
    })
    core = CoreResponse(envelope=env, lane="COMPARE", products=[])
    core.extras["decision"] = {"node_handle": None, "quantity": None,
                               "total_budget_cents": None}
    assert write_session(r, env, core) is True
    raw = _raw(r)
    assert raw["last_node_handle"] == "el-6-6"
    assert raw["last_shortlist_skus"] == ["LAP-OLD"]
    assert raw["constraints"]["quantity"] == 25
    assert raw["constraints"]["total_budget_cents"] == 4000000
    assert raw["constraints"]["budget_scope"] == "total"


def test_followup_preserves_prior_brand_constraints_when_not_replaced():
    import dataclasses
    r = _Redis()
    env = dataclasses.replace(_env(), session={
        "accepted_constraints": {
            "brand_filter": "Lenovo",
            "exclude_brand": "Apple",
            "preferred_brand": "Dell",
        },
    })
    core = _core(env)
    core.extras["decision"].update({
        "brand_filter": None,
        "exclude_brand": None,
        "preferred_brand": None,
    })
    assert write_session(r, env, core) is True
    constraints = _raw(r)["constraints"]
    assert constraints["brand_filter"] == "Lenovo"
    assert constraints["exclude_brand"] == "Apple"
    assert constraints["preferred_brand"] == "Dell"


def test_named_workload_entities_roundtrip_for_consent_retry():
    r = _Redis()
    env = _env()
    core = _core(env)
    core.extras["decision"]["workload_entities"] = [["game", "Black Myth Wukong"]]

    assert write_session(r, env, core) is True
    constraints = _raw(r)["constraints"]
    assert constraints["workload_entities"] == [["game", "Black Myth Wukong"]]


def test_accepted_semantic_evidence_and_fit_explanation_roundtrip():
    r = _Redis()
    env = _env()
    core = _core(env)
    core.extras["semantic_resolution"] = {
        "outcome": "proceed_catalog",
        "catalog_authority": "permitted",
        "desired_outcome": "simulate mechanical-machine maintenance",
        "interpretation_confidence": 0.83,
        "evidence": [{"source_id": "official-provider", "claim_status": "verified"}],
    }
    core.extras["semantic_requirement_compilation"] = {
        "status": "accepted",
        "compiled_requirements": [{
            "attribute_key": "ram_gb",
            "operator": ">=",
            "value": 32,
            "unit": "GB",
            "source_claim_ids": ["official:ram"],
        }],
        "commercial_authority_granted": False,
    }
    core.extras["explanation"] = {
        "sku": "LAP-1",
        "workload_summary": "simulate mechanical-machine maintenance",
        "fit_ledger": [],
    }

    assert write_session(r, env, core) is True
    raw = _raw(r)
    assert raw["semantic_resolution"]["catalog_authority"] == "permitted"
    assert raw["semantic_requirement_compilation"]["compiled_requirements"][0][
        "source_claim_ids"
    ] == ["official:ram"]
    assert raw["last_product_explanation"]["sku"] == "LAP-1"

    slice_ = F._read_session_slice(r, "u1", "t1")
    assert slice_["semantic_resolution"]["desired_outcome"] == (
        "simulate mechanical-machine maintenance"
    )
    assert slice_["semantic_requirement_compilation"]["status"] == "accepted"


def test_explicit_brand_clear_drops_all_prior_brand_constraints():
    import dataclasses
    r = _Redis()
    env = dataclasses.replace(_env(), session={
        "accepted_constraints": {
            "brand_filter": "Lenovo",
            "exclude_brand": "Apple",
            "preferred_brand": "Dell",
        },
    })
    core = _core(env)
    core.extras["decision"].update({
        "brand_action": "clear",
        "brand_filter": None,
        "exclude_brand": None,
        "preferred_brand": None,
    })
    assert write_session(r, env, core) is True
    constraints = _raw(r)["constraints"]
    assert constraints["brand_filter"] is None
    assert constraints["exclude_brand"] is None
    assert constraints["preferred_brand"] is None


def test_filter_followup_preserves_active_procurement_workflow():
    import dataclasses
    r = _Redis()
    env = dataclasses.replace(_env(), session={
        "prior_lane": "PROCUREMENT",
        "active_workflow_lane": "PROCUREMENT",
        "accepted_constraints": {"quantity": 25},
    })
    core = _core(env)
    core.lane = "FILTER"
    core.extras["decision"]["subject_action"] = "continue"
    assert write_session(r, env, core) is True
    raw = _raw(r)
    assert raw["last_lane"] == "FILTER"
    assert raw["active_workflow_lane"] == "PROCUREMENT"


def test_session_write_is_tenant_scoped():
    r = _Redis()
    env = _env()
    write_session(r, env, _core(env))
    scoped_key = Memory(r, tenant_id="t1").scoped_key("structured_state", "u1")
    assert scoped_key in r.store
    assert "session:t1:u1:kv_state" not in r.store
    assert F._read_session_slice(r, "u1", "t2") == {}


def test_postflight_never_raises_and_reports():
    out = run_postflight(None, _env(), _core(_env()), latency_ms=42)   # redis=None
    assert out["session_written"] is False               # no redis → no write, no raise
    r = _Redis()
    env = _env()
    out = run_postflight(r, env, _core(env), latency_ms=42)
    assert out["session_written"] is True


def test_no_uid_skips_write():
    r = _Redis()
    env = TurnEnvelope.from_suggest_params(query="x", uid="", tenant_id="t1")
    assert write_session(r, env, _core(env)) is False
