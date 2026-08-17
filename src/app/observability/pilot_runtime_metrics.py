"""Low-cardinality pilot signals used by alert rules and operator dashboards."""
from prometheus_client import Counter, Gauge, Histogram


model_execution_outcomes_total = Counter(
    "shopsquire_model_execution_outcomes_total",
    "Governed model execution outcomes.",
    ("status", "failure_code"),
)
model_execution_duration_seconds = Histogram(
    "shopsquire_model_execution_duration_seconds",
    "Governed model execution latency.",
    buckets=(0.1, 0.25, 0.5, 1, 2, 4, 8, 15, 30, 60, 120),
)
model_late_results_total = Counter(
    "shopsquire_model_late_results_total",
    "Model results quarantined after timeout or cancellation.",
)
agent_ledger_persistence_failures_total = Counter(
    "shopsquire_agent_ledger_persistence_failures_total",
    "Failures writing the durable AgentRunEvent ledger.",
)
official_parser_outcomes_total = Counter(
    "shopsquire_official_parser_outcomes_total",
    "Official-origin parser outcomes.",
    ("status", "failure_code"),
)
carrier_transport_outcomes_total = Counter(
    "shopsquire_carrier_transport_outcomes_total",
    "Carrier transport outcomes.",
    ("status",),
)
discovery_engine_outcomes_total = Counter(
    "shopsquire_discovery_engine_outcomes_total",
    "Search-engine observations reported by the local discovery provider.",
    ("outcome",),
)
commerce_idempotency_conflicts_total = Counter(
    "shopsquire_commerce_idempotency_conflicts_total",
    "Commerce request idempotency conflicts.",
    ("conflict_type",),
)
recommendation_audit_capacity_rejections_total = Counter(
    "shopsquire_recommendation_audit_capacity_rejections_total",
    "Recommendation audit writes rejected before enqueue because the bounded outbox was full.",
)
database_pool_checked_out = Gauge(
    "shopsquire_database_pool_checked_out",
    "Currently checked-out SQLAlchemy connections.",
)
database_pool_capacity = Gauge(
    "shopsquire_database_pool_capacity",
    "Configured SQLAlchemy base plus overflow connection capacity.",
)


def record_model_outcome(status: str, failure_code: str | None, elapsed_ms: int) -> None:
    model_execution_outcomes_total.labels(
        status=str(status or "unknown"),
        failure_code=str(failure_code or "none"),
    ).inc()
    model_execution_duration_seconds.observe(max(0.0, float(elapsed_ms) / 1_000.0))


def observe_database_pool(engine) -> dict[str, int | str]:
    pool = engine.pool
    checked_out_fn = getattr(pool, "checkedout", None)
    size_fn = getattr(pool, "size", None)
    checked_out = int(checked_out_fn()) if callable(checked_out_fn) else 0
    base_size = int(size_fn()) if callable(size_fn) else 0
    max_overflow = max(0, int(getattr(pool, "_max_overflow", 0) or 0))
    capacity = max(0, base_size + max_overflow)
    database_pool_checked_out.set(checked_out)
    database_pool_capacity.set(capacity)
    return {
        "status": "observed" if capacity else "not_applicable",
        "checked_out": checked_out,
        "capacity": capacity,
    }


__all__ = [
    "agent_ledger_persistence_failures_total",
    "carrier_transport_outcomes_total",
    "commerce_idempotency_conflicts_total",
    "discovery_engine_outcomes_total",
    "model_late_results_total",
    "official_parser_outcomes_total",
    "recommendation_audit_capacity_rejections_total",
    "observe_database_pool",
    "record_model_outcome",
]
