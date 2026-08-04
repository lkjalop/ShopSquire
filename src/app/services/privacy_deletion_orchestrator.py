"""Durable stage reporting for privacy deletion.

The job stores only a tenant-bound subject hash. Raw identifiers remain in the
bounded deletion call and are never written to the orchestration ledger.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start_job(*, tenant_id: str, subject_hash: str) -> str:
    job_id = f"pdj_{uuid.uuid4().hex}"
    now = _now()
    with db_session() as db:
        db.execute(
            text(
                "INSERT INTO privacy_deletion_job "
                "(id,tenant_id,subject_hash,status,stages_json,action_required_json,created_at,updated_at) "
                "VALUES (:id,:tenant_id,:subject_hash,'running',:stages,:actions,:now,:now)"
            ),
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "subject_hash": subject_hash,
                "stages": "{}",
                "actions": "[]",
                "now": now,
            },
        )
        db.commit()
    return job_id


def finish_job(
    job_id: str,
    *,
    tenant_id: str,
    stages: dict[str, Any],
    action_required: list[str],
    failed: bool = False,
) -> dict[str, Any]:
    status = "failed" if failed else ("action_required" if action_required else "completed")
    now = _now()
    with db_session() as db:
        db.execute(
            text(
                "UPDATE privacy_deletion_job SET status=:status, stages_json=:stages, "
                "action_required_json=:actions, updated_at=:now "
                "WHERE id=:id AND tenant_id=:tenant_id"
            ),
            {
                "id": job_id,
                "tenant_id": tenant_id,
                "status": status,
                "stages": json.dumps(stages, sort_keys=True, default=str),
                "actions": json.dumps(action_required, sort_keys=True),
                "now": now,
            },
        )
        db.commit()
    return {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "status": status,
        "stages": stages,
        "action_required": action_required,
        "updated_at": now.isoformat(),
    }


def get_job(job_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    with db_session() as db:
        row = db.execute(
            text(
                "SELECT id,tenant_id,subject_hash,status,stages_json,action_required_json,"
                "created_at,updated_at FROM privacy_deletion_job "
                "WHERE id=:id AND tenant_id=:tenant_id"
            ),
            {"id": job_id, "tenant_id": tenant_id},
        ).mappings().first()
    if row is None:
        return None
    out = dict(row)
    out["stages"] = json.loads(str(out.pop("stages_json") or "{}"))
    out["action_required"] = json.loads(str(out.pop("action_required_json") or "[]"))
    return out
