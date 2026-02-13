import json


class DummyMemory:
    def __init__(self):
        self._ctx = {}

    def get_context(self, uid: str):
        return {"summary": None, "kv": None, "recent_retrieval": None}

    def set_recent_retrieval(self, uid: str, facts, ttl_seconds: int = 600):
        pass


class DummyLLM:
    def __init__(self):
        self.calls = []

    def rerank_with_budget(self, uid, candidates, constraints):
        self.calls.append((uid, candidates, constraints))
        # return ranked list of candidate dicts
        return sorted(candidates, key=lambda c: c.get("price_cents", 0))


def test_choose_model_tier_basic():
    from src.app.services.orchestrator import Orchestrator
    from src.app.security.firewall import TransactionFirewall

    mem = DummyMemory()
    fw = TransactionFirewall({})
    flags = {"MODEL_T1": "m_t1", "MODEL_T2": "m_t2", "MODEL_T3": "m_t3"}
    orch = Orchestrator(mem, fw, flags)

    # low risk, high intent -> T1
    payload = {"intent_confidence": 0.9}
    sec = {"risk_adj": 0.0}
    choice = orch.choose_model_tier(payload, {}, sec)
    assert choice["text_tier"] == "T1"

    # low confidence -> T2
    payload = {"intent_confidence": 0.6}
    choice = orch.choose_model_tier(payload, {}, sec)
    assert choice["text_tier"] == "T2"

    # high amount -> T3
    payload = {"intent_confidence": 0.95, "amount": 500}
    sec = {"risk_adj": 0.0}
    choice = orch.choose_model_tier(payload, {}, sec)
    assert choice["text_tier"] == "T3"


def test_call_text_model_rerank_stub(tmp_path):
    from src.app.services.orchestrator import Orchestrator
    from src.app.security.firewall import TransactionFirewall

    mem = DummyMemory()
    fw = TransactionFirewall({})
    flags = {}
    orch = Orchestrator(mem, fw, flags)

    dummy = DummyLLM()
    orch.llm = dummy

    candidates = [
        {"sku": "a", "price_cents": 300},
        {"sku": "b", "price_cents": 100},
        {"sku": "c", "price_cents": 200},
    ]
    prompt_obj = {"candidates": candidates, "constraints": {}}
    res = orch.call_text_model("uid-1", {}, json.dumps(prompt_obj))
    assert isinstance(res, dict)
    assert res["usage"]["method"] in ("rerank", "ollama_cli", "fallback")
    # If rerank ran, ensure result ordering is by price (our DummyLLM returns sorted by price)
    if res["usage"]["method"] == "rerank":
        ranked = res["result"]
        prices = [c["price_cents"] for c in ranked]
        assert prices == sorted(prices)
