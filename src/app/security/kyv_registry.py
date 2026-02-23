"""Know-Your-Vendor (KYV) onboarding registry.

Provides a DB-backed vendor entity registry that tracks:
- Legal entity name + business registration number (ABN/ACN/EIN)
- Verification status (pending → verified → suspended → revoked)
- Domain ownership proof (verified email domain)
- Risk tier (low / medium / high / critical)
- Onboarding date and last-review date

ENV configuration
-----------------
KYV_AUTO_VERIFY           – "1" to auto-verify when ABN check passes (default "0")
KYV_ABN_VALIDATION        – "1" to enable ABN/ACN format validation (default "1")
KYV_REVIEW_INTERVAL_DAYS  – Days between mandatory re-reviews (default 90)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.app.models.db import db_session

logger = logging.getLogger("shopsquire.kyv_registry")


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        if v is None or str(v).strip() == "":
            return default
        return max(0, int(float(str(v).strip())))
    except Exception:
        return default


def _env_bool(key: str, default: bool = False) -> bool:
    v = _env(key)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes")


_VALID_STATUSES = {"pending", "verified", "suspended", "revoked"}
_VALID_RISK_TIERS = {"low", "medium", "high", "critical"}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _ensure_table() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS kyv_vendors (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        legal_name TEXT NOT NULL,
                        trading_name TEXT,
                        registration_number TEXT,
                        registration_type TEXT,
                        verified_domain TEXT,
                        status TEXT NOT NULL DEFAULT 'pending',
                        risk_tier TEXT NOT NULL DEFAULT 'medium',
                        contact_email TEXT,
                        notes TEXT,
                        onboarded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        verified_at TEXT,
                        last_review_at TEXT,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            db.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_kyv_tenant_reg "
                    "ON kyv_vendors(tenant_id, registration_number) WHERE registration_number IS NOT NULL"
                )
            )
            db.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_kyv_tenant_domain "
                    "ON kyv_vendors(tenant_id, verified_domain) WHERE verified_domain IS NOT NULL"
                )
            )
            db.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ABN / ACN validation (Australian Business/Company Number)
# ---------------------------------------------------------------------------

_ABN_WEIGHTS = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]


def validate_abn(abn: str) -> bool:
    """Validate an Australian Business Number (11 digits, Modulus-89 check)."""
    digits = re.sub(r"\s+", "", str(abn or ""))
    if not re.fullmatch(r"\d{11}", digits):
        return False
    nums = [int(d) for d in digits]
    nums[0] -= 1  # subtract 1 from first digit per ATO spec
    total = sum(n * w for n, w in zip(nums, _ABN_WEIGHTS))
    return total % 89 == 0


def validate_acn(acn: str) -> bool:
    """Validate an Australian Company Number (9 digits, Modulus-10 check)."""
    digits = re.sub(r"\s+", "", str(acn or ""))
    if not re.fullmatch(r"\d{9}", digits):
        return False
    weights = [8, 7, 6, 5, 4, 3, 2, 1]
    nums = [int(d) for d in digits]
    total = sum(n * w for n, w in zip(nums[:8], weights))
    check = (10 - (total % 10)) % 10
    return check == nums[8]


def validate_registration(number: str, reg_type: str | None = None) -> Dict[str, Any]:
    """Validate a business registration number based on type."""
    if not _env_bool("KYV_ABN_VALIDATION", True):
        return {"valid": True, "type": reg_type or "unknown", "skipped": True}

    clean = re.sub(r"\s+", "", str(number or ""))
    if not clean:
        return {"valid": False, "type": None, "reason": "empty"}

    # Auto-detect type
    if reg_type is None:
        if len(clean) == 11 and clean.isdigit():
            reg_type = "abn"
        elif len(clean) == 9 and clean.isdigit():
            reg_type = "acn"
        else:
            reg_type = "other"

    reg_type = str(reg_type).lower()
    if reg_type == "abn":
        ok = validate_abn(clean)
        return {"valid": ok, "type": "abn", "reason": None if ok else "ABN checksum failed"}
    if reg_type == "acn":
        ok = validate_acn(clean)
        return {"valid": ok, "type": "acn", "reason": None if ok else "ACN checksum failed"}

    # For other reg types, accept if non-empty
    return {"valid": bool(clean), "type": reg_type}


# ---------------------------------------------------------------------------
# Registry CRUD
# ---------------------------------------------------------------------------

def register_vendor(
    *,
    tenant_id: str,
    legal_name: str,
    registration_number: str | None = None,
    registration_type: str | None = None,
    trading_name: str | None = None,
    verified_domain: str | None = None,
    contact_email: str | None = None,
    risk_tier: str = "medium",
    notes: str | None = None,
) -> Dict[str, Any]:
    """Register a new vendor entity. Returns the created record or error."""
    _ensure_table()
    vendor_id = str(uuid.uuid4())
    risk_tier = str(risk_tier).lower() if risk_tier else "medium"
    if risk_tier not in _VALID_RISK_TIERS:
        risk_tier = "medium"

    # Validate registration number if provided
    reg_result: Dict[str, Any] | None = None
    if registration_number:
        reg_result = validate_registration(registration_number, registration_type)
        if not reg_result.get("valid"):
            return {"ok": False, "reason": reg_result.get("reason", "invalid registration number"), "validation": reg_result}
        registration_type = reg_result.get("type") or registration_type

    status = "pending"
    verified_at = None
    if _env_bool("KYV_AUTO_VERIFY") and reg_result and reg_result.get("valid") and not reg_result.get("skipped"):
        status = "verified"
        verified_at = datetime.now(timezone.utc).isoformat()

    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO kyv_vendors
                    (id, tenant_id, legal_name, trading_name, registration_number,
                     registration_type, verified_domain, status, risk_tier,
                     contact_email, notes, onboarded_at, verified_at, last_review_at, updated_at)
                    VALUES
                    (:id, :tenant_id, :legal_name, :trading_name, :registration_number,
                     :registration_type, :verified_domain, :status, :risk_tier,
                     :contact_email, :notes, CURRENT_TIMESTAMP, :verified_at, NULL, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": vendor_id,
                    "tenant_id": tenant_id,
                    "legal_name": legal_name,
                    "trading_name": trading_name,
                    "registration_number": registration_number,
                    "registration_type": registration_type,
                    "verified_domain": (verified_domain or "").strip().lower() or None,
                    "status": status,
                    "risk_tier": risk_tier,
                    "contact_email": contact_email,
                    "notes": notes,
                    "verified_at": verified_at,
                },
            )
            db.commit()
    except Exception as exc:
        logger.warning("vendor registration failed: %s", exc)
        return {"ok": False, "reason": str(exc)}

    return {
        "ok": True,
        "vendor_id": vendor_id,
        "status": status,
        "risk_tier": risk_tier,
        "registration_valid": reg_result,
    }


def get_vendor(*, tenant_id: str, vendor_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single vendor by ID."""
    _ensure_table()
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id, tenant_id, legal_name, trading_name, registration_number,
                           registration_type, verified_domain, status, risk_tier,
                           contact_email, notes, onboarded_at, verified_at, last_review_at, updated_at
                    FROM kyv_vendors
                    WHERE id = :id AND tenant_id = :tenant_id
                    """
                ),
                {"id": vendor_id, "tenant_id": tenant_id},
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return _row_to_dict(row)


def lookup_vendor_by_domain(*, tenant_id: str, domain: str) -> Optional[Dict[str, Any]]:
    """Find a verified vendor by their verified domain."""
    _ensure_table()
    domain = (domain or "").strip().lower()
    if not domain:
        return None
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT id, tenant_id, legal_name, trading_name, registration_number,
                           registration_type, verified_domain, status, risk_tier,
                           contact_email, notes, onboarded_at, verified_at, last_review_at, updated_at
                    FROM kyv_vendors
                    WHERE tenant_id = :tenant_id AND verified_domain = :domain
                    ORDER BY updated_at DESC LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "domain": domain},
            ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    return _row_to_dict(row)


def update_vendor_status(
    *,
    tenant_id: str,
    vendor_id: str,
    status: str,
    notes: str | None = None,
) -> bool:
    """Transition a vendor's status (pending→verified, verified→suspended, etc.)."""
    _ensure_table()
    status = str(status).lower()
    if status not in _VALID_STATUSES:
        return False
    verified_clause = ""
    if status == "verified":
        verified_clause = ", verified_at = CURRENT_TIMESTAMP"
    try:
        with db_session() as db:
            db.execute(
                text(
                    f"""
                    UPDATE kyv_vendors
                    SET status = :status,
                        notes = COALESCE(:notes, notes),
                        updated_at = CURRENT_TIMESTAMP
                        {verified_clause}
                    WHERE id = :id AND tenant_id = :tenant_id
                    """
                ),
                {"id": vendor_id, "tenant_id": tenant_id, "status": status, "notes": notes},
            )
            db.commit()
        return True
    except Exception:
        return False


def list_vendors_needing_review(*, tenant_id: str) -> List[Dict[str, Any]]:
    """Return vendors whose last_review_at is older than the configured interval."""
    _ensure_table()
    interval_days = _env_int("KYV_REVIEW_INTERVAL_DAYS", 90)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=interval_days)).isoformat()
    try:
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT id, tenant_id, legal_name, trading_name, registration_number,
                           registration_type, verified_domain, status, risk_tier,
                           contact_email, notes, onboarded_at, verified_at, last_review_at, updated_at
                    FROM kyv_vendors
                    WHERE tenant_id = :tenant_id
                      AND status = 'verified'
                      AND (last_review_at IS NULL OR last_review_at < :cutoff)
                    ORDER BY last_review_at ASC NULLS FIRST
                    LIMIT 100
                    """
                ),
                {"tenant_id": tenant_id, "cutoff": cutoff},
            ).fetchall()
    except Exception:
        rows = []
    return [_row_to_dict(r) for r in (rows or [])]


def mark_reviewed(*, tenant_id: str, vendor_id: str) -> bool:
    """Update last_review_at to now."""
    _ensure_table()
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    UPDATE kyv_vendors
                    SET last_review_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id AND tenant_id = :tenant_id
                    """
                ),
                {"id": vendor_id, "tenant_id": tenant_id},
            )
            db.commit()
        return True
    except Exception:
        return False


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": row[0],
        "tenant_id": row[1],
        "legal_name": row[2],
        "trading_name": row[3],
        "registration_number": row[4],
        "registration_type": row[5],
        "verified_domain": row[6],
        "status": row[7],
        "risk_tier": row[8],
        "contact_email": row[9],
        "notes": row[10],
        "onboarded_at": row[11],
        "verified_at": row[12],
        "last_review_at": row[13],
        "updated_at": row[14],
    }
