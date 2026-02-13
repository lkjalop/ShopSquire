def test_insider_triggers_ticket_and_logs(monkeypatch):
    from src.app.services.orchestrator import Orchestrator
    from src.app.security.firewall import TransactionFirewall

    calls = {"ticket_created": False, "logged": []}

    class DummyMem:
        def get_context(self, uid):
            return {}
        def set_recent_retrieval(self, uid, facts, ttl_seconds: int = 600):
            pass

    def fake_create_ticket(self, title, description, severity, tenant_id=None):
        calls["ticket_created"] = True
        class T:
            id = "TKT-INSIDER-1"
        return T()

    def fake_log_decision(*args, **kwargs):
        calls["logged"].append((args, kwargs))
        return "dec-1"

    monkeypatch.setattr("src.app.services.ticketing.TicketingAgent.create_ticket", fake_create_ticket, raising=False)
    # patch both the decision_log module and orchestrator's imported reference
    monkeypatch.setattr("src.app.services.decision_log.log_decision", fake_log_decision, raising=False)
    monkeypatch.setattr("src.app.services.orchestrator.log_decision", fake_log_decision, raising=False)

    orch = Orchestrator(DummyMem(), TransactionFirewall({}), {})
    # suspicious payload with actor_context triggers high severity via observer heuristics
    payload = {"intent_confidence": 0.9, "actor_id": "emp-1", "actor_role": "admin", "amount": 0, "cart_total_cents": 100}
    # Inject actor_context into security analysis via analyze_payload call path is indirect; pass unusual flags directly
    payload["unusual_hours"] = True
    # Run orchestrator; expect ticket created and logs written
    res = orch.run("uid-1", payload)
    assert calls["ticket_created"] is True
    assert len(calls["logged"]) >= 1
