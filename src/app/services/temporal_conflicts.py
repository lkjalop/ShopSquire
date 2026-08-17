"""Deterministic temporal conflict detection for typed evidence claims."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator


ResolutionOwner = Literal[
    "catalog", "research", "buyer", "computation", "supplier", "tenant_policy", "human",
]
ConflictStatus = Literal["unresolved", "accepted", "superseded", "rejected"]


def _utc(value: str | None, *, upper: bool = False) -> datetime:
    if value is None:
        return datetime.max.replace(tzinfo=timezone.utc) if upper else datetime.min.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("temporal_claim_time_requires_timezone")
    return parsed.astimezone(timezone.utc)


class TemporalClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=240)
    subject: str = Field(min_length=1, max_length=300)
    attribute: str = Field(min_length=1, max_length=120)
    value: Any
    valid_from: str
    valid_to: str | None = None
    observed_at: str
    source: str = Field(min_length=1, max_length=240)
    source_authority: str = Field(default="unspecified", max_length=120)
    source_text: str | None = Field(default=None, max_length=500)
    timezone_name: str | None = Field(default=None, max_length=80)

    @field_validator("valid_from", "valid_to", "observed_at")
    @classmethod
    def validate_time(cls, value: str | None) -> str | None:
        if value is not None:
            _utc(value)
        return value

    @field_validator("timezone_name")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value:
            try:
                ZoneInfo(value)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("temporal_claim_timezone_unknown") from exc
        return value


class TemporalConflictReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conflict_id: str = Field(pattern=r"^tcr-[a-f0-9]{24}$")
    subject: str
    attribute: str
    competing_claim_ids: tuple[str, ...] = Field(min_length=2)
    valid_time_overlap: tuple[str, str | None]
    observed_times: dict[str, str]
    conflict_type: Literal["value_mismatch", "time_anchor_mismatch", "validity_mismatch"]
    affected_stages: tuple[str, ...] = Field(min_length=1)
    resolution_owner: ResolutionOwner
    status: ConflictStatus = "unresolved"
    authority: Literal["conflict_evidence_only"] = "conflict_evidence_only"


_ATTRIBUTE_STAGES: dict[str, tuple[str, ...]] = {
    "lead_time_days": ("commercial", "fulfilment", "response"),
    "availability_quantity": ("commercial", "fulfilment", "response"),
    "price_minor": ("commercial", "response"),
    "required_by": ("commercial", "fulfilment", "response"),
}


def _owner(claims: tuple[TemporalClaim, TemporalClaim]) -> ResolutionOwner:
    authorities = " ".join(item.source_authority.casefold() for item in claims)
    if "supplier" in authorities or "carrier" in authorities:
        return "supplier"
    if "buyer" in authorities:
        return "buyer"
    if "policy" in authorities:
        return "tenant_policy"
    return "research"


def _overlap(left: TemporalClaim, right: TemporalClaim) -> tuple[datetime, datetime] | None:
    start = max(_utc(left.valid_from), _utc(right.valid_from))
    end = min(_utc(left.valid_to, upper=True), _utc(right.valid_to, upper=True))
    # Adjacent half-open validity windows are not conflicts.
    return (start, end) if start < end else None


_TIME_ATTRIBUTES = {
    "required_by", "delivery_date", "deadline", "quote_valid_until", "available_at",
}


def _value_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return _utc(value)
    except (TypeError, ValueError):
        return None


def _conflict_type(left: TemporalClaim, right: TemporalClaim) -> str:
    same_phrase = bool(left.source_text and left.source_text == right.source_text)
    different_zone = bool(
        left.timezone_name and right.timezone_name
        and left.timezone_name != right.timezone_name
    )
    if same_phrase and different_zone:
        return "time_anchor_mismatch"
    if left.attribute in _TIME_ATTRIBUTES:
        return "time_anchor_mismatch"
    return "value_mismatch"


def _receipt(
    left: TemporalClaim, right: TemporalClaim, *, conflict_type: str,
) -> TemporalConflictReceipt | None:
    overlap = _overlap(left, right)
    if overlap is None:
        return None
    pair = tuple(sorted((left.claim_id, right.claim_id)))
    digest = hashlib.sha256(json.dumps({
        "subject": left.subject, "attribute": f"{left.attribute}|{right.attribute}",
        "claims": pair, "type": conflict_type,
    }, sort_keys=True).encode()).hexdigest()[:24]
    end = None if overlap[1] == datetime.max.replace(tzinfo=timezone.utc) else overlap[1].isoformat()
    stages = tuple(dict.fromkeys(
        _ATTRIBUTE_STAGES.get(left.attribute, ("evidence", "fit", "commercial", "response"))
        + _ATTRIBUTE_STAGES.get(right.attribute, ("evidence", "fit", "commercial", "response"))
    ))
    return TemporalConflictReceipt(
        conflict_id=f"tcr-{digest}", subject=left.subject,
        attribute=(left.attribute if left.attribute == right.attribute else f"{left.attribute}|{right.attribute}"),
        competing_claim_ids=pair,
        valid_time_overlap=(overlap[0].isoformat(), end),
        observed_times={item.claim_id: item.observed_at for item in (left, right)},
        conflict_type=conflict_type, affected_stages=stages,
        resolution_owner=_owner((left, right)), status="unresolved",
    )


def detect_temporal_conflicts(
    claims: list[TemporalClaim] | tuple[TemporalClaim, ...],
) -> tuple[TemporalConflictReceipt, ...]:
    """Return stable unresolved receipts; resolution occurs at a separate authority boundary."""
    typed = tuple(claims)
    rows: list[TemporalConflictReceipt] = []
    for index, left in enumerate(typed):
        for right in typed[index + 1:]:
            if (left.subject, left.attribute) != (right.subject, right.attribute):
                continue
            if left.value == right.value:
                continue
            receipt = _receipt(left, right, conflict_type=_conflict_type(left, right))
            if receipt:
                rows.append(receipt)
    # Cross-attribute commercial validity: an offer that expires before the
    # requested delivery date cannot support that promise.
    for quote in (item for item in typed if item.attribute == "quote_valid_until"):
        for delivery in (item for item in typed if item.attribute in {"required_by", "delivery_date"}):
            if quote.subject != delivery.subject:
                continue
            quote_time, delivery_time = _value_time(quote.value), _value_time(delivery.value)
            if quote_time is None or delivery_time is None or quote_time >= delivery_time:
                continue
            receipt = _receipt(quote, delivery, conflict_type="validity_mismatch")
            if receipt:
                rows.append(receipt)
    rows.sort(key=lambda item: item.conflict_id)
    return tuple(rows)


__all__ = ["TemporalClaim", "TemporalConflictReceipt", "detect_temporal_conflicts"]
