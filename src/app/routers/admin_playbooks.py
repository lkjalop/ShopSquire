from __future__ import annotations

from typing import Any, Dict, Optional
import uuid
import json

from fastapi import APIRouter, Body, Depends, HTTPException

from src.app.models.db import db_session
from src.app.routers.approvals import enqueue_approval
from src.app.security.auth import ROLE_DEVELOPER, ROLE_OWNER, require_role_or_oidc
from src.app.services.decision_log import log_trace_event
from src.app.services.persistence import write_audit_and_event
from src.app.services.playbook_engine import (
    diff_playbook_versions,
    dry_run_playbook_selection,
    get_playbook_action_reliability,
    get_playbook_by_id,
    get_playbook_kpis,
    list_playbook_dlq,
    list_playbooks,
    load_playbook_config,
    publish_playbook_update,
    reprocess_playbook_dlq,
    rollback_playbook_version,
    validate_playbook_config,
)
from src.app.services.trace_broker import recover_pending, replay_recent, stream_health
from src.app.services.llm import get_llm_routing_metrics


router = APIRouter(prefix="/api/v1/admin/playbooks", tags=["admin-playbooks"])


def _approval_status(approval_id: str) -> Optional[Dict[str, Any]]:
    try:
        with db_session() as db:
            row = db.execute(
                """
                SELECT id, capability, status
                FROM approvals
                WHERE id = :id
                """,
                {"id": approval_id},
            ).fetchone()
        if not row:
            return None
        return {"id": row[0], "capability": row[1], "status": row[2]}
    except Exception:
        return None


def _ensure_change_approval(
    *,
    approval_id: str | None,
    capability: str,
    approval_payload: Dict[str, Any],
    actor: str,
) -> Dict[str, Any]:
    if not approval_id:
        aid = enqueue_approval(capability=capability, payload=approval_payload, reason=f"{capability} requested", created_by=actor)
        return {"status": "pending_approval", "approval_id": aid}
    st = _approval_status(approval_id)
    if not st:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if str(st.get("capability") or "") != capability:
        raise HTTPException(status_code=400, detail="approval_capability_mismatch")
    if str(st.get("status") or "").lower() != "approved":
        raise HTTPException(status_code=409, detail="approval_not_granted")
    return {"status": "approved", "approval_id": approval_id}


