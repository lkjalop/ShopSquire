"""SuggestContext adoption — Pass 1 (timing_breakdown + fraud_summary).

Locks the shared-state bag's contract for the first two folded fields. The behavioural guarantee
(identical suggest() response) is covered by the golden contract test; this pins the bag shape so a
later pass can migrate readers to ctx.* and extract stages taking the ctx.
"""
from __future__ import annotations

from src.app.services.suggest_context import SuggestContext


def test_ctx_has_timing_and_fraud_fields():
    ctx = SuggestContext()
    assert ctx.timing_breakdown == {"ollama_summary_ms": None}
    assert ctx.fraud_summary == {}


def test_ctx_dicts_are_per_instance():
    a = SuggestContext()
    b = SuggestContext()
    a.timing_breakdown["x"] = 1
    a.fraud_summary["score"] = 0.5
    assert b.timing_breakdown == {"ollama_summary_ms": None}  # no shared default
    assert b.fraud_summary == {}


def test_timing_alias_semantics_in_place_mutation():
    # The recommend.py alias relies on in-place mutation flowing back to the ctx.
    ctx = SuggestContext()
    local = ctx.timing_breakdown
    local["guard_ms"] = 12
    assert ctx.timing_breakdown["guard_ms"] == 12  # same object


def test_fraud_summary_sync_semantics():
    # fraud_summary is reassigned in suggest(), then mirrored onto the ctx.
    ctx = SuggestContext()
    fraud_summary = {"score": 0.9, "level": "high"}  # a fresh local (rebind)
    ctx.fraud_summary = fraud_summary
    assert ctx.fraud_summary["level"] == "high"


def test_pass3_pass4_fields_exist():
    ctx = SuggestContext()
    assert ctx.kv_out == {} and ctx.structured_state_out == {} and ctx.nlp == {}


def test_kv_out_structured_state_nlp_live_carrier():
    # Pass 3/4: bound by reference after their last rebind, so in-place mutations flow in.
    ctx = SuggestContext()
    kv_out = {"last_turn_type": "result_turn"}
    structured_state_out = {"nqe_asked_ids": ["ask_budget"]}
    nlp = {"intent": "product_search"}
    ctx.kv_out = kv_out
    ctx.structured_state_out = structured_state_out
    ctx.nlp = nlp
    kv_out["confirmed_slots"] = {"use_case": "gaming"}
    structured_state_out["last_shortlist_skus"] = ["SKU1"]
    nlp["intent_confidence"] = 0.9
    assert ctx.kv_out["confirmed_slots"] == {"use_case": "gaming"}
    assert ctx.structured_state_out["last_shortlist_skus"] == ["SKU1"]
    assert ctx.nlp["intent_confidence"] == 0.9


def test_image_context_live_carrier_semantics():
    # Pass 2: after suggest() binds ctx.image_context = image_context (post-strip), downstream
    # in-place mutations on the local flow into the ctx (same object).
    ctx = SuggestContext()
    image_context = {"labels": ["laptop"], "ocr": "x"}  # finalized local (rebind)
    ctx.image_context = image_context  # bind by reference
    image_context["product_identity"] = {"brand": "lenovo"}  # downstream in-place mutation
    image_context.pop("ocr", None)
    assert ctx.image_context["product_identity"] == {"brand": "lenovo"}
    assert "ocr" not in ctx.image_context
