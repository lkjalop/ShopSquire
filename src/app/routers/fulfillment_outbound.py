"""Operator-owned durable outbound queue endpoints; delivery stays in the worker."""
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from src.app.models.db import db_session
from src.app.security.auth import ROLE_MERCHANT, ROLE_OWNER, require_role
from src.app.services.fulfillment import workflow as fwf
from src.app.services.fulfillment.domain import Actor, ActorType

router = APIRouter()
_OPERATOR = [ROLE_MERCHANT, ROLE_OWNER]


def _replay_deferred_send_transitions(db, sent_rows: list) -> Dict[str, int]:
    """A background delivery only TRANSMITS; the case still sits in APPROVED_TO_SEND. Here we replay the
    EXACT transition that the human (or autonomous agent) already approved at dispatch time — recorded on the
    queue row — so a deferred send advances the case to QUOTE_SENT instead of stranding it. Idempotent: a case
    already advanced (or superseded) simply fails the guard and is counted as skipped, never re-fired."""
    advanced, skipped = 0, 0
    for row in (sent_rows or []):
        ev = str(row.get("transition_event") or "")
        a_type = str(row.get("actor_type") or "")
        cid = str(row.get("case_id") or "")
        if not (ev and a_type and cid):
            skipped += 1
            continue
        try:
            actor = Actor(ActorType(a_type), str(row.get("actor_id") or ""))
            res = fwf.transition(db, case_id=cid, event=ev, actor=actor, reason_code="deferred_send_delivered",
                                 evidence={"provider_ref": row.get("provider_ref", ""), "deferred": True},
                                 state_patch={"outbound": {"provider_ref": row.get("provider_ref", ""),
                                                           "content_hash": row.get("content_hash"), "status": "sent",
                                                           "transport": "queued"}})
            if getattr(res, "ok", False):
                advanced += 1
            else:
                skipped += 1  # case no longer in APPROVED_TO_SEND (e.g. superseded) — guard refused, by design
        except Exception:
            skipped += 1
    return {"advanced": advanced, "skipped": skipped}


@router.post("/outbound/process", status_code=202)
def outbound_process(
    limit: int = 50,
    role: str = Depends(require_role(_OPERATOR)),
) -> Dict[str, Any]:
    """Drive the durable outbound queue once — attempt every DUE pending send, backing off failures and
    dead-lettering exhausted ones. A deferred delivery then REPLAYS the approved transition so the case advances
    to QUOTE_SENT (no stranding). In production a worker calls this on a schedule; here an operator can too."""
    import uuid
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.fulfillment import outbound_delivery
    from src.app.tasks.fulfillment_tasks import process_outbound_delivery

    tenant_id = str(current_tenant_id() or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail={"error": "tenant_scope_missing"})
    bounded_limit = max(1, min(int(limit), 100))
    job_id = f"outjob-{uuid.uuid4().hex}"
    with db_session() as db:
        outbound_delivery.create_job(
            db,
            job_id=job_id,
            tenant_id=tenant_id,
            requested_by=role,
            limit=bounded_limit,
        )
    try:
        process_outbound_delivery.apply_async(
            kwargs={
                "tenant_id": tenant_id,
                "job_id": job_id,
                "limit": bounded_limit,
            },
            task_id=job_id,
            retry=True,
            retry_policy={
                "max_retries": 3,
                "interval_start": 0,
                "interval_step": 1,
                "interval_max": 3,
            },
        )
    except Exception as exc:
        with db_session() as db:
            outbound_delivery.finish_job(
                db,
                job_id=job_id,
                tenant_id=tenant_id,
                error=f"publish_failed:{type(exc).__name__}",
            )
        raise HTTPException(
            status_code=503,
            detail={"error": "outbound_job_publish_failed"},
        )
    return {
        "accepted": True,
        "job_id": job_id,
        "tenant_id": tenant_id,
        "status": "queued",
    }


@router.get("/outbound/jobs/{job_id}")
def outbound_job_status(
    job_id: str,
    role: str = Depends(require_role(_OPERATOR)),
) -> Dict[str, Any]:
    from src.app.platform.tenant_context import current_tenant_id
    from src.app.services.fulfillment import outbound_delivery

    tenant_id = str(current_tenant_id() or "").strip()
    with db_session() as db:
        result = outbound_delivery.job_status(
            db,
            job_id=job_id,
            tenant_id=tenant_id,
        )
    if not result:
        raise HTTPException(
            status_code=404,
            detail={"error": "outbound_job_not_found"},
        )
    return result


@router.get("/outbound/status")
def outbound_status(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """Queue health: counts by status + how many sent messages are still unacknowledged (no 855)."""
    from src.app.services.fulfillment import outbound_queue as oq
    from src.app.platform.tenant_context import current_tenant_id
    with db_session() as db:
        return oq.queue_status(
            db,
            tenant_id=str(current_tenant_id() or ""),
        )


@router.get("/outbound/dead-letters")
def outbound_dead_letters(role: str = Depends(require_role(_OPERATOR))) -> Dict[str, Any]:
    """The sends that exhausted their retries — operator triage queue."""
    from src.app.services.fulfillment import outbound_queue as oq
    from src.app.platform.tenant_context import current_tenant_id
    with db_session() as db:
        return {
            "dead_letters": oq.dead_letters(
                db,
                tenant_id=str(current_tenant_id() or ""),
            )
        }
