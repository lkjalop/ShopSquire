from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.memory import Memory
from src.app.services.recommendations import RecommendationService
from tests.utils import default_headers


def test_followup_query_keeps_budget_context(monkeypatch):
    app = create_app()
    client = TestClient(app, headers=default_headers())
    kv_state: dict[str, dict] = {}
    structured: dict[str, dict] = {}

    def _get_context(self, uid: str):
        kv = kv_state.get(uid) or {}
        return {"summary": None, "kv": kv, "recent_retrieval": None}

    def _set_kv(self, uid: str, kv: dict, ttl_seconds=None):
        kv_state[uid] = dict(kv or {})

    def _get_kv(self, uid: str):
        return dict(kv_state.get(uid) or {})

    def _set_structured(self, uid: str, s: dict, ttl_seconds=None):
        structured[uid] = dict(s or {})

    def _get_structured(self, uid: str):
        return dict(structured.get(uid) or {})

    monkeypatch.setattr(Memory, "get_context", _get_context)
    monkeypatch.setattr(Memory, "set_kv", _set_kv)
    monkeypatch.setattr(Memory, "get_kv", _get_kv)
    monkeypatch.setattr(Memory, "set_structured_state", _set_structured)
    monkeypatch.setattr(Memory, "get_structured_state", _get_structured)

    def _fake_candidates(self, query: str, limit: int = 10):
        return [
            {"id": "1", "sku": "SKU-1", "name": "Gaming Laptop A", "price_cents": 150000, "currency": "USD", "stock": 10},
            {"id": "2", "sku": "SKU-2", "name": "Gaming Laptop B", "price_cents": 180000, "currency": "USD", "stock": 8},
            {"id": "3", "sku": "SKU-3", "name": "Gaming Laptop C", "price_cents": 190000, "currency": "USD", "stock": 6},
            {"id": "4", "sku": "SKU-4", "name": "Gaming Laptop D", "price_cents": 260000, "currency": "USD", "stock": 5},
        ]

    monkeypatch.setattr(RecommendationService, "retrieve_candidates", _fake_candidates)

    uid = "followup-memory-user"

    first = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "show me computers that are portable and good for gaming between 1500 to 1900"},
    )
    assert first.status_code == 200
    first_body = first.json()
    first_constraints = first_body.get("constraints_used") or {}
    assert int(first_constraints.get("budget_max")) == 1900
    assert int(first_constraints.get("budget_min")) == 1500

    second = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "why did you pick those gaming laptops? explain your reasoning"},
    )
    assert second.status_code == 200
    second_body = second.json()
    second_constraints = second_body.get("constraints_used") or {}

    # Regression guard: follow-up explain prompts should retain prior budget context.
    assert second_constraints.get("budget_max") is not None, (
        f"budget_max missing from followup constraints: {second_constraints}"
    )
    assert int(second_constraints.get("budget_max")) == 1900
    assert int(second_constraints.get("budget_min")) == 1500


def test_followup_widen_budget_by_delta_uses_prior_envelope(monkeypatch):
    app = create_app()
    client = TestClient(app, headers=default_headers())
    state: dict[str, dict] = {}

    def _get_context(self, uid: str):
        kv = state.get(uid) or {}
        return {"summary": None, "kv": kv, "recent_retrieval": None}

    def _set_kv(self, uid: str, kv: dict, ttl_seconds=None):
        state[uid] = kv or {}

    monkeypatch.setattr(Memory, "get_context", _get_context)
    monkeypatch.setattr(Memory, "set_kv", _set_kv)

    def _fake_candidates(self, query: str, limit: int = 10):
        return [
            {"id": "1", "sku": "SKU-1", "name": "Gaming Laptop A", "price_cents": 150000, "currency": "USD", "stock": 10},
            {"id": "2", "sku": "SKU-2", "name": "Gaming Laptop B", "price_cents": 180000, "currency": "USD", "stock": 8},
            {"id": "3", "sku": "SKU-3", "name": "Gaming Laptop C", "price_cents": 250000, "currency": "USD", "stock": 6},
        ]

    monkeypatch.setattr(RecommendationService, "retrieve_candidates", _fake_candidates)
    uid = "followup-memory-user-delta"

    first = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "show me gaming laptops between 1500 to 1900"},
    )
    assert first.status_code == 200
    first_constraints = (first.json() or {}).get("constraints_used") or {}
    assert int(first_constraints.get("budget_max")) == 1900
    assert int(first_constraints.get("budget_min")) == 1500

    second = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "can we widen the budget range by 600?"},
    )
    assert second.status_code == 200
    second_constraints = (second.json() or {}).get("constraints_used") or {}
    assert int(second_constraints.get("budget_max")) == 2500
    assert int(second_constraints.get("budget_min")) == 2100
