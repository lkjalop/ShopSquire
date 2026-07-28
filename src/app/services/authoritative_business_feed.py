from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.business_semantics import PAYLOAD_MODELS, validate_payload


SUPPORTED_ENTITY_TYPES = frozenset(PAYLOAD_MODELS)


@dataclass(frozen=True)
class BusinessObservation:
    entity_type: str
    external_id: str
    event_time: str
    payload: dict[str, Any]
    schema_version: int = 1
    corrects_observation_id: str | None = None
    reverses_observation_id: str | None = None


def _canonical_payload(payload: dict[str, Any]) -> tuple[str, str]:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("event_time_required")
    parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def business_observation_id(
    *,
    tenant_id: str,
    source: str,
    observation: BusinessObservation,
) -> str:
    """Return the immutable identity used by the append-only observation ledger."""
    entity = str(observation.entity_type or "").strip().lower()
    external_id = str(observation.external_id or "").strip()
    if entity not in SUPPORTED_ENTITY_TYPES:
        raise ValueError(f"unsupported_entity_type:{entity}")
    if not external_id:
        raise ValueError("external_id_required")
    event_time = _parse_time(observation.event_time)
    validated_payload = validate_payload(entity, dict(observation.payload or {}))
    _, payload_hash = _canonical_payload(validated_payload)
    return hashlib.sha256(
        (
            f"{str(tenant_id).strip()}|{str(source).strip().lower()}|{entity}|"
            f"{external_id}|{event_time}|{observation.schema_version}|"
            f"{observation.corrects_observation_id or ''}|"
            f"{observation.reverses_observation_id or ''}|{payload_hash}"
        ).encode("utf-8")
    ).hexdigest()


def load_observations_csv(path: str | Path) -> list[BusinessObservation]:
    rows: list[BusinessObservation] = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            entity = str(row.get("entity_type") or "").strip().lower()
            external_id = str(row.get("external_id") or "").strip()
            if not entity or not external_id:
                raise ValueError(f"invalid_identity_at_line_{line_number}")
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_payload_at_line_{line_number}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"invalid_payload_at_line_{line_number}")
            rows.append(
                BusinessObservation(
                    entity_type=entity,
                    external_id=external_id,
                    event_time=str(row.get("event_time") or ""),
                    payload=payload,
                )
            )
    return rows


def ingest_authoritative_observations(
    *,
    tenant_id: str,
    source: str,
    observations: Iterable[BusinessObservation],
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    if not tenant:
        raise ValueError("authoritative_tenant_required")
    if not source_name:
        raise ValueError("authoritative_source_required")

    run_id = f"feed-{uuid.uuid4().hex}"
    started = datetime.now(timezone.utc).isoformat()
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO authoritative_feed_run
                (id, tenant_id, source, status, records_seen, records_inserted,
                 records_replayed, started_at)
                VALUES (:id, :tenant, :source, 'started', 0, 0, 0, :started)
                """
            ),
            {"id": run_id, "tenant": tenant, "source": source_name, "started": started},
        )
        db.commit()

    seen = inserted = replayed = 0
    try:
        with db_session() as db:
            for item in observations:
                seen += 1
                entity = str(item.entity_type or "").strip().lower()
                external_id = str(item.external_id or "").strip()
                if entity not in SUPPORTED_ENTITY_TYPES:
                    raise ValueError(f"unsupported_entity_type:{entity}")
                if not external_id:
                    raise ValueError("external_id_required")
                event_time = _parse_time(item.event_time)
                if item.schema_version != 1:
                    raise ValueError(f"unsupported_schema_version:{item.schema_version}")
                if item.corrects_observation_id and item.reverses_observation_id:
                    raise ValueError("observation_cannot_correct_and_reverse")
                validated_payload = validate_payload(entity, dict(item.payload or {}))
                payload_json, payload_hash = _canonical_payload(validated_payload)
                observation_id = business_observation_id(
                    tenant_id=tenant,
                    source=source_name,
                    observation=item,
                )
                exists = db.execute(
                    text("SELECT 1 FROM authoritative_business_observation WHERE id=:id"),
                    {"id": observation_id},
                ).fetchone()
                if exists:
                    replayed += 1
                    continue
                supersedes = item.corrects_observation_id or item.reverses_observation_id
                if supersedes:
                    prior = db.execute(
                        text(
                            """
                            SELECT entity_type FROM authoritative_business_observation
                            WHERE id=:id AND tenant_id=:tenant AND source=:source
                            """
                        ),
                        {"id": supersedes, "tenant": tenant, "source": source_name},
                    ).fetchone()
                    if not prior:
                        raise ValueError("superseded_observation_not_in_source_scope")
                    if str(prior[0]) != entity:
                        raise ValueError("superseded_observation_entity_mismatch")
                db.execute(
                    text(
                        """
                        INSERT INTO authoritative_business_observation
                        (id, tenant_id, source, entity_type, external_id,
                         event_time, observed_at, payload_hash, payload_json,
                         quality_status, feed_run_id, schema_version, event_kind,
                         corrects_observation_id, reverses_observation_id)
                        VALUES
                        (:id, :tenant, :source, :entity, :external_id,
                         :event_time, :observed_at, :payload_hash, :payload_json,
                         'accepted', :run_id, :schema_version, :event_kind,
                         :corrects_id, :reverses_id)
                        """
                    ),
                    {
                        "id": observation_id,
                        "tenant": tenant,
                        "source": source_name,
                        "entity": entity,
                        "external_id": external_id,
                        "event_time": event_time,
                        "observed_at": datetime.now(timezone.utc).isoformat(),
                        "payload_hash": payload_hash,
                        "payload_json": payload_json,
                        "run_id": run_id,
                        "schema_version": item.schema_version,
                        "event_kind": (
                            "correction" if item.corrects_observation_id
                            else "reversal" if item.reverses_observation_id
                            else "observation"
                        ),
                        "corrects_id": item.corrects_observation_id,
                        "reverses_id": item.reverses_observation_id,
                    },
                )
                inserted += 1
            db.commit()
        status = "empty" if seen == 0 else "observed"
        error = None
    except Exception as exc:
        status = "malformed"
        error = f"{type(exc).__name__}: {exc}"

    with db_session() as db:
        db.execute(
            text(
                """
                UPDATE authoritative_feed_run
                SET status=:status, records_seen=:seen,
                    records_inserted=:inserted, records_replayed=:replayed,
                    error=:error, finished_at=:finished
                WHERE id=:id
                """
            ),
            {
                "id": run_id,
                "status": status,
                "seen": seen,
                "inserted": inserted,
                "replayed": replayed,
                "error": error,
                "finished": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.commit()
    return {
        "id": run_id,
        "tenant_id": tenant,
        "source": source_name,
        "status": status,
        "records_seen": seen,
        "records_inserted": inserted,
        "records_replayed": replayed,
        "error": error,
    }
