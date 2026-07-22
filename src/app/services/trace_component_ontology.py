"""Canonical component roles for trace producers.

Legacy producer IDs are preserved for joins and historical replay. This projection controls how
new traces describe authority: only model-directed components are agents; ordinary execution is
a stage, connector, gate, observer, or workflow.
"""
from __future__ import annotations

from typing import Dict


_MODEL_DIRECTED = {
    "recommendation_agent",
    "research_agent",
    "buyer_intent_agent",
}


def classify_trace_component(source_type: str | None, source_id: str | None) -> Dict[str, str]:
    raw_type = str(source_type or "unknown").strip().lower()
    raw_id = str(source_id or raw_type or "unknown").strip()
    token = raw_id.lower()
    if token in _MODEL_DIRECTED:
        kind, authority = "agent", "proposes"
    elif any(part in token for part in ("gate", "guard", "policy", "firewall", "authorization")):
        kind, authority = "gate", "authorizes"
    elif any(part in token for part in ("observer", "trace", "audit", "telemetry", "memory")):
        kind, authority = "observer", "observes"
    elif any(part in token for part in ("inventory", "market", "supplier_channel", "connector", "retrieval")):
        kind, authority = "connector", "retrieves"
    elif any(part in token for part in ("workflow", "procurement", "fulfillment", "orchestrator")):
        kind, authority = "workflow", "coordinates"
    else:
        kind, authority = "stage", "executes"

    label = raw_id
    if kind != "agent" and label.lower().endswith("_agent"):
        label = label[:-6]
    label = label.replace("_", " ").strip()
    return {"kind": kind, "authority": authority, "label": label or kind.title(), "legacy_id": raw_id}
