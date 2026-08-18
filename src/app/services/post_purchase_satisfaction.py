"""Affirmative post-purchase satisfaction contract and persistence."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from src.app.models.orm import PostPurchaseSatisfactionRecord
from src.app.services.commercial_outcome_ledger import record_commercial_outcome


ReasonCode = Literal["fit", "quality", "delivery", "price", "support", "other"]


class SatisfactionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: str = Field(min_length=8, max_length=160)
    rating: int = Field(ge=1, le=5)
    fulfilled_as_expected: bool
    would_recommend: bool | None = None
    reason_codes: tuple[ReasonCode, ...] = Field(default=(), max_length=6)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("satisfaction_time_requires_timezone")
    return current.astimezone(timezone.utc)


def record_post_purchase_satisfaction(
    db: Any,
    *,
    tenant_id: str,
    order_id: str,
    submission: SatisfactionSubmission,
    actor_class: Literal["buyer", "human_operator"],
    source_authority: str,
    observed_at: datetime | None = None,
    commit: bool = True,
) -> PostPurchaseSatisfactionRecord:
    """Persist explicit feedback only after a completed delivery lifecycle."""

    order = db.execute(text("""
        SELECT id, tenant_id, trace_id, status
        FROM orders WHERE id=:order_id AND tenant_id=:tenant_id
    """), {"order_id": order_id, "tenant_id": tenant_id}).fetchone()
    if not order:
        raise ValueError("satisfaction_order_not_found")
    if str(order._mapping.get("status") or "") not in {
        "delivered", "return_requested", "returned",
    }:
        raise ValueError("satisfaction_requires_delivered_order")
    existing = db.execute(select(PostPurchaseSatisfactionRecord).where(
        PostPurchaseSatisfactionRecord.tenant_id == tenant_id,
        PostPurchaseSatisfactionRecord.submission_id == submission.submission_id,
    )).scalar_one_or_none()
    if existing is not None:
        return existing
    now = _utc(observed_at)
    reasons = sorted(set(submission.reason_codes))
    row = PostPurchaseSatisfactionRecord(
        id=str(uuid.uuid4()), submission_id=submission.submission_id,
        tenant_id=tenant_id, order_id=order_id,
        trace_id=order._mapping.get("trace_id"), rating=submission.rating,
        fulfilled_as_expected=submission.fulfilled_as_expected,
        would_recommend=submission.would_recommend,
        reason_codes_json=reasons, actor_class=actor_class,
        source_authority=source_authority, observed_at=now, created_at=now,
    )
    db.add(row)
    record_commercial_outcome(
        db,
        tenant_id=tenant_id,
        outcome_id=f"{order_id}:satisfaction:{submission.submission_id}",
        order_id=order_id,
        trace_id=order._mapping.get("trace_id"),
        outcome_type="satisfaction_recorded",
        source_authority=source_authority,
        observed_at=now,
        commit=False,
    )
    if commit:
        db.commit()
    return row


__all__ = ["SatisfactionSubmission", "record_post_purchase_satisfaction"]
