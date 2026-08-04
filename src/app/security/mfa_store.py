"""Per-principal TOTP secret store (PCI #5 admin MFA).

Persists one TOTP secret per admin principal (role/identity) with a confirmed flag, so MFA is a real
second factor (per-admin authenticator app) rather than a single shared env OTP. SQLite/Postgres via
the app db_session; the table is created on demand (matches auth.py's inline-DDL pattern).

Defensive: all reads return safe defaults and never raise; writes raise only on a genuine DB error so
the caller can surface it. Secrets are at rest in the app DB — protect the DB as you would any
credential store (the platform encrypts PII columns separately; TOTP secrets are MFA seeds).
"""
from __future__ import annotations

from typing import Optional, Tuple

from sqlalchemy import text as _sql

from src.app.models.db import db_session

_DDL = """
CREATE TABLE IF NOT EXISTS admin_mfa_secrets (
  principal TEXT PRIMARY KEY,
  secret TEXT NOT NULL,
  confirmed INTEGER NOT NULL DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  confirmed_at TEXT
)
"""


def _ensure_table(db) -> None:
    db.execute(_sql(_DDL))


def set_secret(principal: str, secret: str) -> None:
    """Store/replace an UNCONFIRMED secret for principal (enrollment start)."""
    p = str(principal or "").strip().lower()
    if not p or not secret:
        return
    with db_session() as db:
        _ensure_table(db)
        db.execute(
            _sql("INSERT INTO admin_mfa_secrets (principal, secret, confirmed) VALUES (:p, :s, 0) "
                 "ON CONFLICT(principal) DO UPDATE SET secret=:s, confirmed=0, confirmed_at=NULL"),
            {"p": p, "s": str(secret)},
        )
        db.commit()


def get_secret(principal: str) -> Tuple[Optional[str], bool]:
    """Return (secret, confirmed) for principal, or (None, False) if not enrolled. Never raises."""
    p = str(principal or "").strip().lower()
    if not p:
        return None, False
    try:
        with db_session() as db:
            _ensure_table(db)
            row = db.execute(
                _sql("SELECT secret, confirmed FROM admin_mfa_secrets WHERE principal = :p"), {"p": p}
            ).fetchone()
            if not row:
                return None, False
            return str(row[0]), bool(row[1])
    except Exception:
        return None, False


def confirm(principal: str) -> bool:
    """Mark the principal's secret confirmed (after a successful first code). Returns success."""
    p = str(principal or "").strip().lower()
    if not p:
        return False
    with db_session() as db:
        _ensure_table(db)
        res = db.execute(
            _sql("UPDATE admin_mfa_secrets SET confirmed=1, confirmed_at=CURRENT_TIMESTAMP "
                 "WHERE principal = :p"),
            {"p": p},
        )
        db.commit()
        return (getattr(res, "rowcount", 0) or 0) > 0


def is_enrolled(principal: str) -> bool:
    """True only when the principal has a CONFIRMED secret (MFA active for them)."""
    _secret, confirmed = get_secret(principal)
    return bool(confirmed)
