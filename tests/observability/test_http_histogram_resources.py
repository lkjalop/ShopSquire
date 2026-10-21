"""Keep complete HTTP latency buckets within a per-series lock budget."""
from concurrent.futures import ThreadPoolExecutor
import gc
import os
import subprocess
import sys
import threading
from uuid import uuid4

from prometheus_client import CollectorRegistry, Histogram, generate_latest
import pytest

from src.app.observability.metrics import http_request_duration_seconds


def _metric():
    registry = CollectorRegistry()
    metric = type(http_request_duration_seconds)(
        'owned_latency_' + uuid4().hex, 'Owned latency probe', ['method', 'path'], registry=registry,
    )
    return registry, metric


def _samples(metric):
    return {(sample.name.rsplit('_', 1)[-1], tuple(sorted(sample.labels.items()))): sample.value
            for family in metric.collect() for sample in family.samples if not sample.name.endswith('_created')}


def test_http_latency_keeps_every_standard_bucket_and_sample():
    registry, actual = _metric()
    expected = Histogram('reference_latency', 'Reference', ['method', 'path'], registry=None)
    for method, path, values in (
        ('GET', '/health', [0, .005, .025, .5, 1, 2.5, 10, 120]),
        ('POST', '/api/v1/chat/query', [.01, .1, 5, 30]),
    ):
        for value in values:
            actual.labels(method=method, path=path).observe(value)
            expected.labels(method, path).observe(value)
    assert _samples(actual) == _samples(expected)
    raw = generate_latest(registry).decode()
    assert '_bucket{le="+Inf"' in raw or 'le="+Inf"' in raw
    assert '_created' in raw


def test_http_latency_observations_are_exact_under_concurrent_scrapes():
    registry, metric = _metric()

    def observe(_index):
        for _ in range(200):
            metric.labels('POST', '/api/v1/chat/query').observe(.25)
            generate_latest(registry)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(observe, range(8)))
    samples = _samples(metric)
    labels = (('method', 'POST'), ('path', '/api/v1/chat/query'))
    assert samples['count', labels] == 1600
    assert samples['sum', labels] == 400


def test_http_latency_series_use_at_most_two_locks_each():
    lock_type = type(threading.Lock())
    def locks():
        return sum(isinstance(obj, lock_type) for obj in gc.get_objects())

    before = locks()
    registry, metric = _metric()
    for number in range(128):
        metric.labels('GET', f'/api/v1/resource-{number}/*').observe(.1)
    retained = locks() - before
    assert len(list(registry.collect())) >= 1
    assert retained <= 256, f'128 HTTP histogram series retained {retained} value/registry locks'


@pytest.mark.parametrize('labels', [({},), ({'method': 'GET'},), ({'method': 'GET', 'path': '/', 'extra': 'x'},)])
def test_http_latency_rejects_incorrect_label_sets(labels):
    _registry, metric = _metric()
    with pytest.raises(ValueError):
        metric.labels(**labels[0])


def test_http_latency_keeps_native_multiprocess_storage(tmp_path):
    from prometheus_client import multiprocess

    program = '''from prometheus_client import Histogram
from src.app.observability.http_histogram import http_latency_histogram
metric=http_latency_histogram('owned_multiprocess_latency','Owned worker',['method','path'],registry=None)
assert type(metric) is Histogram
for value in (.25,.25,1):
    metric.labels('GET','/owned').observe(value)
'''
    env = {**os.environ, 'PROMETHEUS_MULTIPROC_DIR': str(tmp_path)}
    for _ in range(2):
        worker = subprocess.run([sys.executable, '-c', program], env=env,
                                capture_output=True, text=True, timeout=15)
        assert worker.returncode == 0, worker.stderr
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry, path=str(tmp_path))
    samples = {sample.name: sample.value for family in registry.collect() for sample in family.samples}
    assert samples['owned_multiprocess_latency_count'] == 6
    assert samples['owned_multiprocess_latency_sum'] == 3
