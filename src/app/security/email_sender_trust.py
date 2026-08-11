from __future__ import annotations

from typing import Any, Dict
import hashlib
from sqlalchemy import text

from src.app.models.db import db_session


def _hash16(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _ensure_table() -> None:
    """Compatibility hook; schema ownership belongs to Alembic.

    Runtime CREATE/ALTER raced across concurrent email inspections on
    PostgreSQL and could poison otherwise successful requests. Test and
    production databases must apply the migration chain before serving.
    """
    return None


def score_sender_trust(email: Dict[str, Any], extracted: Dict[str, Any], tenant_id: str | None) -> Dict[str, Any]:
    _ensure_table()
    tenant = str(tenant_id or "default")
    from_domain = str((extracted.get("meta") or {}).get("from_domain") or "")
    sender_domain_hash = _hash16(from_domain) or "unknown"
    vendor_domain = str(email.get("vendor_domain") or "").strip().lower()
    chain = str(email.get("reply_chain_id") or "").strip()
    prior_chain = str(email.get("prior_reply_chain_id") or "").strip()

    seen_count = 0
    bank_change_count = 0
    oob_verified_count = 0
    mismatch_count = 0
    first_seen_at = None
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT seen_count, bank_change_count, oob_verified_count, reply_chain_mismatch_count
                    , first_seen_at
                    FROM email_sender_trust
                    WHERE tenant_id=:tenant AND sender_domain_hash=:sender
                    """
                ),
                {"tenant": tenant, "sender": sender_domain_hash},
            ).fetchone()
        if row:
            seen_count = int(row[0] or 0)
            bank_change_count = int(row[1] or 0)
            oob_verified_count = int(row[2] or 0)
            mismatch_count = int(row[3] or 0)
            first_seen_at = row[4]
    except Exception:
        pass

    hist = min(1.0, float(seen_count) / 20.0)
    reply_chain_continuity_score = 1.0
    if chain and prior_chain:
        reply_chain_continuity_score = 1.0 if chain == prior_chain else 0.0
    elif chain or prior_chain:
        reply_chain_continuity_score = 0.5
    vendor_relationship_confidence = 0.2 + (0.5 if vendor_domain and vendor_domain == from_domain else 0.0) + (0.3 * hist)
    vendor_relationship_confidence = max(0.0, min(1.0, vendor_relationship_confidence))
    mismatch_rate = (float(mismatch_count) / float(max(1, seen_count))) if seen_count > 0 else 0.0
    domain_age_days = 0
    try:
        from datetime import datetime, timezone

        if isinstance(first_seen_at, str) and first_seen_at.strip():
            dt = datetime.fromisoformat(first_seen_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            domain_age_days = max(0, int((datetime.now(timezone.utc) - dt).total_seconds() // 86400))
        elif seen_count > 0:
            # Coarse fallback when first_seen_at unavailable in legacy rows.
            domain_age_days = min(365, seen_count)
    except Exception:
        domain_age_days = min(365, seen_count) if seen_count > 0 else 0
    trust_score = max(
        0.0,
        min(
            1.0,
            (0.45 * hist)
            + (0.35 * reply_chain_continuity_score)
            + (0.20 * vendor_relationship_confidence)
            - (0.25 * mismatch_rate),
        ),
    )
    return {
        "sender_domain_hash": sender_domain_hash,
        "historical_seen_count": seen_count,
        "sender_trust_score": round(trust_score, 4),
        "reply_chain_continuity_score": round(reply_chain_continuity_score, 4),
        "vendor_relationship_confidence": round(vendor_relationship_confidence, 4),
        "historical_bank_change_count": bank_change_count,
        "historical_oob_verified_count": oob_verified_count,
        "domain_age_days": int(domain_age_days),
    }


def update_sender_trust(email: Dict[str, Any], extracted: Dict[str, Any], verdict: Dict[str, Any], tenant_id: str | None) -> None:
    _ensure_table()
    tenant = str(tenant_id or "default")
    from_domain = str((extracted.get("meta") or {}).get("from_domain") or "")
    sender_domain_hash = _hash16(from_domain) or "unknown"
    chain = str(email.get("reply_chain_id") or "").strip()
    prior_chain = str(email.get("prior_reply_chain_id") or "").strip()
    ind_types = {str((x or {}).get("type") or "") for x in (verdict.get("indicators") or [])}
    bank_change = bool("bank_change_request" in ind_types or "bank_fingerprint_mismatch" in ind_types)
    oob_verified = bool(email.get("oob_verified")) or ("oob_verification_completed" in ind_types)
    mismatch = bool(chain and prior_chain and chain != prior_chain)
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO email_sender_trust
                                        (tenant_id, sender_domain_hash, first_seen_at, seen_count, bank_change_count, oob_verified_count, reply_chain_mismatch_count, last_reply_chain_hash, updated_at)
                                        VALUES (:tenant, :sender, CURRENT_TIMESTAMP, 1, :bank_change, :oob_verified, :mismatch, :chain_hash, CURRENT_TIMESTAMP)
                    ON CONFLICT(tenant_id, sender_domain_hash) DO UPDATE SET
                      seen_count = email_sender_trust.seen_count + 1,
                      bank_change_count = email_sender_trust.bank_change_count + :bank_change,
                      oob_verified_count = email_sender_trust.oob_verified_count + :oob_verified,
                      reply_chain_mismatch_count = email_sender_trust.reply_chain_mismatch_count + :mismatch,
                      last_reply_chain_hash = :chain_hash,
                      updated_at = CURRENT_TIMESTAMP
                    """
                ),
                {
                    "tenant": tenant,
                    "sender": sender_domain_hash,
                    "bank_change": 1 if bank_change else 0,
                    "oob_verified": 1 if oob_verified else 0,
                    "mismatch": 1 if mismatch else 0,
                    "chain_hash": _hash16(chain) if chain else None,
                },
            )
            db.commit()
    except Exception:
        pass
