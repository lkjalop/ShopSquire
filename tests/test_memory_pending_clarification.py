from src.app.services.memory import Memory


class _Redis:
    def __init__(self):
        self.data = {}

    def setex(self, key, _ttl, value):
        self.data[key] = value

    def get(self, key):
        return self.data.get(key)

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)


def test_pending_clarification_is_tenant_scoped_and_consumable():
    memory = Memory(_Redis())
    pending = {"version": 1, "question_id": "budget_scope", "original_query": "20 laptops for 41000",
               "allowed_option_ids": ["total", "per_unit"]}
    memory.set_pending_clarification("buyer-1", pending, tenant_id="store-a")
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-a") == pending
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-b") == {}
    memory.clear_pending_clarification("buyer-1", tenant_id="store-a")
    assert memory.get_pending_clarification("buyer-1", tenant_id="store-a") == {}
