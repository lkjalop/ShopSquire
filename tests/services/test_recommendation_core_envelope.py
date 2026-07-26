"""Phase 4 step 1: the envelope invariants and the legacy adapter's fork emulation, measured
against the FROZEN contract — the boundary must hold before any brain code exists."""
from src.app.contracts.suggest_contract import response_shape, validate_response
from src.app.services.recommend_parity_full import diff_responses, message_class
from src.app.services.recommendation_core.envelope import (
    CoreResponse,
    ProductCard,
    TurnEnvelope,
)
from src.app.services.recommendation_core.legacy_adapter import to_legacy


def _env(**over):
    return TurnEnvelope.from_suggest_params(query="gaming laptop under $2000", uid="u1",
                                            budget_max=2000, **over)


def _core(**over) -> CoreResponse:
    c = CoreResponse(envelope=_env(), message="Here are 2 options.",
                     products=[ProductCard(sku="LAP-1", title="Dell G16", price_cents=169900),
                               ProductCard(sku="LAP-2", title="Asus TUF", price_cents=189900)])
    for k, v in over.items():
        setattr(c, k, v)
    return c


# ── envelope ──────────────────────────────────────────────────────────────────

def test_envelope_converts_dollars_to_cents_once():
    e = _env()
    assert e.budget_max_cents == 200000 and e.budget_min_cents is None
    assert e.trace_id and e.tenant_id == "default"


def test_free_text_budget_is_normalized_before_legacy_dispatch_order():
    e = TurnEnvelope.from_suggest_params(
        query="work laptops budget 1200 to 1500, need 10", uid="u1"
    )
    assert e.budget_min_cents == 120000
    assert e.budget_max_cents == 150000


def test_structured_budget_remains_authoritative_over_text():
    e = TurnEnvelope.from_suggest_params(
        query="laptop under 1500", uid="u1", budget_max=1800
    )
    assert e.budget_max_cents == 180000


def test_finalize_enforces_never_empty_message():
    c = _core(message="", products=[])
    out = c.finalize()
    assert out.message.strip()                       # the valorant silent-zero, dead by type
    c2 = _core(message="", products=[], degraded=True, grounding="error")
    assert "won't guess" in c2.finalize().message    # degraded honesty, not fake results


def test_finalize_enforces_off_catalog_honesty():
    c = _core(off_catalog={"class": "material_handling", "label": "forklifts"})
    out = c.finalize()
    assert out.products == [] and "don't stock" in out.message


def test_finalize_grounding_error_forces_degraded():
    assert _core(grounding="error").finalize().degraded is True


# ── legacy adapter: fork emulation vs the frozen contract ─────────────────────

def test_full_pipeline_shape_passes_contract_with_zero_violations():
    payload = to_legacy(_core())
    assert response_shape(payload) == "full_pipeline"
    assert validate_response(payload) == []          # stricter than v1's own clarify branches


def test_full_pipeline_off_catalog_matches_corpus_class():
    payload = to_legacy(_core(off_catalog={"class": "datacenter_gpu_server",
                                           "label": "rack-mount GPU servers",
                                           "supplier_rfq_offer": True}, message=""))
    assert message_class(payload) == "off_catalog"
    assert validate_response(payload) == []          # honesty rule holds THROUGH the adapter


def test_clarify_and_answer_classes_map():
    assert message_class(to_legacy(_core())) == "answer"
    c = _core(clarify=[{"q": "What budget?"}])
    assert message_class(to_legacy(c)) == "answer_with_clarify"


def test_slate_disposition_clears_authoritative_empty_but_retains_for_clarify():
    assert to_legacy(_core())["slate_disposition"] == "replace"
    assert to_legacy(_core(products=[]))["slate_disposition"] == "clear"
    clarifying = _core(products=[], clarify=[{"text": "Which product type?"}])
    assert to_legacy(clarifying)["slate_disposition"] == "retain"
    clarifying.extras["decision"] = {"subject_action": "reset"}
    assert to_legacy(clarifying)["slate_disposition"] == "clear"


def test_other_forks_detected_by_shape():
    assert response_shape(to_legacy(_core(), shape="inventory_fast")) == "inventory_fast"
    assert response_shape(to_legacy(_core(), shape="claims")) == "claims"
    assert response_shape(to_legacy(_core(products=[]), shape="policy_faq")) == "policy_faq"


def test_envelope_wire_roundtrip_cents_exact():
    """R10.1: a shadow job carries the FULL envelope; the worker must rebuild the SAME turn —
    cents stay cents (never re-converted through dollars), session/cart/image intact."""
    from src.app.services.recommendation_core.envelope import TurnEnvelope
    env = TurnEnvelope.from_suggest_params(
        query="gaming laptop", uid="u1", tenant_id="t1", budget_max=2499.99, has_image=True,
        intent_hint="explain",
        session={"prior_node": "el-6-11-2", "shortlist_skus": ["A"]},
        cart=[{"sku": "A", "quantity": 2}])
    back = TurnEnvelope.from_dict(env.to_dict())
    assert back == env                                    # frozen dataclass equality = full fidelity
    assert back.budget_max_cents == 249999                # cents-exact, no dollar re-round
    assert back.intent_hint == "EXPLAIN"


def test_envelope_rejects_unknown_intent_hint():
    env = TurnEnvelope.from_suggest_params(query="laptop", intent_hint="invented_lane")
    assert env.intent_hint is None
    wire = env.to_dict()
    wire["intent_hint"] = "INVENTED_LANE"
    assert TurnEnvelope.from_dict(wire).intent_hint is None


def test_envelope_currency_is_bounded_and_round_trips():
    env = TurnEnvelope.from_suggest_params(query="laptop", currency="aud")
    assert env.currency == "AUD"
    assert TurnEnvelope.from_dict(env.to_dict()).currency == "AUD"
    assert TurnEnvelope.from_suggest_params(query="laptop", currency="bitcoin").currency == "USD"


def test_envelope_uses_authoritative_store_currency_when_unspecified():
    env = TurnEnvelope.from_suggest_params(query="laptop")
    assert env.currency == "AUD"


def test_shown_products_beat_stray_claims_artifacts():
    """R10 census fix: the legacy kitchen-sink can mint incident_id + needs_human_review=True
    on a PRODUCT turn (recorded live in compare_two_models, 15 products). A payload that SHOWS
    products is a product response — else the replay projects V2 through the product-less
    claims adapter and manufactures a phantom empty."""
    kitchen_sink = {"products": [{"sku": "X"}], "incident_id": "abc",
                    "needs_human_review": True, "assistant_message": "m"}
    assert response_shape(kitchen_sink) == "full_pipeline"
    # a REAL claims payload (no shown products) still classifies claims
    assert response_shape({"incident_id": "abc", "needs_human_review": True}) == "claims"
    # present-but-EMPTY products with claims signal = claims (nothing shown)
    assert response_shape({"products": [], "needs_human_review": True}) == "claims"


def test_adapter_output_diffs_cleanly_against_itself():
    # the differ must treat two identical-outcome adapter payloads as identical —
    # otherwise shadow would measure the adapter, not the core
    a, b = to_legacy(_core()), to_legacy(_core())
    d = diff_responses(a, b)
    assert d["identical_outcome"] and d["severity"] == "INFO"


def test_universal_trace_fields_on_every_fork():
    for shape in ("full_pipeline", "inventory_fast", "claims", "policy_faq"):
        p = to_legacy(_core(), shape=shape)
        assert p["trace_id"] and p["decision_id"] and p["decision_trace_id"]
        assert p["_trace_recommendation_persisted"] is False  # honest: core does not persist yet
