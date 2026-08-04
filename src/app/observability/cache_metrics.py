"""Low-cardinality metrics for governed temporal-cache operations."""
from prometheus_client import Counter


temporal_cache_eviction_total = Counter(
    "shopsquire_temporal_cache_eviction_total",
    "Temporal cache provider eviction outcomes.",
    ("outcome",),
)
