"""Durable return evidence processing with independent killable lanes."""
from __future__ import annotations

import base64
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.media_process_isolation import run_isolated_media_call
from src.app.services.return_claims import load_encrypted_artifact, transition_claim
from src.app.workers.celery_app import celery_app


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lane(function_name: str, payload: dict, timeout_s: float):
    return run_isolated_media_call(
        module_name="src.app.services.return_artifact_analysis",
        function_name=function_name,
        kwargs=payload,
        timeout_s=timeout_s,
    )


@celery_app.task(
    name="src.app.tasks.return_evidence_tasks.process_return_evidence",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def process_return_evidence(self, tenant_id: str, job_id: str) -> dict:
    from src.app.observability.return_metrics import RETURN_EVIDENCE_OUTSTANDING

    RETURN_EVIDENCE_OUTSTANDING.labels(tenant_id=tenant_id).inc()
    try:
        try:
            return _process_return_evidence(tenant_id=tenant_id, job_id=job_id)
        except RuntimeError as exc:
            # Retriable custody/source failures must be durable and visible before
            # Celery schedules another attempt.
            with db_session() as db:
                db.execute(
                    text(
                        "UPDATE return_evidence_job SET status='queued',last_error=:error "
                        "WHERE id=:job AND tenant_id=:tenant"
                    ),
                    {"error": str(exc)[:500], "job": job_id, "tenant": tenant_id},
                )
                db.commit()
            raise
        except Exception as exc:
            with db_session() as db:
                db.execute(
                    text(
                        "UPDATE return_evidence_job SET status='failed',finished_at=:now,last_error=:error "
                        "WHERE id=:job AND tenant_id=:tenant"
                    ),
                    {
                        "now": _now(), "error": f"{type(exc).__name__}:{str(exc)[:450]}",
                        "job": job_id, "tenant": tenant_id,
                    },
                )
                db.commit()
            logger.exception("return evidence job failed tenant=%s job=%s", tenant_id, job_id)
            return {"status": "failed", "job_id": job_id}
    finally:
        RETURN_EVIDENCE_OUTSTANDING.labels(tenant_id=tenant_id).dec()


def _process_return_evidence(*, tenant_id: str, job_id: str) -> dict:
    with db_session() as db:
        job = db.execute(
            text(
                "SELECT claim_id,status FROM return_evidence_job "
                "WHERE id=:job AND tenant_id=:tenant"
            ),
            {"job": job_id, "tenant": tenant_id},
        ).fetchone()
        if not job:
            return {"status": "not_found"}
        if str(job[1]) in {"completed", "quarantined"}:
            return {"status": str(job[1]), "idempotent": True}
        claim_id = str(job[0])
        db.execute(
            text(
                "UPDATE return_evidence_job SET status='running',attempts=attempts+1,started_at=:now "
                "WHERE id=:job AND tenant_id=:tenant"
            ),
            {"now": _now(), "job": job_id, "tenant": tenant_id},
        )
        objects = db.execute(
            text(
                "SELECT id,original_name_sanitized,media_type FROM return_evidence_object "
                "WHERE claim_id=:claim AND tenant_id=:tenant ORDER BY created_at"
            ),
            {"claim": claim_id, "tenant": tenant_id},
        ).fetchall()
        db.commit()

    security_blocked = False
    degraded = False
    observations: list[tuple[str, str, dict]] = []
    for evidence_id, filename, media_type in objects:
        with db_session() as db:
            raw = load_encrypted_artifact(
                db, tenant_id=tenant_id, claim_id=claim_id, evidence_id=str(evidence_id),
                actor_id="return-evidence-worker", purpose="bounded_security_and_visual_analysis",
            )
            db.commit()
        payload = {
            "content_b64": base64.b64encode(raw).decode("ascii"),
            "filename": str(filename), "content_type": str(media_type or "application/octet-stream"),
        }
        # Each lane owns a disposable process. A timeout kills only that lane;
        # no OCR/parser native state survives into the API or Celery process.
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="return-artifact-lanes") as pool:
            security_future = pool.submit(_lane, "inspect_security", payload, 4.0)
            visual_future = pool.submit(_lane, "inspect_visual", payload, 7.0)
            security = security_future.result()
            visual = visual_future.result()
        try:
            from src.app.observability.return_metrics import RETURN_EVIDENCE_LANE_SECONDS

            RETURN_EVIDENCE_LANE_SECONDS.labels(lane="security", status=security.status).observe(
                security.elapsed_ms / 1000.0
            )
            RETURN_EVIDENCE_LANE_SECONDS.labels(lane="visual", status=visual.status).observe(
                visual.elapsed_ms / 1000.0
            )
        except Exception as exc:
            logger.debug("return evidence metric emission failed: %s", exc)
        security_value = security.value if security.status == "completed" else {
            "status": security.status, "blocked": True, "reasons": [security.error or "security_lane_failed"]
        }
        visual_value = visual.value if visual.status == "completed" else {
            "status": visual.status, "degradation_reason": visual.error or "visual_lane_failed"
        }
        security_blocked = security_blocked or bool(security_value.get("blocked"))
        degraded = degraded or security.status != "completed" or visual.status != "completed" or (
            str(visual_value.get("status")) == "degraded"
        )
        observations.extend([
            (str(evidence_id), "security_verdict", security_value),
            (str(evidence_id), "visual_ocr", visual_value),
        ])

    final = "quarantined" if security_blocked else "degraded" if degraded else "completed"
    with db_session() as db:
        for evidence_id, kind, value in observations:
            db.execute(
                text(
                    "INSERT INTO return_evidence_observation "
                    "(id,tenant_id,claim_id,evidence_id,observation_type,sanitized_json,confidence,"
                    "authority,observed_at,created_at) VALUES "
                    "(:id,:tenant,:claim,:evidence,:kind,:payload,:confidence,'observation_only',:observed,:created)"
                ),
                {
                    "id": str(uuid.uuid4()), "tenant": tenant_id, "claim": claim_id,
                    "evidence": evidence_id, "kind": kind,
                    "payload": json.dumps(value, sort_keys=True, default=str),
                    "confidence": value.get("confidence"), "observed": _now(), "created": _now(),
                },
            )
        db.execute(
            text(
                "UPDATE return_evidence_job SET status=:status,security_status=:security,"
                "visual_status=:visual,finished_at=:now,last_error=:error "
                "WHERE id=:job AND tenant_id=:tenant"
            ),
            {
                "status": final,
                "security": "quarantined" if security_blocked else "completed",
                "visual": "degraded" if degraded else "completed",
                "now": _now(), "error": None if final == "completed" else final,
                "job": job_id, "tenant": tenant_id,
            },
        )
        if final == "completed":
            claim = db.execute(
                text("SELECT status FROM return_claim WHERE id=:claim AND tenant_id=:tenant"),
                {"claim": claim_id, "tenant": tenant_id},
            ).fetchone()
            if claim and str(claim[0]) == "evidence_pending":
                transition_claim(
                    db, tenant_id=tenant_id, claim_id=claim_id, to_status="under_review",
                    actor_type="system", actor_id="return-evidence-worker",
                    metadata={"evidence_job_id": job_id, "security_status": "completed"},
                )
        db.commit()
    return {"status": final, "claim_id": claim_id, "observation_count": len(observations)}


@celery_app.task(name="src.app.tasks.return_evidence_tasks.dispatch_return_evidence_jobs")
def dispatch_return_evidence_jobs(limit: int = 25) -> dict:
    with db_session() as db:
        rows = db.execute(
            text(
                "SELECT id,tenant_id FROM return_evidence_job WHERE status='queued' "
                "ORDER BY created_at LIMIT :limit"
            ),
            {"limit": max(1, min(int(limit), 100))},
        ).fetchall()
    for job_id, tenant_id in rows:
        process_return_evidence.delay(str(tenant_id), str(job_id))
    return {"dispatched": len(rows)}
