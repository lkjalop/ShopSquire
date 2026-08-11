"""Release-integrity test for evidence scatter/gather telemetry.

The orchestrator intentionally treats metric publication as non-fatal, so a
missing module otherwise degrades silently in a clean checkout.  Keep this
dependency explicit and importable.
"""

from src.app.observability.evidence_metrics import (
    evidence_late_results_total,
    evidence_outstanding_lanes,
)


def test_evidence_scatter_gather_metrics_are_packaged() -> None:
    assert evidence_outstanding_lanes._name == "shopsquire_evidence_outstanding_lanes"
    assert evidence_late_results_total._name == "shopsquire_evidence_late_results"
