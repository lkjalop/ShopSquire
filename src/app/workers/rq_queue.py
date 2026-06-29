from __future__ import annotations

"""Redis RQ background worker queue for CV/Fraud tasks.

- Queues: 'cv', 'fraud', 'dead-letter'
- Bounded queue via soft threshold; overflow goes to dead-letter.
- Graceful fallback when Redis/RQ unavailable.
"""

from typing import Any, Dict, Optional

REDIS_AVAILABLE = False
try:
    import redis  # type: ignore
    from rq import Queue, Worker, Connection  # type: ignore
    REDIS_AVAILABLE = True
except Exception:  # pragma: no cover
    REDIS_AVAILABLE = False

import os
import time
import json
from urllib.parse import urlparse

from src.app.observability.metrics import (
    record_worker_queue_depth,
    record_worker_queue_oldest_age,
)


def _get_redis_connection() -> Optional["redis.Redis"]:
    if not REDIS_AVAILABLE:
        return None
    try:
        url = os.getenv("REDIS_URL") or "redis://localhost:6379/0"
        env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
        non_dev = env not in ("local", "dev", "development", "test", "testing")
        parsed = urlparse(str(url))
        acl_user = str(os.getenv("REDIS_ACL_USERNAME", "") or "").strip()
        acl_pass = str(os.getenv("REDIS_ACL_PASSWORD", "") or "").strip()
        if non_dev:
            if str(parsed.scheme or "").lower() != "rediss":
                return None
            if not acl_user or not acl_pass:
                return None
            return redis.from_url(url, username=acl_user, password=acl_pass,
                                  socket_connect_timeout=0.5, socket_timeout=2.0)  # type: ignore
        return redis.from_url(url, socket_connect_timeout=0.5, socket_timeout=2.0)  # type: ignore
    except Exception:
        return None


def _get_queue(name: str) -> Optional["Queue"]:
    if not REDIS_AVAILABLE:
        return None
    try:
        conn = _get_redis_connection()
        if conn is None:
            return None
        return Queue(name, connection=conn)
    except Exception:
        return None


def _bounded_enqueue(q: "Queue", func, args: tuple, queue_maxsize: int, dead_letter: "Queue") -> Optional[str]:
    _emit_queue_metrics(q)
    _emit_queue_metrics(dead_letter)
    try:
        size = q.count
    except Exception:
        size = 0
    if queue_maxsize > 0 and size >= queue_maxsize:
        # overflow -> dead-letter
        try:
            j = dead_letter.enqueue(func, args=args, job_timeout=os.getenv("RQ_JOB_TIMEOUT", 180))
            _emit_queue_metrics(dead_letter)
            return j.id if j else None
        except Exception:
            return None
    try:
        j = q.enqueue(func, args=args, job_timeout=os.getenv("RQ_JOB_TIMEOUT", 180))
        _emit_queue_metrics(q)
        return j.id if j else None
    except Exception:
        return None


def _emit_queue_metrics(q: Optional["Queue"]) -> None:
    if q is None:
        return
    try:
        stats = _queue_stats(q)
        record_worker_queue_depth(q.name, int(stats.get("depth") or 0))
        record_worker_queue_oldest_age(q.name, float(stats.get("oldest_age_seconds") or 0.0))
    except Exception:
        pass


def _queue_stats(q: "Queue") -> Dict[str, Any]:
    out: Dict[str, Any] = {"queue": q.name, "depth": 0, "oldest_age_seconds": 0.0}
    try:
        out["depth"] = int(q.count or 0)
    except Exception:
        out["depth"] = 0
    if out["depth"] <= 0:
        return out
    try:
        # RQ queue order is oldest at index 0.
        ids = q.get_job_ids(offset=0, length=1)
        if not ids:
            return out
        from rq.job import Job  # type: ignore

        j = Job.fetch(ids[0], connection=q.connection)
        enq = None
        try:
            enq = j.enqueued_at.timestamp() if j.enqueued_at else None
        except Exception:
            enq = None
        if enq is None:
            try:
                meta_ts = j.meta.get("enqueued_ts")
                enq = float(meta_ts) if meta_ts is not None else None
            except Exception:
                enq = None
        if enq is not None:
            out["oldest_age_seconds"] = max(0.0, time.time() - float(enq))
    except Exception:
        out["oldest_age_seconds"] = 0.0
    return out


# ------------------ Job Functions ------------------

def cv_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run CV labels+text and triage; return summary."""
    try:
        from src.app.services.cv_provider import ManagedCVProvider
        from src.app.services.cv_triage_basic import BasicCVTriage
        # run_async_safe instead of raw asyncio.run — robust if this worker fn is ever invoked under an
        # already-running event loop (asyncio.run raises there). Same fix as parallel_agent_executor.
        from src.app.services.async_safe import run_async_safe
        images = payload.get("images") or payload.get("image_b64s") or payload.get("image_data")
        if images:
            img = images[0] if isinstance(images, list) else images
            labels, text, *_ = run_async_safe(ManagedCVProvider().get_labels_and_text(img))
            res = run_async_safe(BasicCVTriage().analyze(labels, text)) or {}
            return {"cv": res, "labels": labels, "text": text}
    except Exception:
        return {"cv": {}}
    return {"cv": {}}


def llm_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Run a best-effort non-streaming LLM generation task."""
    try:
        from src.app.services.llm_provider import OLLAMA_URL
        import httpx

        model = str(payload.get("model") or os.getenv("OLLAMA_SMALL_MODEL", "llama3:8b"))
        prompt = str(payload.get("prompt") or "")
        if not prompt:
            return {"llm": {"error": "empty_prompt"}}
        req = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": payload.get("options") or {"temperature": 0.2, "num_predict": 128},
        }
        with httpx.Client(timeout=float(os.getenv("LLM_JOB_TIMEOUT_SECONDS", "8"))) as client:
            r = client.post(f"{OLLAMA_URL.rstrip('/')}/api/generate", json=req)
            r.raise_for_status()
            data = r.json()
        return {"llm": {"model": model, "response": data.get("response")}}
    except Exception as exc:
        return {"llm": {"error": str(exc)}}


