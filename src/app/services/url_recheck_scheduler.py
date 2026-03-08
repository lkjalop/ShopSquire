from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.phishing_page_detector import run_phishing_page_deep_analysis
from src.app.services.decision_log import log_trace_event

_DEF_STOP_ATTR = "url_recheck_scheduler_stop"
_DEF_THREAD_ATTR = "url_recheck_scheduler_thread"


def _enabled() -> bool:
    return str(os.getenv("URL_RECHECK_WORKER_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")


def _interval_sec() -> float:
    try:
        return max(0.5, float(os.getenv("URL_RECHECK_WORKER_INTERVAL_SEC", "5.0") or 5.0))
    except Exception:
        return 5.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _epoch() -> int:
    return int(time.time())


def _job_id(*, incident_id: str, url: str, stage: str) -> str:
    raw = f"{incident_id}:{url}:{stage}".encode("utf-8")
    return f"urj-{hashlib.sha256(raw).hexdigest()[:24]}"


def _json_load(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def ensure_url_recheck_table() -> None:
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_security_url_recheck_jobs (
                  id TEXT PRIMARY KEY,
                  incident_id TEXT NOT NULL,
                  tenant_id TEXT,
                  decision_id TEXT,
                  url TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  run_at_epoch INTEGER NOT NULL,
                  status TEXT NOT NULL DEFAULT 'pending',
                  attempts INTEGER NOT NULL DEFAULT 0,
                  last_error TEXT,
                  analysis_json TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_email_security_url_recheck_due
                ON email_security_url_recheck_jobs (status, run_at_epoch)
                """
            )
        )
        db.commit()


def schedule_url_rechecks(
    *,
    incident_id: str,
    tenant_id: str | None,
    decision_id: str | None,
    urls: List[str],
    delays_seconds: Dict[str, int] | None = None,
    now_epoch: int | None = None,
) -> Dict[str, Any]:
    ensure_url_recheck_table()
    now = int(now_epoch or _epoch())
    delays = delays_seconds or {"t15m": 15 * 60, "t2h": 2 * 60 * 60}
    clean_urls = []
    seen = set()
    for u in urls or []:
        s = str(u or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        clean_urls.append(s)

    out: Dict[str, Any] = {"ok": True, "incident_id": incident_id, "scheduled": 0, "jobs": []}
    if not clean_urls:
        out["ok"] = False
        out["error"] = "no_urls"
        return out

    with db_session() as db:
        for url in clean_urls[:40]:
            for stage, delay in delays.items():
                run_at = now + max(1, int(delay or 0))
                jid = _job_id(incident_id=incident_id, url=url, stage=stage)
                exists = db.execute(
                    text("SELECT id FROM email_security_url_recheck_jobs WHERE id = :id LIMIT 1"),
                    {"id": jid},
                ).fetchone()
                if exists is not None:
                    continue
                db.execute(
                    text(
                        """
                        INSERT INTO email_security_url_recheck_jobs
                        (id, incident_id, tenant_id, decision_id, url, stage, run_at_epoch, status, attempts, created_at, updated_at)
                        VALUES
                        (:id, :incident_id, :tenant_id, :decision_id, :url, :stage, :run_at_epoch, 'pending', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """
                    ),
                    {
                        "id": jid,
                        "incident_id": incident_id,
                        "tenant_id": tenant_id,
                        "decision_id": decision_id,
                        "url": url,
                        "stage": stage,
                        "run_at_epoch": run_at,
                    },
                )
                out["jobs"].append({"id": jid, "url": url, "stage": stage, "run_at_epoch": run_at})
        db.commit()
    out["scheduled"] = len(out["jobs"])
    return out


def _append_reason(reasons: List[str], reason: str) -> List[str]:
    out = [str(x) for x in (reasons or []) if str(x or "").strip()]
    if reason not in out:
        out.append(reason)
    return out


def _process_due_job(job: Dict[str, Any]) -> Dict[str, Any]:
    jid = str((job or {}).get("id") or "")
    incident_id = str((job or {}).get("incident_id") or "")
    tenant_id = str((job or {}).get("tenant_id") or "").strip() or None
    decision_id = str((job or {}).get("decision_id") or "").strip() or None
    url = str((job or {}).get("url") or "").strip()
    stage = str((job or {}).get("stage") or "").strip() or "scheduled"
    attempts = int((job or {}).get("attempts") or 0)
    if not (jid and incident_id and url):
        return {"ok": False, "error": "invalid_job", "job_id": jid}

    analysis = run_phishing_page_deep_analysis([url])
    escalated = False
    updated = False
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT id, evidence_json, reasons_json, severity, risk_band
                FROM email_security_incidents
                WHERE id = :id AND (:tenant_id IS NULL OR tenant_id = :tenant_id)
                LIMIT 1
                """
            ),
            {"id": incident_id, "tenant_id": tenant_id},
        ).fetchone()
        if row is None:
            db.execute(
                text(
                    """
                    UPDATE email_security_url_recheck_jobs
                    SET status = 'failed',
                        attempts = :attempts,
                        last_error = :last_error,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """
                ),
                {"id": jid, "attempts": attempts + 1, "last_error": "incident_not_found"},
            )
            db.commit()
            return {"ok": False, "error": "incident_not_found", "job_id": jid}

        evidence = _json_load(row[1], {})
        reasons = _json_load(row[2], [])
        severity = str(row[3] or "info")
        risk_band = str(row[4] or "low")
        route = str((evidence or {}).get("route") or "auto_resolve")

        stage_obj = (evidence.get("phishing_page_stage") if isinstance(evidence, dict) else {}) or {}
        scheduled = (stage_obj.get("scheduled_rechecks") if isinstance(stage_obj, dict) else {}) or {}
        scheduled[stage] = {
            "job_id": jid,
            "completed_at": _utc_now_iso(),
            "max_risk_score": float(analysis.get("max_risk_score") or 0.0),
            "malicious": bool(analysis.get("malicious")),
            "findings": list(analysis.get("findings") or [])[:20],
        }
        stage_obj["scheduled_rechecks"] = scheduled
        stage_obj["worker_status"] = "completed"
        stage_obj["deferred_upgrade"] = bool(analysis.get("malicious") or float(analysis.get("max_risk_score") or 0.0) >= 0.85)
        stage_obj["deferred_last_stage"] = stage
        evidence["phishing_page_stage"] = stage_obj

        if bool(analysis.get("malicious")) or float(analysis.get("max_risk_score") or 0.0) >= 0.85:
            severity = "error"
            risk_band = "high"
            route = "security_review"
            reasons = _append_reason(reasons, "phishing_page_scheduled_recheck_malicious")
            escalated = True
        elif float(analysis.get("max_risk_score") or 0.0) >= 0.6:
            if severity == "info":
                severity = "warning"
                risk_band = "medium"
            if route == "auto_resolve":
                route = "human_review"
            reasons = _append_reason(reasons, "phishing_page_scheduled_recheck_review")
        evidence["route"] = route
        evidence["risk_band"] = risk_band

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
                "id": incident_id,
                "evidence_json": json.dumps(evidence, ensure_ascii=False),
                "reasons_json": json.dumps(reasons, ensure_ascii=False),
                "severity": severity,
                "risk_band": risk_band,
            },
        )
        db.execute(
            text(
                """
                UPDATE email_security_url_recheck_jobs
                SET status = 'completed',
                    attempts = :attempts,
                    last_error = NULL,
                    analysis_json = :analysis_json,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :id
                """
            ),
            {
                "id": jid,
                "attempts": attempts + 1,
                "analysis_json": json.dumps(analysis, ensure_ascii=False),
            },
        )
        db.commit()
        updated = True

    trace_id = decision_id or str((evidence or {}).get("trace_id") or (evidence or {}).get("decision_id") or "").strip()
    if trace_id:
        try:
            log_trace_event(
                trace_id=trace_id,
                event_type="phishing_page_scheduled_recheck_completed",
                source_type="agent",
                source_id="Phishing_Recheck_Scheduler",
                target_type="email",
                target_id=incident_id,
                payload={
                    "job_id": jid,
                    "stage": stage,
                    "url": url[:240],
                    "malicious": bool(analysis.get("malicious")),
                    "max_risk_score": float(analysis.get("max_risk_score") or 0.0),
                    "findings": list(analysis.get("findings") or [])[:20],
                    "escalated": escalated,
                },
            )
        except Exception:
            pass

    return {"ok": True, "job_id": jid, "incident_id": incident_id, "updated": updated, "escalated": escalated, "analysis": analysis}


