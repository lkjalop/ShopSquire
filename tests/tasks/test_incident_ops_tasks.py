from src.app.tasks import incident_ops_tasks


def test_scheduled_vuln_scan_daily_uses_service_and_persists(monkeypatch):
    monkeypatch.setattr(
        incident_ops_tasks,
        "_load_scheduled_scan_configs",
        lambda: [{"tenant_id": "tenant-a", "profile": "baseline", "target_url": "https://shop.example", "image_ref": "", "code_path": ""}],
    )

    seen = {"persisted": []}

    class _FakeReport:
        target = "https://shop.example"
        critical_count = 1

        def to_api_dict(self):
            return {"risk_score": 8.8, "total_findings": 3, "critical": 1, "high": 1}

    class _FakeService:
        async def scan_all(self, **kwargs):
            seen["scan_kwargs"] = kwargs
            return _FakeReport()

    async def _fake_auto_escalate(report):
        seen["escalated"] = report.critical_count

    monkeypatch.setattr("src.app.services.vuln_scanner.VulnScanService", _FakeService)
    monkeypatch.setattr("src.app.routers.vuln_scan._auto_escalate_critical", _fake_auto_escalate)
    monkeypatch.setattr(
        incident_ops_tasks,
        "_persist_scan_scorecard",
        lambda **kwargs: seen["persisted"].append(kwargs),
    )

    out = incident_ops_tasks.scheduled_vuln_scan_daily()

    assert out["status"] == "ok"
    assert out["scan_count"] == 1
    assert seen["scan_kwargs"]["target_url"] == "https://shop.example"
    assert seen["escalated"] == 1
    assert seen["persisted"][0]["tenant_id"] == "tenant-a"