@router.get("")
def get_playbooks(
    include_disabled: bool = True,
    domain: Optional[str] = None,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return {"playbooks": list_playbooks(include_disabled=include_disabled, domain=domain)}


@router.get("/item/{playbook_id}")
def get_playbook(
    playbook_id: str,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    pb = get_playbook_by_id(playbook_id)
    if not pb:
        raise HTTPException(status_code=404, detail="playbook_not_found")
    return {"playbook": pb}


@router.post("/validate")
def validate_playbooks(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else load_playbook_config()
    ok, errors = validate_playbook_config(config)
    return {"valid": ok, "errors": errors}


@router.post("/dry-run")
def dry_run(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    risk_band = payload.get("risk_band")
    context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
    return dry_run_playbook_selection(tags=[str(t) for t in tags], risk_band=str(risk_band) if risk_band else None, context=context)


@router.post("/publish")
def publish(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    playbook_id = str(payload.get("playbook_id") or "").strip()
    updates = payload.get("updates") if isinstance(payload.get("updates"), dict) else {}
    actor = str(payload.get("actor") or role)
    approval_id = str(payload.get("approval_id") or "").strip() or None
    if not playbook_id:
        raise HTTPException(status_code=400, detail="playbook_id_required")
    if not updates:
        raise HTTPException(status_code=400, detail="updates_required")
    approval = _ensure_change_approval(
        approval_id=approval_id,
        capability="playbook_publish",
        approval_payload={"playbook_id": playbook_id, "updates": updates},
        actor=actor,
    )
    if approval["status"] != "approved":
        return approval
    try:
        res = publish_playbook_update(playbook_id=playbook_id, updates=updates, actor=actor)
        try:
            write_audit_and_event(
                decision_id=f"playbook:{playbook_id}",
                action="playbook_publish",
                actor=actor,
                metadata={"approval_id": approval.get("approval_id"), "before": res.get("before"), "after": res.get("after")},
            )
        except Exception:
            pass
        try:
            trace_id = str(uuid.uuid4())
            payload = {
                "operation": "publish",
                "approval_id": approval.get("approval_id"),
                "actor": actor,
                "before_version": (res.get("before") or {}).get("version"),
                "after_version": (res.get("after") or {}).get("version"),
                "snapshot": res.get("snapshot"),
            }
            log_trace_event(
                trace_id=trace_id,
                event_type="playbook_change",
                source_type="admin",
                source_id="playbook_editor",
                target_type="playbook",
                target_id=playbook_id,
                payload=payload,
            )
        except Exception:
            pass
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rollback")
def rollback(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    playbook_id = str(payload.get("playbook_id") or "").strip()
    target_version = str(payload.get("target_version") or "").strip()
    actor = str(payload.get("actor") or role)
    approval_id = str(payload.get("approval_id") or "").strip() or None
    if not playbook_id or not target_version:
        raise HTTPException(status_code=400, detail="playbook_id_and_target_version_required")
    approval = _ensure_change_approval(
        approval_id=approval_id,
        capability="playbook_rollback",
        approval_payload={"playbook_id": playbook_id, "target_version": target_version},
        actor=actor,
    )
    if approval["status"] != "approved":
        return approval
    try:
        res = rollback_playbook_version(playbook_id=playbook_id, target_version=target_version, actor=actor)
        try:
            write_audit_and_event(
                decision_id=f"playbook:{playbook_id}",
                action="playbook_rollback",
                actor=actor,
                metadata={"approval_id": approval.get("approval_id"), "target_version": target_version, "before": res.get("before"), "after": res.get("after")},
            )
        except Exception:
            pass
        try:
            trace_id = str(uuid.uuid4())
            payload = {
                "operation": "rollback",
                "approval_id": approval.get("approval_id"),
                "actor": actor,
                "target_version": target_version,
                "before_version": (res.get("before") or {}).get("version"),
                "after_version": (res.get("after") or {}).get("version"),
            }
            log_trace_event(
                trace_id=trace_id,
                event_type="playbook_change",
                source_type="admin",
                source_id="playbook_editor",
                target_type="playbook",
                target_id=playbook_id,
                payload=payload,
            )
        except Exception:
            pass
        return {"status": "ok", **res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{playbook_id}/diff")
def get_diff(
    playbook_id: str,
    from_version: str,
    to_version: str,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return diff_playbook_versions(playbook_id=playbook_id, from_version=from_version, to_version=to_version)


@router.get("/kpis/summary")
def get_kpis(
    days: int = 30,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return get_playbook_kpis(days=days)


@router.get("/ops/reliability")
def get_reliability(
    days: int = 30,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return get_playbook_action_reliability(days=days)


@router.get("/trail/{playbook_id}")
def get_playbook_trail(
    playbook_id: str,
    limit: int = 50,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    decision_key = f"playbook:{playbook_id}"
    rows: list[Dict[str, Any]] = []
    try:
        with db_session() as db:
            audit_rows = db.execute(
                """
                SELECT id, decision_id, action, actor, metadata, created_at
                FROM decision_audits
                WHERE decision_id = :decision_id
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"decision_id": decision_key, "limit": limit},
            ).fetchall()
            chain_rows = db.execute(
                """
                SELECT source_id, payload_hash, prev_hash, merkle_root, created_at
                FROM audit_log_chain
                WHERE source_type = 'decision.audit' AND source_id = :source_id
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"source_id": decision_key, "limit": limit},
            ).fetchall()
        chain_by_created = {str(r[4]): r for r in (chain_rows or [])}
        for r in audit_rows or []:
            created = str(r[5])
            c = chain_by_created.get(created)
            metadata = r[4]
            try:
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
            except Exception:
                pass
            rows.append(
                {
                    "id": r[0],
                    "decision_id": r[1],
                    "action": r[2],
                    "actor": r[3],
                    "metadata": metadata,
                    "created_at": created,
                    "chain": {
                        "payload_hash": (c[1] if c else None),
                        "prev_hash": (c[2] if c else None),
                        "merkle_root": (c[3] if c else None),
                    },
                }
            )
    except Exception:
        rows = []
    return {"playbook_id": playbook_id, "decision_id": decision_key, "rows": rows}


@router.get("/ops/dlq")
def get_dlq(
    limit: int = 100,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return list_playbook_dlq(limit=limit)


@router.post("/ops/dlq/reprocess")
def reprocess_dlq(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    limit = int(payload.get("limit") or 50)
    return reprocess_playbook_dlq(limit=limit)


@router.get("/ops/streams/health")
async def get_streams_health(
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return await stream_health()


@router.post("/ops/streams/recover")
async def recover_streams(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    count = int(payload.get("count") or 100)
    return await recover_pending(max_messages=count)


@router.post("/ops/streams/replay")
async def replay_streams(
    payload: Dict[str, Any] = Body(default_factory=dict),
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    count = int(payload.get("count") or 100)
    return await replay_recent(count=count)


@router.get("/ops/llm/routing")
def get_llm_routing(
    window_minutes: int = 60,
    tenant_id: str | None = None,
    role: str = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_DEVELOPER])),
) -> Dict[str, Any]:
    return get_llm_routing_metrics(window_minutes=window_minutes, tenant_id=tenant_id)
