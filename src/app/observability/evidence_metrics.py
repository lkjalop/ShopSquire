"""Bounded scatter-gather resource metrics."""
from prometheus_client import Counter, Gauge


evidence_outstanding_lanes = Gauge(
    "shopsquire_evidence_outstanding_lanes",
    "Evidence lanes whose underlying work has not completed.",
)
evidence_late_results_total = Counter(
    "shopsquire_evidence_late_results_total",
    "Evidence results rejected after their authority deadline.",
    ("lane",),
)
