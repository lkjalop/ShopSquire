"""Tenant-scoped immutable ATP and marketing facts.

These records are evidence, not decisions. Callers must still apply freshness, provenance,
inventory, capability, consent, and action-policy clamps before using them.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text


def _required(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _with_defaults(fact: Dict[str, Any], fields: tuple[str, ...]) -> Dict[str, Any]:
    return {field: fact.get(field) for field in fields} | dict(fact)


def record_atp_fact(db, fact: Dict[str, Any]) -> bool:
    tenant = _required(fact.get("tenant_id"), "tenant_id")
    dedup = _required(fact.get("deduplication_id"), "deduplication_id")
    source = _required(fact.get("source_system"), "source_system")
    observed = _required(fact.get("observed_at"), "observed_at")
    params = _with_defaults(fact, (
        "material_id", "sku", "variant_id", "taxonomy_node", "location_id",
        "requested_quantity", "requested_date", "on_hand_quantity", "committed_quantity",
        "incoming_receipts_quantity", "safety_stock_quantity", "lead_time_days",
        "confirmed_quantity", "confirmed_date", "supplier_id", "source_record_id",
        "valid_from", "valid_to", "freshness_policy",
    ))
    params.update({
        "id": str(fact.get("id") or uuid.uuid4()), "tenant_id": tenant,
        "deduplication_id": dedup, "source_system": source, "observed_at": observed,
        "ingested_at": str(fact.get("ingested_at") or _now()),
        "provenance_json": json.dumps(fact.get("provenance_chain") or []),
        "confidence": _bounded_confidence(fact.get("confidence")),
        "schema_version": int(fact.get("schema_version") or 1),
        "status": str(fact.get("status") or "active"),
    })
    result = db.execute(text("""
        INSERT INTO inventory_atp_fact (
          id, tenant_id, schema_version, deduplication_id, material_id, sku, variant_id,
          taxonomy_node, location_id, requested_quantity, requested_date, on_hand_quantity,
          committed_quantity, incoming_receipts_quantity, safety_stock_quantity, lead_time_days,
          confirmed_quantity, confirmed_date, supplier_id, source_system, source_record_id,
          provenance_json, confidence, observed_at, ingested_at, valid_from, valid_to,
          freshness_policy, status
        ) VALUES (
          :id, :tenant_id, :schema_version, :deduplication_id, :material_id, :sku, :variant_id,
          :taxonomy_node, :location_id, :requested_quantity, :requested_date, :on_hand_quantity,
          :committed_quantity, :incoming_receipts_quantity, :safety_stock_quantity, :lead_time_days,
          :confirmed_quantity, :confirmed_date, :supplier_id, :source_system, :source_record_id,
          :provenance_json, :confidence, :observed_at, :ingested_at, :valid_from, :valid_to,
          :freshness_policy, :status
        ) ON CONFLICT(tenant_id, deduplication_id) DO NOTHING
    """), params)
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0) > 0


def record_marketing_event(db, fact: Dict[str, Any]) -> bool:
    tenant = _required(fact.get("tenant_id"), "tenant_id")
    dedup = _required(fact.get("deduplication_id"), "deduplication_id")
    source = _required(fact.get("source_system"), "source_system")
    event_type = _required(fact.get("event_type"), "event_type")
    occurred = _required(fact.get("occurred_at"), "occurred_at")
    params = _with_defaults(fact, (
        "subject_hash", "session_id", "sku", "variant_id", "taxonomy_node", "campaign_id",
        "creative_id", "channel", "value", "currency", "quantity", "consent_state",
        "attribution_window", "source_record_id", "valid_from", "valid_to", "freshness_policy",
    ))
    params.update({
        "id": str(fact.get("id") or uuid.uuid4()), "tenant_id": tenant,
        "deduplication_id": dedup, "source_system": source, "event_type": event_type,
        "occurred_at": occurred, "ingested_at": str(fact.get("ingested_at") or _now()),
        "provenance_json": json.dumps(fact.get("provenance_chain") or []),
        "confidence": _bounded_confidence(fact.get("confidence")),
        "schema_version": int(fact.get("schema_version") or 1),
        "status": str(fact.get("status") or "active"),
    })
    result = db.execute(text("""
        INSERT INTO marketing_event_fact (
          id, tenant_id, schema_version, deduplication_id, event_type, subject_hash, session_id,
          sku, variant_id, taxonomy_node, campaign_id, creative_id, channel, value, currency,
          quantity, consent_state, attribution_window, source_system, source_record_id,
          provenance_json, confidence, occurred_at, ingested_at, valid_from, valid_to,
          freshness_policy, status
        ) VALUES (
          :id, :tenant_id, :schema_version, :deduplication_id, :event_type, :subject_hash, :session_id,
          :sku, :variant_id, :taxonomy_node, :campaign_id, :creative_id, :channel, :value, :currency,
          :quantity, :consent_state, :attribution_window, :source_system, :source_record_id,
          :provenance_json, :confidence, :occurred_at, :ingested_at, :valid_from, :valid_to,
          :freshness_policy, :status
        ) ON CONFLICT(tenant_id, deduplication_id) DO NOTHING
    """), params)
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0) > 0
