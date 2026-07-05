from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.decision_log import log_trace_event


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _entropy(s: str) -> float:
    s = str(s or "")
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = float(len(s))
    ent = 0.0
    for c in freq.values():
        p = float(c) / n
        ent -= p * math.log2(p)
    return float(ent)


def _ensure_tables() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS outbound_email_events (
                      id TEXT PRIMARY KEY,
                      tenant_id TEXT,
                      agent_id TEXT,
                      to_hash TEXT,
                      to_domain_hash TEXT,
                      thread_id_hash TEXT,
                      subject_entropy REAL,
                      body_entropy REAL,
                      subject_len INTEGER,
                      body_len INTEGER,
                      created_at INTEGER NOT NULL,
                      meta_json TEXT
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS outbound_email_anomalies (
                      id TEXT PRIMARY KEY,
                      event_id TEXT NOT NULL,
                      tenant_id TEXT,
                      agent_id TEXT,
                      severity TEXT NOT NULL,
                      reasons_json TEXT NOT NULL,
                      score REAL,
                      created_at INTEGER NOT NULL
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def scan_outbound_content_dlp(subject: str, body: str) -> Dict[str, Any]:
    """Content DLP on OUTBOUND mail: scan subject+body for SECRETS (credentials/keys/tokens) and
    PII using the shared dlp_export patterns. The outbound monitor was behavioral-only (entropy,
    timing) — it never looked at content, so PII/secrets could leave undetected.

    A secret leaving is unambiguous → action='block'. PII is a softer flag → action='review'
    (a lot of legitimate mail carries a name/phone). Returns
    {secret_hits, pii_hits, action, categories}. Never raises."""
    try:
        from src.app.security.dlp_export import dlp_scrub_pii, dlp_scrub_text
        blob = f"{subject or ''}\n{body or ''}"
        _, secret_hits = dlp_scrub_text(blob)
        _, pii_hits = dlp_scrub_pii(blob)
    except Exception:
        return {"secret_hits": 0, "pii_hits": 0, "action": "allow", "categories": []}
    categories: List[str] = []
    if secret_hits:
        categories.append("secret")
    if pii_hits:
        categories.append("pii")
    action = "block" if secret_hits > 0 else ("review" if pii_hits > 0 else "allow")
    return {"secret_hits": int(secret_hits), "pii_hits": int(pii_hits), "action": action, "categories": categories}


def record_outbound_email_event(
    *,
    tenant_id: str | None,
    agent_id: str,
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    decision_id: str | None = None,
    meta: Optional[Dict[str, Any]] = None,
    now_ts: int | None = None,
) -> Dict[str, Any]:
    _ensure_tables()
    now = int(now_ts) if now_ts is not None else int(time.time())
    ev_id = f"oev-{uuid.uuid4().hex}"
    to_s = str(to or "")
    dom = None
    try:
        dom = to_s.split("@", 1)[1].lower().strip() if "@" in to_s else None
    except Exception:
        dom = None
    subj = str(subject or "")
    bod = str(body or "")
    # Content DLP scan — fold the finding into the event meta so it persists + surfaces on the trace.
    dlp = scan_outbound_content_dlp(subj, bod)
    _meta = dict(meta or {})
    if dlp.get("action") != "allow":
        _meta["dlp_content"] = dlp
    row = {
        "id": ev_id,
        "tenant_id": tenant_id,
        "agent_id": str(agent_id or "unknown"),
        "to_hash": _hash16(to_s),
        "to_domain_hash": _hash16(dom) if dom else None,
        "thread_id_hash": _hash16(thread_id) if thread_id else None,
        "subject_entropy": float(_entropy(subj[:256])),
        "body_entropy": float(_entropy(bod[:1024])),
        "subject_len": int(len(subj)),
        "body_len": int(len(bod)),
        "created_at": now,
        "meta_json": json.dumps(_meta, ensure_ascii=False),
    }
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO outbound_email_events
                    (id, tenant_id, agent_id, to_hash, to_domain_hash, thread_id_hash,
                     subject_entropy, body_entropy, subject_len, body_len, created_at, meta_json)
                    VALUES
                    (:id, :tenant_id, :agent_id, :to_hash, :to_domain_hash, :thread_id_hash,
                     :subject_entropy, :body_entropy, :subject_len, :body_len, :created_at, :meta_json)
                    """
                ),
                row,
            )
            db.commit()
    except Exception:
        pass
    try:
        if decision_id:
            log_trace_event(
                trace_id=decision_id,
                event_type="outbound_email_observed",
                source_type="agent",
                source_id="Outbound_Comms_Monitor",
                target_type="email",
                target_id=ev_id,
                payload={
                    "agent_id": row["agent_id"],
                    "to_domain_hash": row["to_domain_hash"],
                    "subject_entropy": row["subject_entropy"],
                    "body_entropy": row["body_entropy"],
                    "thread_id_hash": row["thread_id_hash"],
                },
            )
    except Exception:
        pass
    return {"id": ev_id, "dlp": dlp,
            **{k: row[k] for k in ("tenant_id", "agent_id", "to_domain_hash", "thread_id_hash", "subject_entropy", "body_entropy", "created_at")}}


def _recent_events(*, agent_id: str, minutes: int = 60, now_ts: int | None = None) -> List[Dict[str, Any]]:
    _ensure_tables()
    now = int(now_ts) if now_ts is not None else int(time.time())
    since = now - int(max(1, minutes)) * 60
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, created_at, subject_entropy, body_entropy, thread_id_hash, to_domain_hash
                    FROM outbound_email_events
                    WHERE agent_id = :agent_id AND created_at >= :since
                    ORDER BY created_at ASC
                    """
                ),
                {"agent_id": str(agent_id), "since": since},
            ).fetchall()
        out = []
        for r in rows or []:
            out.append(
                {
                    "id": r[0],
                    "created_at": int(r[1] or 0),
                    "subject_entropy": float(r[2] or 0.0),
                    "body_entropy": float(r[3] or 0.0),
                    "thread_id_hash": r[4],
                    "to_domain_hash": r[5],
                }
            )
        return out
    except Exception:
        return []


