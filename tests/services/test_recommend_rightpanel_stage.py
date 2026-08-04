"""Right-panel assembly stage (extracted from suggest()). Verifies both branches (support / shopping),
the UI trace event, and the never-raises contract — with all route deps injected (no app wiring)."""
from __future__ import annotations

from src.app.services.recommend_rightpanel_stage import assemble_right_panel


def _passthru_security(payload, **kw):
    return payload  # the real helper enriches payload; identity is enough for the stage test


def _warranty_found(uid):
    return {"status": "found", "message": "Coverage active", "order_ref": "ORD-1"}


def _call(payload, *, results=None, assistant_message="orig", turn_intent="SHOPPING",
          image_reupload_reasons=None, trace_calls=None):
    def _trace(**kw):
        if trace_calls is not None:
            trace_calls.append(kw)
    return assemble_right_panel(
        payload, results=results or [], assistant_message=assistant_message,
        analysis={"details": {}}, severity=None, image_reupload_reasons=image_reupload_reasons,
        image_cv_signals_parsed=None, turn_intent=turn_intent, constraints={}, uid="u1",
        decision_id="dec-1", trace_id=None, nlp={"intent": "shopping"},
        apply_image_security_fields=_passthru_security, infer_warranty=_warranty_found, trace_fn=_trace)


def test_shopping_branch_builds_tier_panel():
    payload = {"recommendation_tiers": {"show_split": True, "minimum": [{"sku": "A"}],
                                        "recommended": [{"sku": "B"}]},
               "budget_viability": {"status": "ok"}}
    p, results, msg = _call(payload, results=[{"sku": "A"}], turn_intent="SHOPPING")
    rp = p["right_panel"]
    assert rp["mode"] == "shopping" and rp["show_tiers"] is True and rp["budget_status"] == "ok"
    assert rp["higher_tier"]["items"] == [{"sku": "B"}]
    assert msg == "orig" and results == [{"sku": "A"}]  # shopping branch leaves these untouched


def test_support_branch_clears_results_and_sets_message():
    trace_calls = []
    p, results, msg = _call({}, results=[{"sku": "X"}], turn_intent="SUPPORT_CLAIM", trace_calls=trace_calls)
    rp = p["right_panel"]
    assert rp["mode"] == "support" and rp["show_tiers"] is False
    assert results == [] and p["results"] == []          # support clears the product list
    assert "repair, warranty, or return" in msg
    assert any(c.get("event_type") == "recommendation_result" for c in trace_calls)
    assert rp["support_cards"][0]["status"] == "found"   # warranty status threaded through


def test_device_lanes_fn_is_attached_to_shopping_panel():
    # the injected lane scorer's output lands on right_panel.device_lanes (shopping branch only)
    def _lanes(prods, use_case=None):
        return [{"key": "biz", "title": "Business", "primary": use_case == "office", "skus": [p["sku"] for p in prods]}]
    p, _, _ = assemble_right_panel(
        {"recommendation_tiers": {}}, results=[{"sku": "A"}], assistant_message="m", analysis={"details": {}},
        severity=None, image_reupload_reasons=None, image_cv_signals_parsed=None, turn_intent="SHOPPING",
        constraints={"use_case": "office"}, uid="u", decision_id=None, trace_id=None, nlp={},
        apply_image_security_fields=_passthru_security, infer_warranty=_warranty_found,
        trace_fn=lambda **k: None, device_lanes_fn=_lanes)
    lanes = p["right_panel"].get("device_lanes")
    assert lanes and lanes[0]["key"] == "biz" and lanes[0]["primary"] is True and lanes[0]["skus"] == ["A"]


def test_no_device_lanes_fn_leaves_panel_unchanged():
    p, _, _ = _call({"recommendation_tiers": {}}, results=[{"sku": "A"}])  # no device_lanes_fn injected
    assert "device_lanes" not in p["right_panel"]


def test_fleet_advisory_fn_attached_when_lanes_present():
    p, _, _ = assemble_right_panel(
        {"recommendation_tiers": {}}, results=[{"sku": "A"}], assistant_message="m", analysis={"details": {}},
        severity=None, image_reupload_reasons=None, image_cv_signals_parsed=None, turn_intent="SHOPPING",
        constraints={"use_case": "office"}, uid="u", decision_id=None, trace_id=None, nlp={},
        apply_image_security_fields=_passthru_security, infer_warranty=_warranty_found, trace_fn=lambda **k: None,
        device_lanes_fn=lambda prods, use_case=None: [{"key": "gaming_chassis", "non_primary": True, "count": 1, "skus": ["A"]}],
        fleet_advisory_fn=lambda lanes, use_case=None: {"coverage": "none", "suggest_procurement": True})
    assert p["right_panel"]["fleet_advisory"]["coverage"] == "none"


def test_image_untrusted_marks_security_route():
    p, _, _ = _call({"recommendation_tiers": {}}, image_reupload_reasons=["adversarial"])
    assert p["right_panel"]["image_untrusted"] is True
    assert p["right_panel"]["security_route"] == "visual_sanitized"


def test_never_raises_on_failing_dependency():
    def _boom(payload, **kw):
        raise RuntimeError("security helper down")
    p, results, msg = assemble_right_panel(
        {"k": 1}, results=[1], assistant_message="keep", analysis={}, severity=None,
        image_reupload_reasons=None, image_cv_signals_parsed=None, turn_intent="SHOPPING",
        constraints={}, uid="u", decision_id=None, trace_id=None, nlp={},
        apply_image_security_fields=_boom, infer_warranty=_warranty_found, trace_fn=lambda **k: None)
    # swallowed → current values returned unchanged (matches the inline try/except: pass)
    assert results == [1] and msg == "keep" and p == {"k": 1}
