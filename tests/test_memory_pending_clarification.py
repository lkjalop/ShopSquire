from src.app.services.memory import Memory


from tests.services.test_memory_scope_contract import _Redis


def test_pending_clarification_is_tenant_scoped_and_consumable():
    memory = Memory(_Redis())
    pending = {"version": 1, "question_id": "budget_scope", "original_query": "20 laptops for 41000",
               "allowed_option_ids": ["total", "per_unit"]}
    memory.set_pending_clarification("buyer-1", pending, tenant_id="store-a")
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-a") == pending
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-b") == {}
    memory.clear_pending_clarification("buyer-1", tenant_id="store-a")
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-a") == {}


def test_clear_session_removes_tenant_pending_clarification():
    memory = Memory(_Redis())
    memory.set_pending_clarification(
        "buyer-2", {"question_id": "budget_scope"}, tenant_id="store-a",
    )

    memory.clear_session("buyer-2", tenant_id="store-a")

    assert memory.get_pending_clarification("buyer-2", tenant_id="store-a") == {}