def analyze_agent_outbound_email(
    *,
    agent_id: str,
    minutes: int = 60,
    entropy_subject_threshold: float = 4.0,
    periodic_min_events: int = 6,
    periodic_cv_threshold: float = 0.15,
    now_ts: int | None = None,
) -> Dict[str, Any]:
    events = _recent_events(agent_id=agent_id, minutes=minutes, now_ts=now_ts)
    reasons: List[str] = []
    score = 0.0

    if not events:
        return {"agent_id": agent_id, "minutes": minutes, "anomalous": False, "score": 0.0, "reasons": [], "events": 0}

    # Entropy outliers: subjects that look encoded.
    max_subj_ent = max(float(e.get("subject_entropy") or 0.0) for e in events)
    if max_subj_ent >= float(entropy_subject_threshold):
        reasons.append("high_entropy_subject")
        score += 0.45

    # Periodicity: look at inter-arrival coefficient of variation.
    ts = [int(e.get("created_at") or 0) for e in events]
    deltas = [ts[i] - ts[i - 1] for i in range(1, len(ts)) if ts[i] > 0 and ts[i - 1] > 0]
    if len(deltas) >= max(2, periodic_min_events - 1):
        mean = sum(deltas) / float(len(deltas))
        if mean > 0:
            var = sum((d - mean) ** 2 for d in deltas) / float(len(deltas))
            std = math.sqrt(max(0.0, var))
            cv = std / mean if mean > 0 else 0.0
            if cv <= float(periodic_cv_threshold):
                reasons.append("periodic_beacon_like_timing")
                score += 0.55

        # Destination drift: many distinct domains in short window
        try:
            uniq_domains = len({e.get("to_domain_hash") for e in events if e.get("to_domain_hash")})
            if uniq_domains >= 3:
                reasons.append("destination_drift")
                score += 0.3
        except Exception:
            pass

    # Thread coherence: frequent thread_id changes within short window indicate automation vs conversation.
    try:
        thread_ids = [e.get("thread_id_hash") for e in events if e.get("thread_id_hash")]
        uniq_threads = len(set([t for t in thread_ids if t]))
        if uniq_threads >= 4:
            ratio = float(uniq_threads) / float(max(1, len(events)))
            if ratio >= 0.6:
                reasons.append("thread_coherence_low")
                score += 0.25
    except Exception:
        pass

    anomalous = bool(reasons) and score >= 0.6
    return {
        "agent_id": agent_id,
        "minutes": minutes,
        "anomalous": anomalous,
        "score": round(float(score), 4),
        "reasons": reasons,
        "events": len(events),
        "max_subject_entropy": round(float(max_subj_ent), 4),
    }


