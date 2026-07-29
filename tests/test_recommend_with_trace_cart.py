"""The V2 response transaction must preserve the cart-mutation contract.

The facade routes every served payload through recommend.py's _with_trace (sanitize → localize →
formatter → trace stamping). None of those stages may strip cart_mutation/cart/cart_updated or
rewrite a cart confirmation into 'no match' prose — if one ever does, the whole cart lane breaks
SILENTLY (chat.py's short-circuit keys on cart_mutation being present). Regression-locked here.
"""
import pytest

from src.app.services.recommend_response_transaction import (
    ResponseTransactionDependencies,
    finalize_response_transaction,
)


@pytest.fixture(autouse=True)
def _stub_trace_writes():
    writes = {"events": [], "decisions": []}

    def _log_decision(*args, **kwargs):
        writes["decisions"].append((args, kwargs))
        return kwargs.get("decision_id") or "generated"

    dependencies = ResponseTransactionDependencies(
        security_sanitize=lambda payload: payload,
        sanitize_specs=lambda _payload: None,
        inject_knowledge=lambda _payload, _trace_id: None,
        attach_evidence=lambda _payload, _trace_id: None,
        localize=lambda payload, _locale: payload,
        exclude_off_category=lambda payload: payload,
        annotate_integrity=lambda payload: payload,
        formatter_enabled=lambda: False,
        finalize_answer=lambda payload: payload,
        dereference_labels=lambda payload: payload,
        apply_security_challenge=lambda payload: payload,
        log_trace_event=lambda *args, **kwargs: writes["events"].append(
            (args, kwargs),
        ),
        log_decision=_log_decision,
    )
    return writes, dependencies


def _cart_payload():
    return {
        "assistant_message": "Done — removed 2 items, set a line to 20.",
        "message": "Done — removed 2 items, set a line to 20.",
        "products": [], "results": [],
        "turn_intent": "CART_MUTATE", "turn_type": "cart_mutate_turn",
        "cart_mutation": {"applied": [{"action": "remove_items", "sku": "LAP-1"}],
                          "rejected": [], "ambiguous": [], "needs_clarification": False},
        "cart": {"items": [{"sku": "LAP-2", "quantity": 20}], "subtotal_cents": 100000},
        "cart_updated": True,
        "degraded": False, "off_catalog": None,
    }


def test_with_trace_preserves_cart_contract_fields(_stub_trace_writes):
    _, dependencies = _stub_trace_writes
    expected = _cart_payload()
    out = finalize_response_transaction(
        dict(expected),
        "tid-cart-verify",
        dependencies=dependencies,
    )
    assert out.get("cart_mutation") is not None, "sanitize/formatter stripped cart_mutation"
    assert out.get("cart", {}).get("items"), "cart block stripped"
    assert out.get("cart_updated") is True
    assert out["trace_id"] == "tid-cart-verify"
    assert out["decision_trace_id"] == "tid-cart-verify"
    assert {
        key: out[key] for key in expected
    } == expected


def test_with_trace_does_not_rewrite_cart_message_as_no_match(
    _stub_trace_writes,
):
    # products=[] on a cart turn must NOT trigger the never-empty 'no match' compose —
    # the cart confirmation is the answer.
    _, dependencies = _stub_trace_writes
    out = finalize_response_transaction(
        _cart_payload(),
        "tid-cart-verify2",
        dependencies=dependencies,
    )
    msg = str(out.get("assistant_message") or "")
    assert "Done" in msg
    assert "no match" not in msg.lower() and "couldn't find" not in msg.lower()


def test_with_trace_persists_canonical_decision_row(_stub_trace_writes):
    writes, dependencies = _stub_trace_writes
    out = finalize_response_transaction(
        _cart_payload(),
        "tid-cart-durable",
        dependencies=dependencies,
    )

    assert out["_trace_recommendation_persisted"] is True
    assert len(writes["events"]) == 1
    assert len(writes["decisions"]) == 1
    decision = writes["decisions"][0][1]
    assert decision["decision_id"] == "tid-cart-durable"
    assert decision["event_type"] == "recommendation_result"


def test_with_trace_persists_typed_execution_ontology(_stub_trace_writes):
    writes, dependencies = _stub_trace_writes
    payload = _cart_payload()
    payload["execution_steps"] = [{
        "id": "model_proposal", "kind": "model", "authority": "proposes",
        "label": "Model proposed a bounded turn decision", "status": "accepted",
    }]

    finalize_response_transaction(
        payload,
        "tid-execution-proof",
        dependencies=dependencies,
    )

    event_payload = writes["events"][0][1]["payload"]
    decision = writes["decisions"][0][1]
    assert event_payload["execution_steps"][0]["authority"] == "proposes"
    assert decision["retrieved_context"]["execution_steps"][0]["kind"] == "model"


def test_response_transaction_without_trace_has_no_persistence(
    _stub_trace_writes,
):
    writes, dependencies = _stub_trace_writes
    out = finalize_response_transaction(
        _cart_payload(),
        None,
        dependencies=dependencies,
    )

    assert "trace_id" not in out
    assert writes == {"events": [], "decisions": []}


def test_response_transaction_reports_persistence_failure(
    _stub_trace_writes,
):
    _, dependencies = _stub_trace_writes
    failing = ResponseTransactionDependencies(
        **{
            **dependencies.__dict__,
            "log_decision": lambda **_kwargs: (_ for _ in ()).throw(
                RuntimeError("decision_store_down"),
            ),
        },
    )

    out = finalize_response_transaction(
        _cart_payload(),
        "tid-persistence-failure",
        dependencies=failing,
    )

    assert out["_trace_recommendation_persisted"] is False
