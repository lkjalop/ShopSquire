"""Tenant-scoped immutable ATP and marketing facts.

These records are evidence, not decisions. Callers must still apply freshness, provenance,
inventory, capability, consent, and action-policy clamps before using them.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import text


class MarketFactRejected(ValueError):
    """The fact was retained in quarantine but cannot enter the canonical evidence store."""


@lru_cache(maxsize=1)
def _source_registry() -> Dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "config" / "market_fact_sources.json"
    return json.loads(path.read_text(encoding="utf-8")).get("sources", {})


def signature_payload(fact: Dict[str, Any]) -> bytes:
    bounded = {str(k): v for k, v in fact.items()
               if k not in {"signature", "id", "ingested_at", "status"}}
    return json.dumps(bounded, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def sign_fact(fact: Dict[str, Any], secret: str) -> str:
    return hmac.new(str(secret).encode("utf-8"), signature_payload(fact), hashlib.sha256).hexdigest()


def _parse_time(value: Any) -> datetime:
    raw = _required(value, "observed_at")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_fact(family: str, fact: Dict[str, Any], *, now: datetime | None = None) -> str | None:
    source = _required(fact.get("source_system"), "source_system")
    policy = _source_registry().get(source)
    if not isinstance(policy, dict) or family not in set(policy.get("families") or []):
        return "source_not_allowlisted"
    if not str(fact.get("source_record_id") or "").strip():
        return "missing_source_record_id"
    provenance = fact.get("provenance_chain")
    if not isinstance(provenance, list) or not provenance or not all(str(x).strip() for x in provenance):
        return "missing_provenance_chain"
    try:
        observed = _parse_time(fact.get("observed_at") or fact.get("occurred_at"))
    except (TypeError, ValueError, OverflowError):
        return "invalid_event_time"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - observed).total_seconds()
    if age < -300:
        return "event_time_in_future"
    if age > float(policy.get("max_age_seconds") or 0):
        return "event_too_stale"
    if policy.get("signature") == "hmac":
        secret = os.getenv(str(policy.get("secret_env") or ""), "")
        provided = str(fact.get("signature") or "")
        if not secret:
            return "source_secret_unconfigured"
        if not provided or not hmac.compare_digest(provided, sign_fact(fact, secret)):
            return "invalid_source_signature"
    return None


def _quarantine(db, family: str, fact: Dict[str, Any], reason: str) -> None:
    tenant = str(fact.get("tenant_id") or "unknown").strip() or "unknown"
    payload = {k: v for k, v in fact.items() if k != "signature"}
    db.execute(text("""
        INSERT INTO market_fact_quarantine (
          id, tenant_id, family, source_system, source_record_id, deduplication_id,
          reason_code, payload_json, quarantined_at
        ) VALUES (:id,:tenant,:family,:source,:record,:dedup,:reason,:payload,:at)
        ON CONFLICT(tenant_id, family, deduplication_id, reason_code) DO NOTHING
    """), {"id": str(uuid.uuid4()), "tenant": tenant, "family": family,
           "source": fact.get("source_system"), "record": fact.get("source_record_id"),
           "dedup": fact.get("deduplication_id"), "reason": reason,
           "payload": json.dumps(payload, default=str), "at": _now()})


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


def record_atp_fact(db, fact: Dict[str, Any], *, commit: bool = True,
                    now: datetime | None = None) -> bool:
    tenant = _required(fact.get("tenant_id"), "tenant_id")
    dedup = _required(fact.get("deduplication_id"), "deduplication_id")
    source = _required(fact.get("source_system"), "source_system")
    rejected = _validate_fact("atp", fact, now=now)
    if rejected:
        _quarantine(db, "atp", fact, rejected)
        if commit:
            db.commit()
        raise MarketFactRejected(rejected)
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
    if commit:
        db.commit()
    return int(getattr(result, "rowcount", 0) or 0) > 0


def record_marketing_event(db, fact: Dict[str, Any], *, commit: bool = True,
                           now: datetime | None = None) -> bool:
    tenant = _required(fact.get("tenant_id"), "tenant_id")
    dedup = _required(fact.get("deduplication_id"), "deduplication_id")
    source = _required(fact.get("source_system"), "source_system")
    event_type = _required(fact.get("event_type"), "event_type")
    rejected = _validate_fact("marketing", fact, now=now)
    if rejected:
        _quarantine(db, "marketing", fact, rejected)
        if commit:
            db.commit()
        raise MarketFactRejected(rejected)
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
    if commit:
        db.commit()
    return int(getattr(result, "rowcount", 0) or 0) > 0