def fraud_job(payload: Dict[str, Any], cv_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Run fraud scorer with enrichment; return summary."""
    try:
        from src.app.services.fraud_scorer import FraudScorer
        fraud = FraudScorer()
        score, level, signals = fraud.score_with_enrichment(
            base_signals={},
            expected_serial=None,
            observed_serial=cv_summary.get("serial_number") if isinstance(cv_summary, dict) else None,
            image_phash=None,
            session_data=payload.get("session") if isinstance(payload, dict) else None,
            case_id=payload.get("case_id") if isinstance(payload, dict) else None,
        )
        return {"fraud": {"score": score, "level": level, "signals": signals}}
    except Exception:
        return {"fraud": {}}


# ------------------ Public API ------------------

def enqueue_cv(payload: Dict[str, Any]) -> Optional[str]:
    if not REDIS_AVAILABLE:
        return None
    q = _get_queue("cv")
    dlq = _get_queue("dead-letter")
    if q is None or dlq is None:
        return None
    maxsize = int(os.getenv("CV_RQ_MAXSIZE", "200") or 200)
    return _bounded_enqueue(q, cv_job, (payload,), maxsize, dlq)


def enqueue_fraud(payload: Dict[str, Any], cv_summary: Dict[str, Any]) -> Optional[str]:
    if not REDIS_AVAILABLE:
        return None
    q = _get_queue("fraud")
    dlq = _get_queue("dead-letter")
    if q is None or dlq is None:
        return None
    maxsize = int(os.getenv("FRAUD_RQ_MAXSIZE", "200") or 200)
    return _bounded_enqueue(q, fraud_job, (payload, cv_summary), maxsize, dlq)


def enqueue_llm(payload: Dict[str, Any]) -> Optional[str]:
    if not REDIS_AVAILABLE:
        return None
    q = _get_queue("llm")
    dlq = _get_queue("dead-letter")
    if q is None or dlq is None:
        return None
    maxsize = int(os.getenv("LLM_RQ_MAXSIZE", "500") or 500)
    return _bounded_enqueue(q, llm_job, (payload,), maxsize, dlq)


def get_queue_stats(queues: Optional[list[str]] = None) -> Dict[str, Any]:
    names = queues or ["cv", "llm", "fraud", "dead-letter"]
    out: Dict[str, Any] = {"queues": {}, "redis_available": bool(REDIS_AVAILABLE)}
    if not REDIS_AVAILABLE:
        for n in names:
            out["queues"][n] = {"queue": n, "depth": 0, "oldest_age_seconds": 0.0}
        return out
    for n in names:
        q = _get_queue(n)
        if q is None:
            out["queues"][n] = {"queue": n, "depth": 0, "oldest_age_seconds": 0.0}
            continue
        st = _queue_stats(q)
        out["queues"][n] = st
        _emit_queue_metrics(q)
    return out


def worker_run(queues: Optional[list[str]] = None) -> int:
    """Start an RQ Worker listening to given queues.

    Returns exit code (0 on success).
    """
    if not REDIS_AVAILABLE:
        return 1
    try:
        conn = _get_redis_connection()
        if conn is None:
            return 1
        names = queues or ["cv", "llm", "fraud", "dead-letter"]
        with Connection(conn):
            w = Worker(names)
            w.work(with_scheduler=True)
        return 0
    except Exception:
        return 1


def get_job_status(job_id: str) -> Dict[str, Any]:
    """Return job status and result snapshot if available.

    Structure: {"id": job_id, "status": "queued|started|finished|failed|unknown", "result": Any}
    """
    out: Dict[str, Any] = {"id": job_id, "status": "unknown"}
    if not REDIS_AVAILABLE:
        return out
    try:
        conn = _get_redis_connection()
        if conn is None:
            return out
        from rq.job import Job  # type: ignore
        job = Job.fetch(job_id, connection=conn)
        out["status"] = job.get_status() or "unknown"
        try:
            out["result"] = job.result
        except Exception:
            pass
        try:
            if isinstance(out.get("result"), dict):
                # Ensure JSON-safe payload for API surfaces.
                json.dumps(out.get("result"))
        except Exception:
            out["result"] = {"raw": str(out.get("result"))}
        try:
            # Refresh queue metrics opportunistically.
            for qn in ("cv", "llm", "fraud", "dead-letter"):
                q = _get_queue(qn)
                _emit_queue_metrics(q)
        except Exception:
            pass
        return out
    except Exception:
        return out
