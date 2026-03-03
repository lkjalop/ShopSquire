from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.deps import get_redis
from src.app.models.db import db_session
from src.app.security.phishing_page_detector import run_phishing_page_deep_analysis
from src.app.services.decision_log import log_trace_event


_DEF_STOP_ATTR = "phishing_page_worker_stop"
_DEF_THREAD_ATTR = "phishing_page_worker_thread"


def _enabled() -> bool:
    return str(os.getenv("PHISHING_PAGE_WORKER_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(0.2, float(os.getenv("PHISHING_PAGE_WORKER_INTERVAL_SEC", "1.0") or 1.0))
    except Exception:
        return 1.0


def _queue_name() -> str:
    return str(os.getenv("PHISHING_PAGE_QUEUE_NAME", "email_security:phishing_page_jobs") or "email_security:phishing_page_jobs").strip()


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_reason(reasons: List[str], reason: str) -> List[str]:
    out = [str(x) for x in (reasons or []) if str(x or "").strip()]
    if reason not in out:
        out.append(reason)
    return out


def process_phishing_page_job(job: Dict[str, Any]) -> Dict[str, Any]:
    job_id = str((job or {}).get("job_id") or "").strip()
    tenant_id = str((job or {}).get("tenant_id") or "").strip() or None
    urls = [str(x or "").strip() for x in ((job or {}).get("urls") or []) if str(x or "").strip()]
    if not job_id:
        return {"ok": False, "error": "job_id_required"}
    if not urls:
        return {"ok": False, "error": "urls_required", "job_id": job_id}

    analysis = run_phishing_page_deep_analysis(urls)
    rows = []
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, evidence_json, reasons_json, severity, risk_band
                    FROM email_security_incidents
                    WHERE evidence_json LIKE :needle
                      AND (:tenant_id IS NULL OR tenant_id = :tenant_id)
                    ORDER BY created_at DESC
                    LIMIT 200
                    """
                ),
                {"needle": f"%{job_id}%", "tenant_id": tenant_id},
            ).fetchall()
    except Exception:
        rows = []

    escalated = 0
    updated = 0
    for r in rows or []:
        inc_id = str(r[0])
        evidence = _json_load(r[1], {})
        reasons = _json_load(r[2], [])
        severity = str(r[3] or "info")
        risk_band = str(r[4] or "low")
        stage = (evidence.get("phishing_page_stage") if isinstance(evidence, dict) else {}) or {}

        stage["worker_status"] = "completed"
        stage["completed_at"] = _utc_now_iso()
        stage["final"] = analysis
        stage["detected"] = bool(analysis.get("malicious") or float(analysis.get("max_risk_score") or 0.0) >= 0.6)
        evidence["phishing_page_stage"] = stage

        route = str((evidence or {}).get("route") or "auto_resolve")
        if bool(analysis.get("malicious")) or float(analysis.get("max_risk_score") or 0.0) >= 0.85:
            severity = "error"
            risk_band = "high"
            route = "security_review"
            reasons = _append_reason(reasons, "phishing_page_async_malicious")
            escalated += 1
        elif float(analysis.get("max_risk_score") or 0.0) >= 0.6:
            if severity == "info":
                severity = "warning"
                risk_band = "medium"
            if route == "auto_resolve":
                route = "human_review"
            reasons = _append_reason(reasons, "phishing_page_async_review")
        evidence["route"] = route
        evidence["risk_band"] = risk_band

        try:
            with db_session() as db:
                db.execute(
                    text(
                        """
                        UPDATE email_security_incidents
                        SET evidence_json = :evidence_json,
                            reasons_json = :reasons_json,
                            severity = :severity,
                            risk_band = :risk_band
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": inc_id,
                        "evidence_json": json.dumps(evidence, ensure_ascii=False),
                        "reasons_json": json.dumps(reasons, ensure_ascii=False),
                        "severity": severity,
                        "risk_band": risk_band,
                    },
                )
                db.commit()
            updated += 1
        except Exception:
            continue

        trace_id = str((evidence or {}).get("trace_id") or (evidence or {}).get("decision_id") or "").strip()
        if trace_id:
            try:
                log_trace_event(
                    trace_id=trace_id,
                    event_type="phishing_page_analysis_completed",
                    source_type="agent",
                    source_id="Phishing_Page_Worker",
                    target_type="email",
                    target_id=inc_id,
                    payload={
                        "job_id": job_id,
                        "malicious": bool(analysis.get("malicious")),
                        "max_risk_score": float(analysis.get("max_risk_score") or 0.0),
                        "findings": analysis.get("findings") or [],
                        "route": route,
                        "severity": severity,
                    },
                )
            except Exception:
                pass

    return {
        "ok": True,
        "job_id": job_id,
        "matched_incidents": len(rows or []),
        "updated_incidents": updated,
        "escalated_incidents": escalated,
        "analysis": analysis,
    }


def run_phishing_page_jobs_cycle(*, max_jobs: int = 50) -> Dict[str, Any]:
    r = get_redis()
    if r.__class__.__name__ == "DummyRedis":
        return {"status": "redis_unavailable", "processed": 0, "errors": 0}
    queue = _queue_name()
    processed = 0
    errors = 0
    while processed < max(1, int(max_jobs or 50)):
        raw = None
        try:
            raw = r.rpop(queue)
        except Exception:
            raw = None
        if not raw:
            break
        try:
            job = json.loads(raw) if isinstance(raw, str) else {}
        except Exception:
            job = {}
        out = process_phishing_page_job(job)
        if not out.get("ok"):
            errors += 1
            try:
                r.lpush(f"{queue}:dlq", json.dumps({"raw": raw, "error": out.get("error")}, ensure_ascii=False))
            except Exception:
                pass
        processed += 1
    return {"status": "ok", "processed": processed, "errors": errors}


def start_phishing_page_worker(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                run_phishing_page_jobs_cycle(max_jobs=20)
            except Exception:
                pass
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="phishing-page-worker")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            setattr(app.state, _DEF_STOP_ATTR, stop_event)
            setattr(app.state, _DEF_THREAD_ATTR, th)
    except Exception:
        pass
    return th


def stop_phishing_page_worker(app=None):
    try:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass

