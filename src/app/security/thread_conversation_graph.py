from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.email_security_rules import extract_domain


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_subject(subject: str | None) -> str:
    s = str(subject or "").strip().lower()
    s = re.sub(r"^\s*(re|fw|fwd)\s*:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s)
    return s[:256]


def _hash16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _iso_now() -> str:
    return _utc_now().isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        v = str(ts).replace("Z", "+00:00")
        d = datetime.fromisoformat(v)
        return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _threshold_hours() -> int:
    try:
        return max(0, int(float(os.getenv("THREAD_REENTRY_SILENCE_HOURS", "168") or 168)))
    except Exception:
        return 168


def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS email_thread_graph_state (
                      tenant_id TEXT NOT NULL,
                      thread_key TEXT NOT NULL,
                      first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      last_sender_domain TEXT,
                      sender_domains_json TEXT,
                      message_count INTEGER NOT NULL DEFAULT 0,
                      updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (tenant_id, thread_key)
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _thread_key(email: Dict[str, Any]) -> str:
    chain = str(email.get("reply_chain_id") or "").strip()
    prior_chain = str(email.get("prior_reply_chain_id") or "").strip()
    conv = str(email.get("conversation_id") or "").strip()
    if chain:
        return f"chain:{chain[:120]}"
    if prior_chain:
        return f"chain:{prior_chain[:120]}"
    if conv:
        return f"conv:{conv[:120]}"
    subj = _norm_subject(str(email.get("subject") or ""))
    return f"subject:{_hash16(subj or 'na')}"


def analyze_thread_conversation_graph(email: Dict[str, Any], *, tenant_id: str | None) -> Dict[str, Any]:
    _ensure_table()
    tenant = str(tenant_id or "default")
    tk = _thread_key(email)
    sender_domain = str(extract_domain(str(email.get("from_addr") or "")) or "").lower()
    threshold_h = _threshold_hours()
    now = _utc_now()

    prev_last_seen = None
    prev_sender = ""
    prev_domains: List[str] = []
    prev_count = 0
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT last_seen_at, last_sender_domain, sender_domains_json, message_count
                    FROM email_thread_graph_state
                    WHERE tenant_id=:tenant AND thread_key=:thread_key
                    """
                ),
                {"tenant": tenant, "thread_key": tk},
            ).fetchone()
            if row:
                prev_last_seen = str(row[0] or "")
                prev_sender = str(row[1] or "")
                prev_count = int(row[3] or 0)
                try:
                    prev_domains = [str(x).lower() for x in (json.loads(row[2] or "[]") or []) if str(x).strip()]
                except Exception:
                    prev_domains = []
    except Exception:
        pass

    gap_hours = 0.0
    if prev_last_seen:
        dt = _parse_iso(prev_last_seen)
        if dt is not None:
            gap_hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    reentry_after_silence = bool(prev_count > 0 and gap_hours >= float(threshold_h))
    sender_domain_drift = bool(prev_count > 0 and prev_sender and sender_domain and prev_sender != sender_domain)

    indicators: List[Dict[str, Any]] = []
    if reentry_after_silence:
        indicators.append(
            {
                "type": "thread_reentry_after_silence",
                "value": round(gap_hours, 2),
                "reason": f"Thread re-entry after {round(gap_hours, 1)}h silence (threshold {threshold_h}h)",
            }
        )
    if sender_domain_drift:
        indicators.append(
            {
                "type": "thread_sender_domain_drift",
                "value": {"previous": prev_sender, "current": sender_domain},
                "reason": "Sender domain drift detected on existing thread",
            }
        )
    if reentry_after_silence and sender_domain_drift:
        indicators.append(
            {
                "type": "thread_reentry_drift_combo",
                "value": True,
                "reason": "Thread re-entry after silence + sender drift (high hijack risk)",
            }
        )

    new_domains = sorted(set([x for x in (prev_domains + ([sender_domain] if sender_domain else [])) if x]))[:20]
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO email_thread_graph_state
                    (tenant_id, thread_key, first_seen_at, last_seen_at, last_sender_domain, sender_domains_json, message_count, updated_at)
                    VALUES (:tenant, :thread_key, :now, :now, :sender, :domains, 1, :now)
                    ON CONFLICT(tenant_id, thread_key) DO UPDATE SET
                      last_seen_at=:now,
                      last_sender_domain=:sender,
                      sender_domains_json=:domains,
                      message_count=message_count + 1,
                      updated_at=:now
                    """
                ),
                {
                    "tenant": tenant,
                    "thread_key": tk,
                    "now": _iso_now(),
                    "sender": sender_domain or None,
                    "domains": json.dumps(new_domains, ensure_ascii=False),
                },
            )
            db.commit()
    except Exception:
        pass

    return {
        "thread_key": tk,
        "sender_domain": sender_domain or None,
        "previous_sender_domain": prev_sender or None,
        "gap_hours": round(gap_hours, 2),
        "silence_threshold_hours": threshold_h,
        "reentry_after_silence": reentry_after_silence,
        "sender_domain_drift": sender_domain_drift,
        "indicator_count": len(indicators),
        "indicators": indicators,
        "message_count_before": prev_count,
        "distinct_sender_domains": new_domains,
    }
