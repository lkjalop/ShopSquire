"""Sandbox detonation queue service.

Enqueues detonation jobs for c2_beacon and lolbin_command_sequence hypotheses
detected in image payloads.  Jobs are processed by the Celery worker pool.

Queue entry shape:
    {
        "hypothesis": "c2_beacon" | "lolbin_command_sequence",
        "trace_id": str | None,
        "tenant_id": str | None,
        "decoded_content": str | None,   # extracted LSB payload text
        "urls": list[str],               # URLs decoded from QR or payload
        "attachment_hashes": list[str],  # SHA-256 hashes of suspicious bytes
        "steg_score": float,
        "source": "image_scan" | "email_scan",
        "queued_at": ISO-8601 timestamp,
    }

The Celery task calls runtime_confirmation.confirm_runtime_evidence() and
stores results back to the incident record.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

_AUTO_QUEUE_HYPOTHESES = frozenset({"c2_beacon", "lolbin_command_sequence", "ransomware", "fileless_attack"})

# Redis stream / Celery task name for sandbox jobs
_SANDBOX_TASK_NAME = "sandbox.detonate"
_SANDBOX_STREAM_KEY = "sandbox:detonation:queue"


def should_auto_queue(hypothesis: str) -> bool:
    """Return True if this hypothesis warrants automatic sandbox detonation."""
    return str(hypothesis or "").strip().lower() in _AUTO_QUEUE_HYPOTHESES


def queue_sandbox_detonation(
    *,
    hypothesis: str,
    trace_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    decoded_content: Optional[str] = None,
    urls: Optional[List[str]] = None,
    attachment_hashes: Optional[List[str]] = None,
    steg_score: float = 0.0,
    source: str = "image_scan",
) -> Dict[str, Any]:
    """Queue a sandbox detonation job for the given hypothesis.

    Returns a dict describing what was queued (or the skip reason if not queued).
    Non-blocking — all errors are logged and swallowed so detection is never
    blocked by queue unavailability.
    """
    if not should_auto_queue(hypothesis):
        return {"queued": False, "reason": "hypothesis_not_in_auto_queue_list", "hypothesis": hypothesis}

    job: Dict[str, Any] = {
        "hypothesis": str(hypothesis),
        "trace_id": str(trace_id or "") or None,
        "tenant_id": str(tenant_id or "") or None,
        "decoded_content": str(decoded_content or "")[:500] if decoded_content else None,
        "urls": [str(u) for u in (urls or []) if str(u).strip()][:10],
        "attachment_hashes": [str(h) for h in (attachment_hashes or []) if str(h).strip()][:20],
        "steg_score": round(float(steg_score or 0.0), 4),
        "source": source,
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }

    # Path 1: Celery (preferred — async worker pool)
    try:
        from src.app.workers.celery_app import celery_app

        celery_app.send_task(
            _SANDBOX_TASK_NAME,
            kwargs={"job": job},
            queue="security",
        )
        _log.info("sandbox_queue: celery job queued hypothesis=%s trace=%s", hypothesis, trace_id)
        return {"queued": True, "path": "celery", "hypothesis": hypothesis, "trace_id": trace_id}
    except Exception as _celery_exc:
        _log.debug("sandbox_queue: celery unavailable, trying task_runner: %s", _celery_exc)

    # Path 2: Redis Streams task runner (fallback)
    try:
        from src.app.workers.task_runner import submit_task

        submit_task(_SANDBOX_TASK_NAME, job)
        _log.info("sandbox_queue: task_runner job queued hypothesis=%s trace=%s", hypothesis, trace_id)
        return {"queued": True, "path": "task_runner", "hypothesis": hypothesis, "trace_id": trace_id}
    except Exception as _tr_exc:
        _log.debug("sandbox_queue: task_runner unavailable, trying redis direct: %s", _tr_exc)

    # Path 3: Redis direct XADD (best-effort persistence)
    try:
        import redis as _redis

        _redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _r = _redis.from_url(_redis_url, socket_timeout=2.0)
        _r.xadd(_SANDBOX_STREAM_KEY, {"data": json.dumps(job, ensure_ascii=False, default=str)}, maxlen=5000)
        _log.info("sandbox_queue: redis stream entry added hypothesis=%s trace=%s", hypothesis, trace_id)
        return {"queued": True, "path": "redis_stream", "hypothesis": hypothesis, "trace_id": trace_id}
    except Exception as _redis_exc:
        _log.warning("sandbox_queue: all queue paths failed for hypothesis=%s: %s", hypothesis, _redis_exc)

    return {"queued": False, "reason": "all_queue_paths_failed", "hypothesis": hypothesis}


def process_sandbox_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a sandbox detonation job synchronously.

    Called by the Celery worker when processing a `sandbox.detonate` task.
    Returns the runtime confirmation result dict.
    """
    hypothesis = str(job.get("hypothesis") or "").strip().lower()
    trace_id = str(job.get("trace_id") or "") or None
    tenant_id = str(job.get("tenant_id") or "") or None
    urls = list(job.get("urls") or [])
    attachment_hashes = list(job.get("attachment_hashes") or [])
    decoded_content = str(job.get("decoded_content") or "")

    _log.info("sandbox_queue: processing job hypothesis=%s trace=%s urls=%d", hypothesis, trace_id, len(urls))

    context: Dict[str, Any] = {
        "trace_id": trace_id,
        "tenant_id": tenant_id or "default",
        "urls": urls,
        "attachment_hashes": attachment_hashes,
        "source": job.get("source", "image_scan"),
        "steg_score": job.get("steg_score", 0.0),
    }
    if decoded_content:
        context["decoded_payload_text"] = decoded_content

    result: Dict[str, Any] = {"hypothesis": hypothesis, "trace_id": trace_id}
    try:
        from src.app.security.runtime_confirmation import confirm_runtime_evidence

        runtime_result = confirm_runtime_evidence(
            attack_hypothesis=hypothesis,
            context=context,
        )
        result["runtime_result"] = runtime_result
        result["supported"] = bool((runtime_result or {}).get("supported"))
        result["status"] = "completed"
    except Exception as exc:
        _log.warning("sandbox_queue: confirm_runtime_evidence failed: %s", exc)
        result["status"] = "failed"
        result["error"] = str(exc)[:200]

    # Persist result to incident / trace
    try:
        from src.app.services.decision_log import log_trace_event

        log_trace_event(
            trace_id=trace_id,
            event_type="sandbox_detonation_result",
            source_type="security",
            source_id="SandboxDetonationWorker",
            target_type="system",
            target_id=None,
            payload={
                "hypothesis": hypothesis,
                "status": result.get("status"),
                "supported": result.get("supported"),
                "runtime_result_summary": str((result.get("runtime_result") or {}).get("summary") or "")[:200],
            },
        )
    except Exception:
        pass

    return result
