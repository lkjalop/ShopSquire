from __future__ import annotations

"""Supplier domain allowlist guard.

Protects inventory write paths against BEC (Business Email Compromise) attacks
where a threat actor sends spoofed supplier emails to trigger fraudulent
inventory updates or PO approvals.

Security model:
- Any inventory mutation triggered by an inbound email must verify the sender's
  domain is in the trusted_supplier_domains table.
- Unknown domains are quarantined and an escalation ticket is created.
- The table is admin-managed; changes are HMAC-logged in the audit chain.
- This guard is NOT a replacement for DMARC/SPF/DKIM — those validate the
  transport layer. This guard validates the *business* identity.
"""

import hashlib
import logging
import os
import re
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text as _text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.supplier_domain_guard")

# ── Table DDL ─────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS trusted_supplier_domains (
    id          TEXT PRIMARY KEY,
    domain      TEXT NOT NULL UNIQUE,
    supplier_id TEXT,
    added_by    TEXT,
    added_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    active      INTEGER DEFAULT 1,
    notes       TEXT
)
"""

_INSERT_DEFAULT = """
INSERT INTO trusted_supplier_domains (id, domain, supplier_id, added_by, notes)
VALUES (:id, :domain, :supplier_id, :added_by, :notes)
ON CONFLICT (domain) DO NOTHING
"""


def ensure_trusted_supplier_domains_table() -> None:
    """Create trusted_supplier_domains table if it does not exist."""
    try:
        with db_session() as db:
            db.execute(_text(_DDL))
            try:
                db.commit()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("ensure_trusted_supplier_domains_table failed: %s", exc)


# ── Email domain extraction ───────────────────────────────────────────────────

_EMAIL_DOMAIN_RE = re.compile(r"@([\w.\-]+)", re.IGNORECASE)


def extract_domain(email_or_header: str) -> Optional[str]:
    """Extract the domain portion from an email address or From: header."""
    m = _EMAIL_DOMAIN_RE.search(str(email_or_header or ""))
    if not m:
        return None
    return m.group(1).lower().strip()


# ── Domain trust check ────────────────────────────────────────────────────────

def is_trusted_supplier_domain(domain: str) -> bool:
    """Return True when *domain* (or a parent domain) is in the allowlist."""
    domain = str(domain or "").lower().strip().strip(".")
    if not domain:
        return False
    try:
        with db_session() as db:
            row = db.execute(
                _text(
                    "SELECT COUNT(*) FROM trusted_supplier_domains "
                    "WHERE active = 1 AND ("
                    "  domain = :d "
                    "  OR :d LIKE '%.' || domain"  # subdomain match
                    ")"
                ),
                {"d": domain},
            ).fetchone()
            return int(row[0] or 0) > 0
    except Exception as exc:
        logger.debug("is_trusted_supplier_domain(%s) failed: %s", domain, exc)
        return False  # fail closed — unknown → untrusted


# ── Guard entry point ─────────────────────────────────────────────────────────

def validate_supplier_email(
    sender_email: str,
    *,
    operation: str = "inventory_update",
    payload_summary: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate that the sender's email domain is in the trusted allowlist.

    Returns:
        {
            "trusted": bool,
            "domain": str,
            "reason": str,
            "quarantine_id": str | None,  # set when untrusted, for audit
        }

    When untrusted, also:
    - Emits a security event (best-effort)
    - Creates an escalation ticket (best-effort)
    - Logs to audit chain (best-effort)
    """
    domain = extract_domain(sender_email)
    if not domain:
        return {
            "trusted": False,
            "domain": "",
            "reason": "cannot_extract_domain",
            "quarantine_id": str(uuid.uuid4()),
        }

    trusted = is_trusted_supplier_domain(domain)
    if trusted:
        return {"trusted": True, "domain": domain, "reason": "domain_allowlisted", "quarantine_id": None}

    quarantine_id = str(uuid.uuid4())
    logger.warning(
        "supplier_email_domain_not_trusted domain=%s op=%s quarantine_id=%s",
        domain, operation, quarantine_id,
    )

    # Emit security event
    try:
        from src.app.security.observer import emit_security_event
        emit_security_event(
            path=f"/inventory/{operation}",
            payload={
                "event": "supplier_domain_not_trusted",
                "domain": domain,
                "sender": sender_email[:128],
                "operation": operation,
                "quarantine_id": quarantine_id,
                "payload_summary": str(payload_summary or "")[:200],
            },
        )
    except Exception:
        pass

    # Create escalation ticket
    try:
        from src.app.services.ticketing import TicketingAgent
        t = TicketingAgent()
        t.create_ticket(
            title=f"Untrusted supplier domain: {domain} attempted {operation}",
            description=(
                f"Sender: {sender_email[:128]}\n"
                f"Domain: {domain}\n"
                f"Operation: {operation}\n"
                f"Quarantine ID: {quarantine_id}\n"
                f"Summary: {str(payload_summary or '')[:200]}"
            ),
            severity="high",
        )
    except Exception:
        pass

    # Audit log
    try:
        from src.app.security.audit_chain import append_audit_record
        append_audit_record(
            record_type="supplier_domain_quarantine",
            actor_id="supplier_domain_guard",
            resource_id=quarantine_id,
            action=operation,
            outcome="quarantined",
            metadata={"domain": domain, "sender": sender_email[:128]},
        )
    except Exception:
        pass

    return {
        "trusted": False,
        "domain": domain,
        "reason": "domain_not_in_allowlist",
        "quarantine_id": quarantine_id,
    }


# ── Admin helpers ─────────────────────────────────────────────────────────────

def add_trusted_domain(
    domain: str,
    *,
    supplier_id: Optional[str] = None,
    added_by: str = "admin",
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a domain to the trusted supplier allowlist.

    Records the addition in the audit chain.
    """
    domain = str(domain or "").lower().strip().strip(".")
    if not domain or not re.match(r"^[\w.\-]+\.[a-z]{2,}$", domain):
        return {"ok": False, "error": "invalid_domain"}
    record_id = str(uuid.uuid4())
    try:
        with db_session() as db:
            db.execute(
                _text(_INSERT_DEFAULT),
                {
                    "id": record_id,
                    "domain": domain,
                    "supplier_id": supplier_id,
                    "added_by": added_by,
                    "notes": notes,
                },
            )
            try:
                db.commit()
            except Exception:
                pass
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    try:
        from src.app.security.audit_chain import append_audit_record
        append_audit_record(
            record_type="trusted_domain_added",
            actor_id=added_by,
            resource_id=domain,
            action="add_trusted_supplier_domain",
            outcome="added",
            metadata={"supplier_id": supplier_id, "notes": notes},
        )
    except Exception:
        pass

    return {"ok": True, "domain": domain, "record_id": record_id}


def list_trusted_domains() -> list:
    """Return all active trusted supplier domains."""
    try:
        with db_session() as db:
            rows = db.execute(
                _text(
                    "SELECT id, domain, supplier_id, added_by, added_at, notes "
                    "FROM trusted_supplier_domains WHERE active = 1 ORDER BY added_at DESC"
                )
            ).fetchall()
        return [
            {
                "id": str(r[0]),
                "domain": str(r[1]),
                "supplier_id": str(r[2] or ""),
                "added_by": str(r[3] or ""),
                "added_at": str(r[4] or ""),
                "notes": str(r[5] or ""),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("list_trusted_domains failed: %s", exc)
        return []
