from src.app.services.cart_session_state import clear_cart_commercial_state
from src.app.services.memory import Memory


def test_cart_clear_drops_commercial_authority_but_keeps_workload_evidence():
    uid = "cart-clear-state-user"
    tenant_id = "cart-clear-state-tenant"
    epoch = "cart-clear-state-epoch"
    memory = Memory(None, tenant_id=tenant_id, session_epoch=epoch)
    memory.set_structured_state(uid, {
        "constraints": {
            "quantity": 30,
            "total_budget_cents": 75_000_00,
            "budget_scope": "total",
            "budget_max_cents": 75_000_00,
            "exact_product_sku": "LAP-OLD",
            "product_selection_authority": "persisted_cart",
            "operational_constraints": {"delivery_window_days": 2},
            "requirements": {"ram_gb": {"op": ">=", "value": 32}},
            "workload_entities": ["ot cyber range"],
        },
        "accepted_constraints": {
            "quantity": 30,
            "exact_product_sku": "LAP-OLD",
            "requirements": {"gpu_vram_gb": {"op": ">=", "value": 8}},
        },
        "confirmed_slots": {
            "order_quantity": 30,
            "exact_product_sku": "LAP-OLD",
            "use_case": "OT cyber range digital twin",
        },
        "requested_quantity": 30,
        "active_workflow_lane": "PROCUREMENT",
        "selected_cart_sku": "LAP-OLD",
        "case_anchor": {"case_id": "case-old", "quantity": 30},
        "last_shortlist_skus": ["LAP-OLD"],
        "last_product_explanation": {"sku": "LAP-OLD"},
        "semantic_resolution": {"desired_outcome": "OT cyber range digital twin"},
        "semantic_requirement_compilation": {"status": "accepted"},
    })
    memory.set_pending_clarification(uid, {"question_id": "budget_scope"})

    cleaned = clear_cart_commercial_state(
        None,
        uid=uid,
        tenant_id=tenant_id,
        session_epoch=epoch,
    )

    assert cleaned["constraints"] == {
        "requirements": {"ram_gb": {"op": ">=", "value": 32}},
        "workload_entities": ["ot cyber range"],
    }
    assert cleaned["accepted_constraints"] == {
        "requirements": {"gpu_vram_gb": {"op": ">=", "value": 8}},
    }
    assert cleaned["confirmed_slots"] == {
        "use_case": "OT cyber range digital twin",
    }
    assert "requested_quantity" not in cleaned
    assert cleaned["semantic_resolution"]["desired_outcome"] == "OT cyber range digital twin"
    assert cleaned["semantic_requirement_compilation"]["status"] == "accepted"
    assert cleaned["last_shortlist_skus"] == []
    assert cleaned["cart_cleared"] is True
    assert "active_workflow_lane" not in cleaned
    assert "selected_cart_sku" not in cleaned
    assert "case_anchor" not in cleaned
    assert "last_product_explanation" not in cleaned
    assert memory.get_pending_clarification(uid) == {}
