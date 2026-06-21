"""product_identity_agent.apply_identity_to_constraints — image identity -> retrieval constraints.

Extracted from suggest() (Phase 3, image/CV stage). Maps an identified product into the live
constraints in place WITHOUT clobbering shopper-provided values, seeds the brand hint, and carries
the specific model for multimodal anchoring.
"""
from __future__ import annotations

from src.app.services.product_identity_agent import apply_identity_to_constraints

_ID = {
    "identified": True, "confidence": 0.9, "brand": "Lenovo", "model": "ThinkPad X1 Carbon",
    "price_tier": "premium", "cpu_tier": "high", "ram_gb_hint": 32, "gpu_hint": "rtx 4060",
    "display_inches_hint": 14.0, "form_factor": "laptop", "product_type": "laptop",
}


def test_unidentified_is_noop():
    c = {}
    ic, hint = apply_identity_to_constraints({"identified": False}, c)
    assert ic == {} and hint is None and c == {}


def test_maps_brand_model_and_specs():
    c = {}
    ic, hint = apply_identity_to_constraints(_ID, c, supported_brand_hints={"lenovo"})
    assert c["brand"] == "Lenovo"
    assert c["identity_model"] == "ThinkPad X1 Carbon"  # anchor
    assert c["_request_brand_hint"] == "lenovo" and c["brands"] == ["lenovo"]
    assert hint == "lenovo"
    assert c["product_type"] == "laptop" and c.get("must_have_gpu") is True
    assert ic["identity_brand"] == "Lenovo"


def test_does_not_clobber_shopper_values():
    c = {"brand": "Dell", "budget_max": 1000, "brands": ["dell"]}
    apply_identity_to_constraints(_ID, c, supported_brand_hints={"lenovo"})
    assert c["brand"] == "Dell"          # shopper's brand kept
    assert c["budget_max"] == 1000       # shopper's budget kept
    assert c["brands"] == ["dell"]       # not overwritten


def test_brand_hint_only_for_supported_brands():
    c = {}
    apply_identity_to_constraints(_ID, c, supported_brand_hints=set())  # lenovo not supported
    assert "_request_brand_hint" not in c and "brands" not in c


def test_logs_enrichment_when_log_fn_given():
    logs = []
    apply_identity_to_constraints(_ID, {}, supported_brand_hints={"lenovo"},
                                  id_source="vision_image", trace_id="t",
                                  log_fn=lambda **kw: logs.append(kw))
    assert logs and logs[0]["event_type"] == "product_identity_text_enrichment"
    assert logs[0]["payload"]["brand"] == "Lenovo" and logs[0]["payload"]["source"] == "vision_image"


def test_never_raises_on_bad_input():
    # log_fn raising must not propagate.
    def _boom(**k):
        raise RuntimeError("trace down")
    ic, hint = apply_identity_to_constraints(_ID, {}, supported_brand_hints={"lenovo"}, log_fn=_boom)
    assert ic["identity_brand"] == "Lenovo"  # mapping still happened
