from prometheus_client import Counter, Gauge, Histogram


RETURN_RESPONSE_SECONDS = Histogram(
    "shopsquire_return_response_seconds",
    "Return workflow latency by user-visible milestone.",
    labelnames=["milestone", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)

RETURN_EVIDENCE_LANE_SECONDS = Histogram(
    "shopsquire_return_evidence_lane_seconds",
    "Isolated return evidence lane latency.",
    labelnames=["lane", "status"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 4, 7, 10),
)

RETURN_EVIDENCE_OUTSTANDING = Gauge(
    "shopsquire_return_evidence_outstanding",
    "Return evidence jobs currently executing.",
    labelnames=["tenant_id"],
)

RETURN_AUTHORIZATION_BLOCKS = Counter(
    "shopsquire_return_authorization_blocks_total",
    "Return requests blocked at identity, ownership or lifecycle boundaries.",
    labelnames=["reason"],
)
