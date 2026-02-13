from __future__ import annotations

from typing import Dict, Any


class AnalyticsEventSink:
    """Lightweight sink placeholder for graph/time-series enrichment."""

    def record(self, event: Dict[str, Any]) -> None:
        # Intentionally minimal: upstream services already persist to decision_logs
        # and security_events. This sink exists as a stable integration point.
        return None
