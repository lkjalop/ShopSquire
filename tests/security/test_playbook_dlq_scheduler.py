from src.app.services import playbook_dlq_scheduler as sched


def test_run_dlq_reprocessor_cycle_writes_audit(monkeypatch):
    monkeypatch.setattr(sched, "_batch_cap", lambda: 10)
    monkeypatch.setattr(sched, "_max_runtime_sec", lambda: 20.0)
    monkeypatch.setattr(sched, "_interval_sec", lambda: 60.0)
    monkeypatch.setattr(sched, "reprocess_playbook_dlq", lambda limit=0: {"picked": 2, "reprocessed": 2, "failed": 0})

    captured = {}

    def fake_audit(decision_id, action, actor, metadata=None):
        captured["decision_id"] = decision_id
        captured["action"] = action
        captured["actor"] = actor
        captured["metadata"] = metadata or {}
        return True

    monkeypatch.setattr(sched, "write_audit_and_event", fake_audit)
    out = sched.run_dlq_reprocessor_cycle()
    assert out.get("picked") == 2
    assert out.get("reprocessed") == 2
    assert captured.get("decision_id") == "system:playbook_dlq"
    assert captured.get("action") == "playbook_dlq_reprocess_cycle"
