from src.app.tasks import incident_ops_tasks as tasks


def test_check_incident_sla_breaches_task(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.incident_sla_scheduler.run_cycle",
        lambda: {"checked": 7, "breached": 2},
    )
    out = tasks.check_incident_sla_breaches()
    assert out.get("checked") == 7
    assert out.get("breached") == 2
