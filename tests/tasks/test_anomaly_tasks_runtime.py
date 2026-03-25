from src.app.tasks import anomaly_tasks


def test_anomaly_hourly_snapshot_uses_metrics_api_and_persists_history(monkeypatch):
    monkeypatch.setattr(
        anomaly_tasks,
        "_collect_metrics_snapshot",
        lambda: {
            "orders_last_hour": 9,
            "refunds_last_hour": 3,
            "snapshot_ts": "2026-03-25T00:00:00Z",
        },
    )

    seen = {}

    monkeypatch.setattr(
        anomaly_tasks,
        "_load_metric_histories",
        lambda limit_per_metric=200: {"orders_last_hour": [1.0] * 12, "refunds_last_hour": [0.0] * 12},
    )
    monkeypatch.setattr(
        anomaly_tasks,
        "_persist_metric_snapshot",
        lambda metrics: seen.setdefault("persisted", metrics),
    )

    class _FakeResult:
        domain = "orders_last_hour"
        value = 9.0
        confidence = 0.82
        severity = "high"
        method_votes = {"zscore": True, "band": True}
        plain_english = "Orders are unusually high."

    class _FakeDetector:
        MAX_HISTORY = 1000

        def detect_metrics(self, metrics, *, histories=None):
            seen["metrics"] = metrics
            seen["histories"] = histories
            return [_FakeResult()]

    monkeypatch.setattr("src.app.services.anomaly_detector.AnomalyDetector", _FakeDetector)
    monkeypatch.setattr("src.app.tasks.anomaly_tasks.log_trace_event", lambda *args, **kwargs: None, raising=False)

    out = anomaly_tasks.anomaly_hourly_snapshot()

    assert out["status"] == "ok"
    assert seen["metrics"] == {"orders_last_hour": 9.0, "refunds_last_hour": 3.0}
    assert "orders_last_hour" in seen["histories"]
    assert seen["persisted"]["orders_last_hour"] == 9
    assert out["anomalies"][0]["metric"] == "orders_last_hour"
    assert out["anomalies"][0]["severity"] == "high"
