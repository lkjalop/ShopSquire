from __future__ import annotations


def test_poll_crowdstrike_task_calls_connector(monkeypatch):
    from src.app.tasks import security_poll_tasks as t

    called = {"args": None}

    def _fake_pull(**kwargs):  # noqa: ANN003
        called["args"] = kwargs
        return {"ok": True, "ingested": 3, "results": []}

    monkeypatch.setattr(t, "pull_crowdstrike_and_ingest", _fake_pull)
    out = t.poll_crowdstrike.run(tenant_id="tenant-x", limit=77, lookback_minutes=22)
    assert out.get("ok") is True
    assert out.get("ingested") == 3
    assert called["args"]["tenant_id"] == "tenant-x"
    assert called["args"]["limit"] == 77
    assert called["args"]["lookback_minutes"] == 22
