"""Dated, source-bound currency authority.

Money is never converted from an unversioned number or a process-wide default.
Callers must supply the exact approved quote that justified the conversion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN
import re
import hashlib

from sqlalchemy import text

from src.app.models.db import db_session


_ISO_4217 = re.compile(r"^[A-Z]{3}$")


def normalize_currency(value: str) -> str:
    currency = str(value or "").strip().upper()
    if not _ISO_4217.fullmatch(currency):
        raise ValueError("invalid_iso_currency")
    return currency


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class FxAuthority:
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: str
    source: str
    source_record_id: str
    status: str = "approved"

    def validate(self) -> "FxAuthority":
        base = normalize_currency(self.base_currency)
        quote = normalize_currency(self.quote_currency)
        if base == quote or Decimal(self.rate) <= 0:
            raise ValueError("invalid_fx_pair_or_rate")
        if not str(self.source or "").strip() or not str(self.source_record_id or "").strip():
            raise ValueError("fx_provenance_required")
        _utc(self.as_of)
        if self.status != "approved":
            raise ValueError("fx_authority_not_approved")
        return self


def convert_minor_units(
    amount_minor: int,
    *,
    from_currency: str,
    to_currency: str,
    authority: FxAuthority | None,
    at_time: str,
    max_age_seconds: int = 86_400,
) -> dict[str, object]:
    source = normalize_currency(from_currency)
    target = normalize_currency(to_currency)
    if source == target:
        return {
            "amount_minor": int(amount_minor),
            "currency": target,
            "conversion": "identity",
            "fx_authority": None,
        }
    if authority is None:
        raise ValueError("approved_fx_authority_required")
    authority.validate()
    if (normalize_currency(authority.base_currency), normalize_currency(authority.quote_currency)) != (
        source,
        target,
    ):
        raise ValueError("fx_pair_mismatch")
    quote_time = _utc(authority.as_of)
    decision_time = _utc(at_time)
    age = (decision_time - quote_time).total_seconds()
    if age < -300 or age > max(1, int(max_age_seconds)):
        raise ValueError("fx_authority_stale_or_future")
    converted = (Decimal(int(amount_minor)) * Decimal(authority.rate)).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    )
    return {
        "amount_minor": int(converted),
        "currency": target,
        "conversion": "approved_fx",
        "fx_authority": {
            "base_currency": source,
            "quote_currency": target,
            "rate": str(authority.rate),
            "as_of": quote_time.isoformat(),
            "source": authority.source,
            "source_record_id": authority.source_record_id,
        },
    }


def record_fx_authority(
    *,
    tenant_id: str,
    authority: FxAuthority,
    approved_by: str,
) -> str:
    authority.validate()
    tenant = str(tenant_id or "").strip()
    actor = str(approved_by or "").strip()
    if not tenant or not actor:
        raise ValueError("fx_tenant_and_approver_required")
    authority_id = hashlib.sha256(
        (
            f"{tenant}|{authority.base_currency}|{authority.quote_currency}|"
            f"{authority.rate}|{authority.as_of}|{authority.source}|{authority.source_record_id}"
        ).encode()
    ).hexdigest()
    with db_session() as db:
        exists = db.execute(
            text("SELECT 1 FROM currency_rate_authority WHERE id=:id"),
            {"id": authority_id},
        ).fetchone()
        if not exists:
            db.execute(
                text(
                    """
                    INSERT INTO currency_rate_authority
                    (id,tenant_id,base_currency,quote_currency,rate_decimal,as_of,
                     source,source_record_id,status,approved_by,created_at)
                    VALUES
                    (:id,:tenant,:base,:quote,:rate,:as_of,:source,:record,
                     'approved',:actor,CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": authority_id,
                    "tenant": tenant,
                    "base": normalize_currency(authority.base_currency),
                    "quote": normalize_currency(authority.quote_currency),
                    "rate": str(authority.rate),
                    "as_of": _utc(authority.as_of).isoformat(),
                    "source": authority.source,
                    "record": authority.source_record_id,
                    "actor": actor,
                },
            )
            db.commit()
    return authority_id


def latest_fx_authority(
    *, tenant_id: str, base_currency: str, quote_currency: str, at_time: str
) -> FxAuthority | None:
    tenant = str(tenant_id or "").strip()
    base = normalize_currency(base_currency)
    quote = normalize_currency(quote_currency)
    decision_time = _utc(at_time)
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT rate_decimal,as_of,source,source_record_id,status
                FROM currency_rate_authority
                WHERE tenant_id=:tenant AND base_currency=:base
                  AND quote_currency=:quote AND status='approved' AND as_of<=:at_time
                ORDER BY as_of DESC LIMIT 1
                """
            ),
            {"tenant": tenant, "base": base, "quote": quote, "at_time": decision_time.isoformat()},
        ).fetchone()
    if not row:
        return None
    return FxAuthority(
        base_currency=base,
        quote_currency=quote,
        rate=Decimal(str(row[0])),
        as_of=_utc(str(row[1])).isoformat(),
        source=str(row[2]),
        source_record_id=str(row[3]),
        status=str(row[4]),
    )