def run_scheduled_url_rechecks_cycle(*, max_jobs: int = 50, now_epoch: int | None = None) -> Dict[str, Any]:
    ensure_url_recheck_table()
    now = int(now_epoch or _epoch())
    processed = 0
    escalated = 0
    errors = 0
    details: List[Dict[str, Any]] = []
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id, incident_id, tenant_id, decision_id, url, stage, attempts
                FROM email_security_url_recheck_jobs
                WHERE status = 'pending'
                  AND run_at_epoch <= :now_epoch
                ORDER BY run_at_epoch ASC
                LIMIT :limit
                """
            ),
            {"now_epoch": now, "limit": max(1, int(max_jobs or 50))},
        ).fetchall()
    for r in rows or []:
        job = {
            "id": r[0],
            "incident_id": r[1],
            "tenant_id": r[2],
            "decision_id": r[3],
            "url": r[4],
            "stage": r[5],
            "attempts": int(r[6] or 0),
        }
        out = _process_due_job(job)
        processed += 1
        if out.get("ok"):
            if out.get("escalated"):
                escalated += 1
        else:
            errors += 1
        details.append({"job_id": job["id"], "ok": bool(out.get("ok")), "error": out.get("error"), "escalated": bool(out.get("escalated"))})
    return {"status": "ok", "processed": processed, "escalated": escalated, "errors": errors, "details": details}


def get_url_recheck_dashboard(*, hours: int = 24, limit: int = 20) -> Dict[str, Any]:
    ensure_url_recheck_table()
    horizon = int(_epoch() - (max(1, int(hours or 24)) * 3600))
    out: Dict[str, Any] = {
        "window_hours": int(hours or 24),
        "totals": {"pending": 0, "completed": 0, "failed": 0},
        "next_due_epoch": None,
        "latest": [],
    }
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT status, COUNT(*) AS c
                FROM email_security_url_recheck_jobs
                WHERE run_at_epoch >= :horizon
                GROUP BY status
                """
            ),
            {"horizon": horizon},
        ).fetchall()
        for r in rows or []:
            st = str(r[0] or "pending")
            out["totals"][st] = int(r[1] or 0)
        next_due = db.execute(
            text(
                """
                SELECT MIN(run_at_epoch)
                FROM email_security_url_recheck_jobs
                WHERE status = 'pending'
                """
            )
        ).scalar()
        out["next_due_epoch"] = int(next_due) if next_due else None
        latest = db.execute(
            text(
                """
                SELECT id, incident_id, tenant_id, stage, status, run_at_epoch, attempts, updated_at
                FROM email_security_url_recheck_jobs
                ORDER BY run_at_epoch DESC
                LIMIT :limit
                """
            ),
            {"limit": max(1, int(limit or 20))},
        ).fetchall()
    out["latest"] = [
        {
            "id": str(r[0]),
            "incident_id": str(r[1]),
            "tenant_id": (str(r[2]) if r[2] is not None else None),
            "stage": str(r[3] or ""),
            "status": str(r[4] or ""),
            "run_at_epoch": int(r[5] or 0),
            "attempts": int(r[6] or 0),
            "updated_at": (str(r[7]) if r[7] is not None else None),
        }
        for r in (latest or [])
    ]
    return out


