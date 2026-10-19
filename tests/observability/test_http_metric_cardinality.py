from uuid import uuid4

from src.app.main import create_app
from fastapi.testclient import TestClient
from src.app.observability.metrics import http_request_duration_seconds
from prometheus_client import CollectorRegistry, Counter, Histogram


def test_new_case_and_missing_resource_ids_do_not_create_metric_series(monkeypatch):
    monkeypatch.setenv('APP_ENV', 'test')
    app = create_app()
    @app.get('/cardinality-probe/{resource_id}')
    def resource(resource_id: str):
        return {'ok': True}
    with TestClient(app) as client:
        for _ in range(12):
            assert client.get('/cardinality-probe/'+uuid4().hex).status_code == 200
            assert client.get('/missing-probe/'+uuid4().hex).status_code == 404
    paths = {labels[1] for labels in http_request_duration_seconds._metrics}
    assert '/cardinality-probe/*' in paths
    assert not any(p.startswith('/cardinality-probe/') and p != '/cardinality-probe/*' for p in paths)
    assert not any(p.startswith('/missing-probe/') for p in paths)


def test_many_registered_routes_share_latency_buckets_but_keep_route_error_counts(monkeypatch):
    from src.app.observability import metrics
    registry = CollectorRegistry()
    counter = Counter('probe_requests', 'Requests', ['method','path','status'], registry=registry)
    duration = Histogram('probe_duration', 'Latency', ['method','path'], registry=registry)
    monkeypatch.setattr(metrics, 'http_requests_total', counter)
    monkeypatch.setattr(metrics, 'http_request_duration_seconds', duration)
    for n in range(100):
        metrics.record_http_metrics('GET', f'/api/v1/inventory/action-{n}/{{resource_id}}', 200, 0.1)
    assert len(counter._metrics) == 100
    assert len(duration._metrics) == 1, 'per-route histogram locks must not grow with the entire API surface'
    assert sum(sample.value for metric in counter.collect() for sample in metric.samples
               if sample.name == 'probe_requests_total') == 100
