import pytest

from src.app.services.orchestrator import Orchestrator


class DummyMemory:
    def __init__(self):
        self._ctx = {"kv": {}, "summary": None}

    def get_context(self, uid: str):
        return self._ctx

    def set_recent_retrieval(self, uid: str, facts: dict):
        pass


def test_orchestrator_auto_decision_applies():
    flags = {"AUTO_CV_DECISIONS_ENABLED": True, "DECISION_LOG_WRITES_ENABLED": False}
    mem = DummyMemory()
    from src.app.security.firewall import TransactionFirewall

    fw = TransactionFirewall(flags={})
    orch = Orchestrator(mem, fw, flags)
    # Craft minimal payload with cv_tier2 decision_action
    payload = {"query": "return my laptop", "cv_tier2": {"decision_action": "approve", "verdict": {"verdict": "approve", "score": 0.12}}, "cart_total_cents": 1000}
    res = orch.run(uid="user123", payload=payload, simulate_only=True)
    assert isinstance(res, object)
    # The proposal should contain auto_decision when allowed
    assert res.proposal.get("auto_decision") is not None
    assert res.proposal["auto_decision"]["action"] == "approve"
