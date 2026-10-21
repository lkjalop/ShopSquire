"""Complete HTTP latency buckets with one lock per labelled series.

Prometheus's public custom-collector protocol keeps collection independent of
its value-storage internals. Multiprocess deployments retain its native store.
"""
from itertools import accumulate
import os
import threading
import time

from prometheus_client import Histogram, REGISTRY
from prometheus_client.core import GaugeMetricFamily, HistogramMetricFamily


class _LatencySeries:
    def __init__(self, bounds):
        self._bounds = bounds
        self._counts = [0] * len(bounds)
        self._sum = 0.0
        self._created = time.time()
        self._lock = threading.Lock()

    def observe(self, amount):
        value = float(amount)
        with self._lock:
            self._sum += value
            for index, upper in enumerate(self._bounds):
                if value <= upper:
                    self._counts[index] += 1
                    break

    def snapshot(self):
        with self._lock:
            return list(accumulate(self._counts)), self._sum, self._created


class HttpLatencyHistogram:
    """Collector for the labelled HTTP metric; bucket resolution is unchanged."""

    def __init__(self, name, documentation, labelnames, registry=REGISTRY):
        self._name = name
        self._documentation = documentation
        self._labelnames = tuple(labelnames)
        self._bounds = Histogram.DEFAULT_BUCKETS
        self._metrics = {}
        self._lock = threading.Lock()
        # Validate the public metric name before registration or observation.
        HistogramMetricFamily(name, documentation, labels=self._labelnames)
        if registry is not None:
            registry.register(self)

    def labels(self, *values, **named):
        if named:
            if values or set(named) != set(self._labelnames):
                raise ValueError('Incorrect HTTP histogram labels')
            values = tuple(named[label] for label in self._labelnames)
        if len(values) != len(self._labelnames):
            raise ValueError('Incorrect HTTP histogram label count')
        labels = tuple(str(value) for value in values)
        with self._lock:
            if labels not in self._metrics:
                self._metrics[labels] = _LatencySeries(self._bounds)
            return self._metrics[labels]

    def describe(self):
        yield HistogramMetricFamily(self._name, self._documentation, labels=self._labelnames)

    def collect(self):
        histogram = HistogramMetricFamily(self._name, self._documentation, labels=self._labelnames)
        created = GaugeMetricFamily(self._name + '_created', self._documentation, labels=self._labelnames)
        with self._lock:
            children = list(self._metrics.items())
        for labels, series in children:
            counts, total, timestamp = series.snapshot()
            buckets = [('+Inf' if upper == float('inf') else str(upper), count)
                       for upper, count in zip(self._bounds, counts)]
            histogram.add_metric(labels, buckets, total)
            created.add_metric(labels, timestamp)
        yield histogram
        if str(os.getenv('PROMETHEUS_DISABLE_CREATED_SERIES', '')).lower() not in {'true', '1', 't'}:
            yield created


def http_latency_histogram(name, documentation, labelnames, registry=REGISTRY):
    if os.getenv('PROMETHEUS_MULTIPROC_DIR') or os.getenv('prometheus_multiproc_dir'):
        return Histogram(name, documentation, labelnames, registry=registry)
    return HttpLatencyHistogram(name, documentation, labelnames, registry=registry)
