"""Contact-frequency governance (agnostic CORE) — David's bounded-communications gate.

The deck's communications layer is autonomous, so it must be CONSENTED, RATE-LIMITED, REGION-AWARE,
and FULLY AUDITED before it can ever message anyone. This module is the DECISION gate every campaign /
offer must pass — it does NOT send anything; it returns ALLOW or SUPPRESS(reason) and writes an audit
record for EVERY decision (allow and suppress alike), so there's a defensible trail of who would have
been contacted, when, and why-not.

Checks, in order (first failure wins, privacy-first):
  1. region rule       — channel blocked in region, or current hour is quiet-hours        → suppress
  2. consent           — region requires consent and the user hasn't granted it for the channel → suppress
  3. per-campaign cap  — already contacted this user for this campaign                     → suppress
  4. frequency window  — >= per_window contacts on this channel within window_seconds      → suppress
  5. otherwise                                                                              → allow

VERTICAL-BLIND: channel/campaign/region are opaque labels. Consent defaults to REQUIRED (opt-in), the
conservative stance. record_contact() accrues frequency only when a real send actually happens (a
separate, deliberate call). Best-effort persistence; the DECISION itself is pure given its inputs.

Tables: contact_consent(uid_hash, channel, granted, region, updated_at),
        contact_event(id, uid_hash, channel, campaign_id, sent_at),
        contact_audit(id, uid_hash, channel, campaign_id, decision, reason, created_at)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

DEFAULT_TENANT = "default"

# suppression reasons (enumerated — the audit trail keys on these)
ALLOW = "allow"
SUPPRESS_REGION_BLOCKED = "region_blocked"
SUPPRESS_QUIET_HOURS = "quiet_hours"
SUPPRESS_NO_CONSENT = "no_consent"
SUPPRESS_CAMPAIGN_CAP = "campaign_cap"
SUPPRESS_FREQUENCY = "frequency_cap"
SUPPRESS_ERROR_FAIL_CLOSED = "error_fail_closed"  # history unreadable → suppress (never permit blindly)
SUPPRESS_AUDIT_UNAVAILABLE = "audit_unavailable"  # couldn't persist the authz record → suppress

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS contact_consent (
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        granted INTEGER DEFAULT 0,
        region TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (tenant_id, uid_hash, channel)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_event (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        campaign_id TEXT,
        sent_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS contact_audit (
        id TEXT PRIMARY KEY,
        tenant_id TEXT DEFAULT 'default',
        uid_hash TEXT,
        channel TEXT,
        campaign_id TEXT,
        decision TEXT,
        reason TEXT,
        region TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
)
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_contact_event_lookup ON contact_event(tenant_id, uid_hash, channel, sent_at)",
    "CREATE INDEX IF NOT EXISTS ix_contact_event_campaign ON contact_event(tenant_id, uid_hash, campaign_id)",
    "CREATE INDEX IF NOT EXISTS ix_contact_audit_uid ON contact_audit(tenant_id, uid_hash, created_at)",
)

# region → rule. Data-driven (no hardcoded jurisprudence): a deployment supplies its own map. The
# default requires consent everywhere (opt-in) and blocks nothing — the safe, minimal baseline.
_DEFAULT_REGION_RULES: Dict[str, Dict[str, Any]] = {
    "default": {"requires_consent": True, "blocked_channels": [], "quiet_hours": []},
}


@dataclass(frozen=True)
class ContactDecision:
    allowed: bool
    reason: str
    channel: str
    campaign_id: Optional[str]
    region: str
    detail: Dict[str, Any] = field(default_factory=dict)


def ensure_tables(db) -> None:
    for ddl in _DDL:
        db.execute(text(ddl))
    for idx in _INDEXES:
        db.execute(text(idx))


def _now(now_iso: Optional[str]) -> datetime:
    if now_iso:
        try:
            return datetime.fromisoformat(str(now_iso).replace("Z", "").replace("T", " "))
        except Exception:
            pass
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_consent(db, *, uid_hash: str, channel: str, granted: bool, region: str = "default",
                   tenant_id: str = DEFAULT_TENANT) -> bool:
    """Upsert a per-(user, channel) consent record. Returns True on success. Never raises."""
    if db is None or not uid_hash or not channel:
        return False
    try:
        ensure_tables(db)
        tid = str(tenant_id).strip() or DEFAULT_TENANT
        db.execute(text("DELETE FROM contact_consent WHERE tenant_id=:t AND uid_hash=:u AND channel=:c"),
                   {"t": tid, "u": str(uid_hash), "c": str(channel)})
        db.execute(text("INSERT INTO contact_consent (tenant_id, uid_hash, channel, granted, region) "
                        "VALUES (:t,:u,:c,:g,:r)"),
                   {"t": tid, "u": str(uid_hash), "c": str(channel), "g": 1 if granted else 0, "r": str(region)})
        return True
    except Exception:
        return False


def _has_consent(db, *, uid_hash: str, channel: str, tenant_id: str) -> bool:
    try:
        row = db.execute(text("SELECT granted FROM contact_consent WHERE tenant_id=:t AND uid_hash=:u AND channel=:c"),
                         {"t": tenant_id, "u": str(uid_hash), "c": str(channel)}).fetchone()
    except Exception:
        return False
    return bool(row and int(row[0] or 0) == 1)


def record_contact(db, *, uid_hash: str, channel: str, campaign_id: Optional[str] = None,
                   now_iso: Optional[str] = None, tenant_id: str = DEFAULT_TENANT, commit: bool = True) -> bool:
    """Log that a real contact WAS made (accrues frequency). Call this only after an actual send.
    Never raises."""
    if db is None or not uid_hash or not channel:
        return False
    try:
        ensure_tables(db)
        db.execute(text("INSERT INTO contact_event (id, tenant_id, uid_hash, channel, campaign_id, sent_at) "
                        "VALUES (:i,:t,:u,:c,:cm,:s)"),
                   {"i": str(uuid.uuid4()), "t": str(tenant_id).strip() or DEFAULT_TENANT, "u": str(uid_hash),
                    "c": str(channel), "cm": campaign_id, "s": _now(now_iso).strftime("%Y-%m-%d %H:%M:%S")})
        if commit:
            db.commit()
        return True
    except Exception:
        return False


def _count_in_window(db, *, uid_hash: str, channel: str, since: datetime, tenant_id: str) -> int:
    # NO internal swallow: if the history can't be read, the error MUST propagate to evaluate_contact's
    # fail-closed handler — returning 0 here would PERMIT contact on an unreadable history (fail-open).
    row = db.execute(
        text("SELECT COUNT(*) FROM contact_event WHERE tenant_id=:t AND uid_hash=:u AND channel=:c "
             "AND sent_at >= :s"),
        {"t": tenant_id, "u": str(uid_hash), "c": str(channel), "s": since.strftime("%Y-%m-%d %H:%M:%S")},
    ).fetchone()
    return int(row[0] or 0)


def _contacted_for_campaign(db, *, uid_hash: str, campaign_id: str, tenant_id: str) -> bool:
    # NO internal swallow (see _count_in_window): an unreadable campaign history must fail closed, not
    # return False (= "not yet contacted" = permit).
    row = db.execute(text("SELECT 1 FROM contact_event WHERE tenant_id=:t AND uid_hash=:u AND campaign_id=:cm LIMIT 1"),
                     {"t": tenant_id, "u": str(uid_hash), "cm": str(campaign_id)}).fetchone()
    return bool(row)


def _write_audit(db, decision: ContactDecision, *, uid_hash: str, tenant_id: str) -> bool:
    """Persist the authorization decision. Returns True on success. A FALSE here on an ALLOW must
    suppress the contact (no customer-impacting action without a durable authorization record)."""
    try:
        db.execute(text("INSERT INTO contact_audit (id, tenant_id, uid_hash, channel, campaign_id, decision, "
                        "reason, region) VALUES (:i,:t,:u,:c,:cm,:d,:r,:rg)"),
                   {"i": str(uuid.uuid4()), "t": tenant_id, "u": str(uid_hash), "c": decision.channel,
                    "cm": decision.campaign_id, "d": "allow" if decision.allowed else "suppress",
                    "r": decision.reason, "rg": decision.region})
        return True
    except Exception:
        return False


def evaluate_contact(
    db,
    *,
    uid_hash: str,
    channel: str,
    campaign_id: Optional[str] = None,
    region: str = "default",
    now_iso: Optional[str] = None,
    per_window: int = 1,
    window_seconds: int = 86400,
    region_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    tenant_id: str = DEFAULT_TENANT,
    write_audit: bool = True,
) -> ContactDecision:
    """The gate. Returns ALLOW or SUPPRESS(reason) and (by default) writes an audit row for the
    decision. Pure given its inputs + the contact_event/consent history. Never raises — on error it
    fails CLOSED (suppress), because the safe default for an autonomous messenger is to NOT send."""
    rules = region_rules or _DEFAULT_REGION_RULES
    rule = rules.get(region) or rules.get("default") or {}
    tid = str(tenant_id).strip() or DEFAULT_TENANT
    try:
        ensure_tables(db) if db is not None else None
        now = _now(now_iso)

        # 1. region rules
        if str(channel) in (rule.get("blocked_channels") or []):
            decision = ContactDecision(False, SUPPRESS_REGION_BLOCKED, str(channel), campaign_id, region)
        elif now.hour in (rule.get("quiet_hours") or []):
            decision = ContactDecision(False, SUPPRESS_QUIET_HOURS, str(channel), campaign_id, region,
                                       detail={"hour": now.hour})
        # 2. consent
        elif bool(rule.get("requires_consent", True)) and not (db is not None and _has_consent(
                db, uid_hash=uid_hash, channel=channel, tenant_id=tid)):
            decision = ContactDecision(False, SUPPRESS_NO_CONSENT, str(channel), campaign_id, region)
        # 3. per-campaign cap
        elif campaign_id and db is not None and _contacted_for_campaign(
                db, uid_hash=uid_hash, campaign_id=campaign_id, tenant_id=tid):
            decision = ContactDecision(False, SUPPRESS_CAMPAIGN_CAP, str(channel), campaign_id, region)
        else:
            # 4. frequency window
            since = now - timedelta(seconds=int(window_seconds))
            count = _count_in_window(db, uid_hash=uid_hash, channel=channel, since=since, tenant_id=tid) if db is not None else 0
            if count >= int(per_window):
                decision = ContactDecision(False, SUPPRESS_FREQUENCY, str(channel), campaign_id, region,
                                           detail={"count": count, "per_window": int(per_window)})
            else:
                decision = ContactDecision(True, ALLOW, str(channel), campaign_id, region,
                                           detail={"count": count, "per_window": int(per_window)})
    except Exception:
        decision = ContactDecision(False, SUPPRESS_ERROR_FAIL_CLOSED, str(channel), campaign_id, region)

    if write_audit and db is not None:
        audited = _write_audit(db, decision, uid_hash=uid_hash, tenant_id=tid)
        # Durable authorization evidence is mandatory: if we CANNOT record an ALLOW, we must not send.
        if decision.allowed and not audited:
            decision = ContactDecision(False, SUPPRESS_AUDIT_UNAVAILABLE, str(channel), campaign_id, region)
            _write_audit(db, decision, uid_hash=uid_hash, tenant_id=tid)  # best-effort record of the flip
        try:
            db.commit()
        except Exception:
            return decision  # commit failed → keep the (possibly fail-closed) decision; never raise
    return decision


def load_recent_audit(db, *, limit: int = 100, tenant_id: str = DEFAULT_TENANT) -> List[Dict[str, Any]]:
    """Recent contact decisions (the audit trail). Best-effort."""
    if db is None:
        return []
    try:
        ensure_tables(db)
        rows = db.execute(
            text("SELECT uid_hash, channel, campaign_id, decision, reason, region FROM contact_audit "
                 "WHERE COALESCE(tenant_id,'default')=:t ORDER BY created_at DESC LIMIT :lim"),
            {"lim": int(limit), "t": str(tenant_id).strip() or DEFAULT_TENANT},
        ).fetchall()
    except Exception:
        return []
    return [{"uid_hash": r[0], "channel": r[1], "campaign_id": r[2], "decision": r[3],
             "reason": r[4], "region": r[5]} for r in rows]