def store_outbound_anomaly(
    *,
    tenant_id: str | None,
    agent_id: str,
    event_id: str,
    analysis: Dict[str, Any],
    severity: str = "high",
    now_ts: int | None = None,
    decision_id: str | None = None,
) -> Optional[str]:
    _ensure_tables()
    if not analysis.get("anomalous"):
        return None
    now = int(now_ts) if now_ts is not None else int(time.time())
    an_id = f"oan-{uuid.uuid4().hex}"
    reasons = analysis.get("reasons") if isinstance(analysis.get("reasons"), list) else []
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO outbound_email_anomalies
                    (id, event_id, tenant_id, agent_id, severity, reasons_json, score, created_at)
                    VALUES
                    (:id, :event_id, :tenant_id, :agent_id, :severity, :reasons_json, :score, :created_at)
                    """
                ),
                {
                    "id": an_id,
                    "event_id": event_id,
                    "tenant_id": tenant_id,
                    "agent_id": agent_id,
                    "severity": severity,
                    "reasons_json": json.dumps(reasons, ensure_ascii=False),
                    "score": float(analysis.get("score") or 0.0),
                    "created_at": now,
                },
            )
            db.commit()
    except Exception:
        return None
    # Emit trace events best-effort for anomaly containment and visibility.
    try:
        if decision_id:
            try:
                log_trace_event(
                    trace_id=decision_id,
                    event_type="outbound_email_anomaly_detected",
                    source_type="agent",
                    source_id="Outbound_Comms_Monitor",
                    target_type="email",
                    target_id=event_id,
                    payload={
                        "anomaly_id": an_id,
                        "severity": severity,
                        "reasons": reasons,
                        "score": float(analysis.get("score") or 0.0),
                    },
                )
            except Exception:
                pass
            try:
                contain_env = str(__import__("os").getenv("OUTBOUND_CONTAIN_ON_ANOMALY", "0")).strip().lower() in ("1", "true", "yes")
            except Exception:
                contain_env = False
            try:
                if contain_env and (severity in ("high", "critical") or float(analysis.get("score") or 0.0) >= 0.7):
                    log_trace_event(
                        trace_id=decision_id,
                        event_type="agent_contained",
                        source_type="agent",
                        source_id="Outbound_Comms_Monitor",
                        target_type="agent",
                        target_id=agent_id,
                        payload={
                            "mechanism": "outbound_email_monitor",
                            "scope": "email_outbound",
                            "reasons": reasons,
                            "severity": severity,
                        },
                    )
                    # Hook: inform policy gate/controls to revoke outbound email capability for this agent.
                    log_trace_event(
                        trace_id=decision_id,
                        event_type="policy_capability_revoked",
                        source_type="agent",
                        source_id="Outbound_Comms_Monitor",
                        target_type="policy",
                        target_id="capability:email_outbound",
                        payload={
                            "agent_id": agent_id,
                            "capability": "email_outbound",
                            "reason": "anomaly_detected",
                        },
                    )
            except Exception:
                pass
    except Exception:
        pass
    return an_id


def list_outbound_anomalies(*, limit: int = 100) -> List[Dict[str, Any]]:
    _ensure_tables()
    limit = max(1, min(int(limit or 100), 500))
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, event_id, tenant_id, agent_id, severity, reasons_json, score, created_at
                    FROM outbound_email_anomalies
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows or []:
            try:
                reasons = json.loads(r[5]) if r[5] else []
            except Exception:
                reasons = []
            out.append(
                {
                    "id": r[0],
                    "event_id": r[1],
                    "tenant_id": r[2],
                    "agent_id": r[3],
                    "severity": r[4],
                    "reasons": reasons,
                    "score": float(r[6] or 0.0),
                    "created_at": int(r[7] or 0),
                }
            )
        return out
    except Exception:
            try:
                contain_env = str(__import__("os").getenv("OUTBOUND_CONTAIN_ON_ANOMALY", "0")).strip().lower() in ("1", "true", "yes")
            except Exception:
                contain_env = False
            try:
                if contain_env and (severity in ("high", "critical") or float(analysis.get("score") or 0.0) >= 0.7):
                    # Persist capability revoke via agent_containment service (policy-style control)
                    try:
                        from src.app.services.agent_containment import contain_agent
                        ttl_env = __import__("os").getenv("OUTBOUND_CONTAIN_TTL_SECONDS", "900")
                        ttl = None
                        try:
                            ttl = int(ttl_env)
                        except Exception:
                            ttl = None
                        contain_agent(
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                            capability="email_outbound",
                            score=float(analysis.get("score") or 0.0),
                            reasons=reasons,
                            actor="Outbound_Comms_Monitor",
                            decision_id=decision_id,
                            trace_id=decision_id,
                            ttl_seconds=ttl,
                        )
                    except Exception:
                        pass
                    # Also emit a lightweight containment trace for UIs that don’t read containment table yet.
                    try:
                        log_trace_event(
                            trace_id=decision_id,
                            event_type="agent_contained",
                            source_type="agent",
                            source_id="Outbound_Comms_Monitor",
                            target_type="agent",
                            target_id=agent_id,
                            payload={
                                "mechanism": "outbound_email_monitor",
                                "scope": "email_outbound",
                                "reasons": reasons,
                                "severity": severity,
                            },
                        )
                    except Exception:
                        pass
            except Exception:
                pass