def replay_failed_url_rechecks(*, limit: int = 50, dry_run: bool = False) -> Dict[str, Any]:
    ensure_url_recheck_table()
    out: Dict[str, Any] = {"requested_limit": int(limit or 50), "dry_run": bool(dry_run), "replayed": 0, "items": []}
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT id
                FROM email_security_url_recheck_jobs
                WHERE status = 'failed'
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": max(1, int(limit or 50))},
        ).fetchall()
        for r in rows or []:
            jid = str(r[0])
            if not dry_run:
                db.execute(
                    text(
                        """
                        UPDATE email_security_url_recheck_jobs
                        SET status = 'pending',
                            last_error = NULL,
                            run_at_epoch = :run_at_epoch,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                        """
                    ),
                    {"id": jid, "run_at_epoch": _epoch()},
                )
            out["replayed"] += 1
            out["items"].append({"id": jid, "status": ("pending" if not dry_run else "failed")})
        if not dry_run:
            db.commit()
    return out


def start_url_recheck_scheduler(app=None):
    if not _enabled():
        return None
    stop_event = threading.Event()

    def _loop():
        while not stop_event.is_set():
            try:
                run_scheduled_url_rechecks_cycle(max_jobs=20)
            except Exception:
                pass
            stop_event.wait(timeout=_interval_sec())

    th = threading.Thread(target=_loop, daemon=True, name="url-recheck-scheduler")
    th.start()
    try:
        if app is not None and hasattr(app, "state"):
            setattr(app.state, _DEF_STOP_ATTR, stop_event)
            setattr(app.state, _DEF_THREAD_ATTR, th)
    except Exception:
        pass
    return th


def stop_url_recheck_scheduler(app=None):
    try:
        ev = getattr(app.state, _DEF_STOP_ATTR, None) if app is not None else None
        th = getattr(app.state, _DEF_THREAD_ATTR, None) if app is not None else None
        if ev is not None:
            ev.set()
        if th is not None and th.is_alive():
            th.join(timeout=2.0)
    except Exception:
        pass
