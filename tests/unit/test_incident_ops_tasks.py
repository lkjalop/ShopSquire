from src.app.tasks import incident_ops_tasks as tasks


def test_check_incident_sla_breaches_task(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.incident_sla_scheduler.run_cycle",
        lambda: {"checked": 7, "breached": 2},
    )
    out = tasks.check_incident_sla_breaches()
    assert out.get("checked") == 7
    assert out.get("breached") == 2


def test_trace_broker_recovery_task_success(monkeypatch):
    async def _recover(max_messages=200):
        return 3

    async def _replay(count=200):
        return 9

    monkeypatch.setattr("src.app.services.trace_broker.recover_pending", _recover)
    monkeypatch.setattr("src.app.services.trace_broker.replay_recent", _replay)
    out = tasks.trace_broker_recovery()
    assert int(out.get("recovered") or 0) == 3
    assert int(out.get("replayed") or 0) == 9


def test_trace_broker_recovery_task_error(monkeypatch):
    async def _recover_fail(max_messages=200):
        raise RuntimeError("recover_failed")

    monkeypatch.setattr("src.app.services.trace_broker.recover_pending", _recover_fail)
    out = tasks.trace_broker_recovery()
    assert "error" in out
