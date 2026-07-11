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


def test_other_forks_detected_by_shape():
    assert response_shape(to_legacy(_core(), shape="inventory_fast")) == "inventory_fast"
    assert response_shape(to_legacy(_core(), shape="claims")) == "claims"
    assert response_shape(to_legacy(_core(products=[]), shape="policy_faq")) == "policy_faq"


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
        assert p["_trace_recommendation_persisted"] is True
