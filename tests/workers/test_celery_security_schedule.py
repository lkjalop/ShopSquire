from __future__ import annotations


def test_celery_security_poll_schedule_enabled(monkeypatch):
    from src.app.workers.celery_app import make_celery

    monkeypatch.setenv("SECURITY_CROWDSTRIKE_POLL_ENABLED", "1")
    monkeypatch.setenv("SECURITY_CROWDSTRIKE_POLL_MINUTES", "7")
    monkeypatch.setenv("SECURITY_CROWDSTRIKE_POLL_TENANT_ID", "tenant-beat")
    monkeypatch.setenv("SECURITY_CROWDSTRIKE_POLL_LIMIT", "55")

    app = make_celery("test-celery-security")
    sched = app.conf.get("beat_schedule") or {}
    item = sched.get("security-crowdstrike-poll") or {}
    assert item.get("task") == "src.app.tasks.security_poll_tasks.poll_crowdstrike"
    assert tuple(item.get("args") or ()) == ("tenant-beat", 55, 7)
