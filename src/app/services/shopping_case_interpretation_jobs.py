"""Durable two-phase interpretation for open-world shopping cases.

The request path persists a revision-bound job and returns the deterministic
catalog projection. A bounded worker may later improve discovery vocabulary;
its output has discovery-proposal authority only and is rejected when the case
revision changed while it was running.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update

from src.app.models.orm import ShoppingCase, ShoppingCaseInterpretationJob
from src.app.services.case_research_plan import CaseResearchPlan


TASK_NAME = "shopping_case_interpretation"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_id(tenant_id: str, case_id: str, revision: int, plan_id: str) -> str:
    digest = hashlib.sha256(
        f"{tenant_id}\x1f{case_id}\x1f{revision}\x1f{plan_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"sci-{digest}"


def project_job(job: ShoppingCaseInterpretationJob) -> dict[str, Any]:
    receipt_authority = str((job.receipt_json or {}).get("authority") or "none")
    return {
        "schema_version": "shopping-case-interpretation-job-v1",
        "job_id": job.job_id,
        "case_id": job.case_id,
        "case_revision": job.case_revision,
        "plan_id": job.plan_id,
        "status": job.status,
        "receipt": job.receipt_json,
        "result": job.result_plan_json if job.status == "completed" else None,
        "error_code": job.error_code,
        "authority": receipt_authority if job.status == "completed" else "none",
        "commercial_authority": False,
    }


def schedule_case_interpretation(
    db,
    *,
    case: ShoppingCase,
    plan: CaseResearchPlan,
) -> dict[str, Any]:
    """Persist before enqueue; duplicate scheduling returns the same job."""

    if str(os.getenv("OPEN_WORLD_QUERY_PROPOSER_ASYNC_ENABLED", "0")).strip().lower() not in {
        "1", "true", "yes", "on",
    }:
        return {
            "schema_version": "shopping-case-interpretation-job-v1",
            "job_id": None, "case_id": case.case_id,
            "case_revision": int(case.revision or 1), "plan_id": plan.plan_id,
            "status": "disabled", "authority": "none",
            "commercial_authority": False,
        }

    revision = int(case.revision or 1)
    job_id = _job_id(case.tenant_id, case.case_id, revision, plan.plan_id)
    existing = db.execute(select(ShoppingCaseInterpretationJob).where(
        ShoppingCaseInterpretationJob.job_id == job_id,
    )).scalar_one_or_none()
    if existing is not None:
        return project_job(existing)
    stamp = _now()
    job = ShoppingCaseInterpretationJob(
        job_id=job_id,
        tenant_id=case.tenant_id,
        case_id=case.case_id,
        uid=case.uid,
        case_revision=revision,
        plan_id=plan.plan_id,
        status="queued",
        input_plan_json=plan.model_dump(mode="json"),
        attempts=0,
        created_at=stamp,
        updated_at=stamp,
    )
    db.add(job)
    db.commit()
    try:
        from src.app.workers.task_runner import submit_task

        task_id = submit_task(TASK_NAME, {
            "job_id": job_id,
            "tenant_id": case.tenant_id,
        })
        job.task_id = task_id
        job.updated_at = _now()
        db.commit()
    except RuntimeError as exc:
        job.status = "enqueue_degraded"
        job.error_code = str(exc)[:120]
        job.updated_at = _now()
        db.commit()
    return project_job(job)


def _claim_job(db, *, job_id: str, tenant_id: str) -> ShoppingCaseInterpretationJob | None:
    job = db.execute(select(ShoppingCaseInterpretationJob).where(
        ShoppingCaseInterpretationJob.job_id == job_id,
        ShoppingCaseInterpretationJob.tenant_id == tenant_id,
    )).scalar_one_or_none()
    if job is None or job.status not in {"queued", "enqueue_degraded", "retry"}:
        return None
    claimed = db.execute(update(ShoppingCaseInterpretationJob).where(
        ShoppingCaseInterpretationJob.job_id == job_id,
        ShoppingCaseInterpretationJob.tenant_id == tenant_id,
        ShoppingCaseInterpretationJob.status.in_(("queued", "enqueue_degraded", "retry")),
    ).values(
        status="running", attempts=ShoppingCaseInterpretationJob.attempts + 1,
        updated_at=_now(), error_code=None,
    ))
    if int(claimed.rowcount or 0) != 1:
        db.rollback()
        return None
    db.commit()
    return db.execute(select(ShoppingCaseInterpretationJob).where(
        ShoppingCaseInterpretationJob.job_id == job_id,
    )).scalar_one()


def execute_case_interpretation_job(payload: dict[str, Any]) -> None:
    """Worker entry point. Late results are persisted as superseded, never applied."""

    from src.app.models.db import db_session
    from src.app.services.decision_log import log_trace_event
    from src.app.services.open_world_query_proposal import propose_open_world_queries

    job_id = str(payload.get("job_id") or "")
    tenant_id = str(payload.get("tenant_id") or "")
    if not job_id or not tenant_id:
        raise ValueError("interpretation_job_identity_required")
    with db_session() as db:
        job = _claim_job(db, job_id=job_id, tenant_id=tenant_id)
        if job is None:
            return
        plan = CaseResearchPlan.model_validate(job.input_plan_json)
        expected_revision = int(job.case_revision)
        case_id = job.case_id

    try:
        proposed, receipt = propose_open_world_queries(plan, timeout_s=6.0)
    except Exception as exc:
        # A task runner may retry this job. Return it to a claimable state so a
        # transient model/runtime failure cannot strand the durable row as
        # permanently running.
        with db_session() as db:
            db.execute(update(ShoppingCaseInterpretationJob).where(
                ShoppingCaseInterpretationJob.job_id == job_id,
                ShoppingCaseInterpretationJob.tenant_id == tenant_id,
                ShoppingCaseInterpretationJob.status == "running",
            ).values(
                status="retry", error_code=type(exc).__name__, updated_at=_now(),
            ))
            db.commit()
        raise

    with db_session() as db:
        job = db.execute(select(ShoppingCaseInterpretationJob).where(
            ShoppingCaseInterpretationJob.job_id == job_id,
            ShoppingCaseInterpretationJob.tenant_id == tenant_id,
        )).scalar_one()
        case = db.execute(select(ShoppingCase).where(
            ShoppingCase.tenant_id == tenant_id,
            ShoppingCase.case_id == case_id,
        )).scalar_one_or_none()
        stamp = _now()
        if case is None or int(case.revision or 1) != expected_revision:
            job.status = "superseded"
            job.error_code = "case_revision_superseded"
            job.receipt_json = receipt
            job.completed_at = stamp
            job.updated_at = stamp
            db.commit()
            return
        job.status = "completed"
        job.result_plan_json = proposed.model_dump(mode="json")
        job.receipt_json = receipt
        job.completed_at = stamp
        job.updated_at = stamp
        db.commit()

    proposal_authority = str(receipt.get("authority") or "none")
    log_trace_event(
        trace_id=case_id.removeprefix("sc-"),
        event_type="case_interpretation_completed",
        source_type="stage",
        source_id="Open_World_Query_Interpreter",
        target_type="shopping_case",
        target_id=case_id,
        payload={
            "case_id": case_id,
            "case_revision": expected_revision,
            "job_id": job_id,
            "interpretations": [
                row.model_dump(mode="json") for row in proposed.hypotheses
            ],
            "discovery_queries": [
                row.model_dump(mode="json") for row in proposed.discovery_queries
            ],
            "receipt": receipt,
            "authority": proposal_authority,
            "qualification_authority": "none",
            "commercial_authority": "none",
            "observed_at": _now().isoformat(),
        },
        tenant_id=tenant_id,
    )


def consume_completed_case_interpretation(
    db,
    *,
    tenant_id: str,
    case_id: str,
    case_revision: int,
    plan: CaseResearchPlan,
) -> tuple[CaseResearchPlan, dict[str, Any]]:
    job = db.execute(select(ShoppingCaseInterpretationJob).where(
        ShoppingCaseInterpretationJob.tenant_id == tenant_id,
        ShoppingCaseInterpretationJob.case_id == case_id,
        ShoppingCaseInterpretationJob.case_revision == case_revision,
        ShoppingCaseInterpretationJob.plan_id == plan.plan_id,
    )).scalar_one_or_none()
    if job is None:
        return plan, {"status": "not_scheduled", "authority": "none", "model_calls": 0}
    if job.status != "completed" or not job.result_plan_json:
        return plan, {
            "status": job.status,
            "authority": "none",
            "model_calls": 0,
            "job_id": job.job_id,
        }
    return CaseResearchPlan.model_validate(job.result_plan_json), {
        **dict(job.receipt_json or {}),
        "status": "completed_durable",
        "job_id": job.job_id,
        "case_revision": job.case_revision,
        "authority": str((job.receipt_json or {}).get("authority") or "none"),
    }


def register_interpretation_task_handler() -> None:
    from src.app.workers.task_runner import register_handler

    register_handler(TASK_NAME, execute_case_interpretation_job)


def recover_pending_case_interpretations(*, limit: int = 100) -> int:
    from src.app.models.db import db_session
    from src.app.workers.task_runner import submit_task

    with db_session() as db:
        try:
            stale_after = max(30, min(int(os.getenv(
                "CASE_INTERPRETATION_RUNNING_STALE_SEC", "120",
            )), 3600))
        except (TypeError, ValueError):
            stale_after = 120
        db.execute(update(ShoppingCaseInterpretationJob).where(
            ShoppingCaseInterpretationJob.status == "running",
            ShoppingCaseInterpretationJob.updated_at < _now() - timedelta(seconds=stale_after),
        ).values(
            status="retry", error_code="stale_running_reclaimed", updated_at=_now(),
        ))
        db.commit()
        rows = db.execute(select(ShoppingCaseInterpretationJob).where(
            ShoppingCaseInterpretationJob.status.in_((
                "queued", "retry", "enqueue_degraded",
            )),
        ).order_by(ShoppingCaseInterpretationJob.created_at.asc()).limit(limit)).scalars().all()
        identities = [(row.job_id, row.tenant_id) for row in rows]
    submitted = 0
    for job_id, tenant_id in identities:
        try:
            submit_task(TASK_NAME, {"job_id": job_id, "tenant_id": tenant_id})
            submitted += 1
        except RuntimeError:
            break
    return submitted


__all__ = [
    "consume_completed_case_interpretation", "execute_case_interpretation_job",
    "project_job", "recover_pending_case_interpretations",
    "register_interpretation_task_handler", "schedule_case_interpretation",
]
