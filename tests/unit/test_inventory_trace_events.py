from src.app.services.recommend_inventory_notice import (
    emit_inventory_brand_notice,
)


def test_inventory_brand_notice_emits_events():
    # Capture emitted trace events
    emitted = []

    def fake_log_trace_event(trace_id, event_type, source_type, source_id, target_type, target_id, payload):
        emitted.append({
            "trace_id": trace_id,
            "event_type": event_type,
            "source_type": source_type,
            "source_id": source_id,
            "target_type": target_type,
            "target_id": target_id,
            "payload": payload,
        })

    # Results do not include the requested brand 'apple'
    results = [
        {"name": "Dell XPS 13", "sku": "DELL-XPS-13"},
        {"name": "Lenovo ThinkPad T14", "sku": "LENOVO-T14"},
    ]
    constraints = {"brands": ["apple"]}
    note, unmatched = emit_inventory_brand_notice(
        results=results,
        constraints=constraints,
        decision_id="TEST-ID",
        trace_id="TEST-ID",
        trace_fn=fake_log_trace_event,
    )

    assert note is not None, "Expected inventory note when suppliers are missing"
    assert "apple" in unmatched

    types = [e["event_type"] for e in emitted]
    assert "inventory_notice" in types, "Expected inventory_notice event"
    assert "supplier_missing" in types, "Expected supplier_missing event"

    inv_ev = next(e for e in emitted if e["event_type"] == "inventory_notice")
    sup_ev = next(e for e in emitted if e["event_type"] == "supplier_missing")

    assert inv_ev["payload"].get("unmatched_brands") == ["apple"]
    assert sup_ev["payload"].get("missing_suppliers_for") == ["apple"]


def test_excluded_brand_never_emits_missing_supplier_notice():
    emitted = []
    note, unmatched = emit_inventory_brand_notice(
        results=[{"name": "Dell XPS 13", "sku": "DELL-XPS-13"}],
        constraints={"brands": ["Apple"], "brand_excludes": ["Apple"]},
        decision_id="TEST-ID",
        trace_id="TEST-ID",
        trace_fn=lambda **event: emitted.append(event),
    )

    assert note is None
    assert unmatched == []
    assert emitted == []
