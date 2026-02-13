from __future__ import annotations

import uuid
from typing import Dict, Optional
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.pii_crypto import encrypt_pii, pii_hash


def create_case(order_id: Optional[str], issue_type: str, description: str, customer_id: Optional[str] = None, guest_email: Optional[str] = None, tenant_id: Optional[str] = None) -> str:
    case_id = str(uuid.uuid4())
    guest_email_norm = (guest_email or "").strip().lower() if guest_email else None
    guest_email_enc = encrypt_pii(guest_email_norm) if guest_email_norm else None
    guest_email_h = pii_hash(guest_email_norm) if guest_email_norm else None
    with db_session() as db:
        params = {
            "id": case_id,
            "tenant_id": tenant_id,
            "order_id": order_id,
            "customer_id": customer_id,
            "guest_email": None,
            "guest_email_hash": guest_email_h,
            "guest_email_encrypted": guest_email_enc,
            "issue_type": issue_type,
            "description": description,
        }
        try:
            db.execute(
                text(
                    """
                    INSERT INTO cases (
                        id, tenant_id, order_id, customer_id, guest_email, guest_email_hash, guest_email_encrypted, issue_type, description, status
                    )
                    VALUES (
                        :id, :tenant_id, :order_id, :customer_id, :guest_email, :guest_email_hash, :guest_email_encrypted, :issue_type, :description, 'open'
                    )
                    """
                ),
                params,
            )
        except Exception as exc:
            # Backward compatibility for older schemas that do not yet include guest email hash/encrypted columns.
            if "guest_email_hash" not in str(exc) and "guest_email_encrypted" not in str(exc):
                raise
            db.rollback()
            db.execute(
                text(
                    """
                    INSERT INTO cases (
                        id, order_id, issue_type, description, status
                    )
                    VALUES (
                        :id, :order_id, :issue_type, :description, 'open'
                    )
                    """
                ),
                {
                    "id": case_id,
                    "order_id": order_id,
                    "issue_type": issue_type,
                    "description": description,
                },
            )
        db.commit()
    return case_id


def get_case_status(case_id: str) -> Dict:
    with db_session() as db:
        row = db.execute(text("SELECT status, issue_type, description, created_at, updated_at FROM cases WHERE id = :id"), {"id": case_id}).fetchone()
        if not row:
            return {"status": "not_found", "case_id": case_id}
        return {
            "status": row[0],
            "issue_type": row[1],
            "description": row[2],
            "created_at": row[3],
            "updated_at": row[4],
        }
