from __future__ import annotations

import email.utils
import json
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Generic, TypeVar

from sqlalchemy import text

from src.app.models.db import db_session


T = TypeVar("T")


class ConnectorOutcomeType(str, Enum):
    OBSERVED = "observed"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"
    UNAUTHORISED = "unauthorised"
    MALFORMED = "malformed"
    PARTIAL = "partial"


@dataclass(frozen=True)
class ConnectorOutcome(Generic[T]):
    outcome: ConnectorOutcomeType
    value: T
    error: str | None = None
    retry_after_seconds: float | None = None
    checkpoint: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in {
            ConnectorOutcomeType.OBSERVED,
            ConnectorOutcomeType.EMPTY,
            ConnectorOutcomeType.PARTIAL,
        }


@dataclass(frozen=True)
class CursorState:
    cursor: str | None
    version: int
    checkpoint: dict[str, Any] | None


def _scope(value: str | None, fallback: str) -> str:
    return str(value or fallback).strip() or fallback


def get_cursor_state(
    *,
    tenant_id: str | None,
    provider: str,
    subscription_id: str | None = None,
    entity_type: str = "inventory",
) -> CursorState:
    params = {
        "tenant_id": _scope(tenant_id, "__global__"),
        "provider": _scope(provider, "unknown"),
        "subscription_id": _scope(subscription_id, "default"),
        "entity_type": _scope(entity_type, "inventory"),
    }
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT cursor_value, cursor_version, checkpoint_json
                FROM erp_sync_state
                WHERE tenant_id=:tenant_id AND provider=:provider
                  AND subscription_id=:subscription_id AND entity_type=:entity_type
                LIMIT 1
                """
            ),
            params,
        ).fetchone()
    if not row:
        return CursorState(cursor=None, version=0, checkpoint=None)
    checkpoint = None
    if row[2]:
        try:
            parsed = json.loads(row[2])
            checkpoint = parsed if isinstance(parsed, dict) else None
        except (TypeError, ValueError):
            checkpoint = None
    return CursorState(
        cursor=str(row[0]) if row[0] is not None else None,
        version=int(row[1] or 0),
        checkpoint=checkpoint,
    )


def compare_and_set_cursor(
    *,
    tenant_id: str | None,
    provider: str,
    expected_version: int,
    cursor_value: str | None,
    checkpoint: dict[str, Any] | None = None,
    subscription_id: str | None = None,
    entity_type: str = "inventory",
) -> CursorState:
    tenant = _scope(tenant_id, "__global__")
    provider_name = _scope(provider, "unknown")
    subscription = _scope(subscription_id, "default")
    entity = _scope(entity_type, "inventory")
    next_version = int(expected_version) + 1
    checkpoint_json = json.dumps(checkpoint, sort_keys=True) if checkpoint is not None else None
    with db_session() as db:
        if int(expected_version) == 0:
            existing = db.execute(
                text(
                    """
                    SELECT cursor_version
                    FROM erp_sync_state
                    WHERE tenant_id=:tenant AND provider=:provider
                      AND subscription_id=:subscription AND entity_type=:entity
                    LIMIT 1
                    """
                ),
                {
                    "tenant": tenant,
                    "provider": provider_name,
                    "subscription": subscription,
                    "entity": entity,
                },
            ).fetchone()
            if existing is not None:
                # Do not attempt an INSERT: ShopSquire's SQLite compatibility
                # layer rewrites plain inserts to OR REPLACE, which would turn
                # a stale writer into a destructive overwrite.
                pass
            else:
                try:
                    db.execute(
                        text(
                            """
                            INSERT INTO erp_sync_state
                            (id, tenant_id, provider, subscription_id, entity_type,
                             cursor_value, cursor_version, checkpoint_json, updated_at)
                            VALUES
                            (:id, :tenant, :provider, :subscription, :entity,
                             :cursor, 1, :checkpoint, CURRENT_TIMESTAMP)
                            """
                        ),
                        {
                            "id": f"erpstate:{uuid.uuid4().hex}",
                            "tenant": tenant,
                            "provider": provider_name,
                            "subscription": subscription,
                            "entity": entity,
                            "cursor": cursor_value,
                            "checkpoint": checkpoint_json,
                        },
                    )
                    db.commit()
                    return CursorState(cursor=cursor_value, version=1, checkpoint=checkpoint)
                except Exception:
                    db.rollback()
        result = db.execute(
            text(
                """
                UPDATE erp_sync_state
                SET cursor_value=:cursor, cursor_version=:next_version,
                    checkpoint_json=:checkpoint, updated_at=CURRENT_TIMESTAMP
                WHERE tenant_id=:tenant AND provider=:provider
                  AND subscription_id=:subscription AND entity_type=:entity
                  AND cursor_version=:expected_version
                """
            ),
            {
                "cursor": cursor_value,
                "next_version": next_version,
                "checkpoint": checkpoint_json,
                "tenant": tenant,
                "provider": provider_name,
                "subscription": subscription,
                "entity": entity,
                "expected_version": int(expected_version),
            },
        )
        if int(result.rowcount or 0) != 1:
            db.rollback()
            raise RuntimeError("connector_cursor_conflict")
        db.commit()
    return CursorState(cursor=cursor_value, version=next_version, checkpoint=checkpoint)


@dataclass
class _TokenEntry:
    token: str
    expires_at: float


class TenantTokenCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], _TokenEntry] = {}
        self._lock = threading.RLock()

    def get(self, *, tenant_id: str | None, provider: str, subscription_id: str | None) -> str | None:
        key = (
            _scope(tenant_id, "__global__"),
            _scope(provider, "unknown"),
            _scope(subscription_id, "default"),
        )
        with self._lock:
            item = self._entries.get(key)
            if not item or item.expires_at <= time.monotonic() + 15:
                self._entries.pop(key, None)
                return None
            return item.token

    def put(
        self,
        *,
        tenant_id: str | None,
        provider: str,
        subscription_id: str | None,
        token: str,
        expires_in_seconds: float,
    ) -> None:
        key = (
            _scope(tenant_id, "__global__"),
            _scope(provider, "unknown"),
            _scope(subscription_id, "default"),
        )
        ttl = max(30.0, min(float(expires_in_seconds or 300), 86400.0))
        with self._lock:
            self._entries[key] = _TokenEntry(token=str(token), expires_at=time.monotonic() + ttl)


TOKEN_CACHE = TenantTokenCache()


def retry_after_seconds(value: str | None, *, now: datetime | None = None, cap_seconds: float = 60.0) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), float(cap_seconds)))
    except ValueError:
        pass
    try:
        target = email.utils.parsedate_to_datetime(raw)
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, min((target - current).total_seconds(), float(cap_seconds)))
    except (TypeError, ValueError, OverflowError):
        return None


class JobBudget:
    def __init__(self, seconds: float) -> None:
        self.deadline = time.monotonic() + max(0.1, float(seconds))

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def require_remaining(self) -> float:
        remaining = self.remaining()
        if remaining <= 0:
            raise TimeoutError("connector_job_budget_exhausted")
        return remaining


def recover_stalled_inventory_runs(*, stale_after_seconds: int = 900) -> int:
    seconds = max(30, int(stale_after_seconds))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    with db_session() as db:
        result = db.execute(
            text(
                """
                UPDATE inventory_sync_runs
                SET status='stalled', outcome_type='unavailable',
                    finished_at=CURRENT_TIMESTAMP,
                    error=COALESCE(error, 'stalled_job_recovered')
                WHERE status='started'
                  AND COALESCE(heartbeat_at, started_at) < :cutoff
                """
            ),
            {"cutoff": cutoff.isoformat()},
        )
        db.commit()
        return int(result.rowcount or 0)


def recover_stalled_erp_outbound(*, stale_after_seconds: int = 900) -> int:
    seconds = max(30, int(stale_after_seconds))
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()
    with db_session() as db:
        result = db.execute(
            text(
                """
                UPDATE erp_outbound_queue
                SET status=CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'retry' END,
                    claimed_at=NULL,
                    last_error=COALESCE(last_error, 'stalled_job_recovered'),
                    updated_at=CURRENT_TIMESTAMP
                WHERE status='processing' AND claimed_at < :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
        db.commit()
        return int(result.rowcount or 0)
