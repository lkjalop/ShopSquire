"""Deterministic payment consequences for uncertain procurement supply."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text


def _instant(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_payment_instant_required")
    return parsed.astimezone(timezone.utc)


def evaluate_payment_consequence(
    *,
    plan_type: str,
    total_amount_cents: int,
    currency: str,
    promise_feasibility: str,
    policy_version: str,
    deposit_bps: int = 0,
    b2b_terms_days: int | None = None,
    account_terms_approved: bool = False,
    authorization_expires_at: str | None = None,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    total = int(total_amount_cents)
    if total < 0 or not policy_version:
        raise ValueError("valid_total_and_policy_required")
    plan = str(plan_type).lower()
    feasibility = str(promise_feasibility or "unknown").lower()
    now = _instant(evaluated_at) or datetime.now(timezone.utc)
    expiry = _instant(authorization_expires_at)
    if expiry is not None and expiry <= now:
        return {
            "plan_type": plan,
            "status": "authorization_expired",
            "currency": currency,
            "total_amount_cents": total,
            "deposit_amount_cents": None,
            "balance_amount_cents": total,
            "terms_days": b2b_terms_days,
            "authorization_expires_at": expiry.isoformat(),
            "policy_version": policy_version,
            "status_reason": "authorization_expired_before_supply_confirmation",
            "state_prevented": "payment_capture",
        }
    if plan == "full_payment":
        status = "capture_authorized" if feasibility == "met" else "authorization_only"
        reason = "confirmed_supply" if feasibility == "met" else "supply_not_fully_confirmed"
        return {
            "plan_type": plan,
            "status": status,
            "currency": currency,
            "total_amount_cents": total,
            "deposit_amount_cents": 0,
            "balance_amount_cents": total,
            "terms_days": None,
            "authorization_expires_at": expiry.isoformat() if expiry else None,
            "policy_version": policy_version,
            "status_reason": reason,
            "state_prevented": None if feasibility == "met" else "full_payment_capture",
        }
    if plan in {"deposit", "balance_after_confirmation"}:
        if not 0 < int(deposit_bps) <= 10000:
            return {
                "plan_type": plan,
                "status": "deposit_policy_required",
                "currency": currency,
                "total_amount_cents": total,
                "deposit_amount_cents": None,
                "balance_amount_cents": total,
                "terms_days": None,
                "authorization_expires_at": expiry.isoformat() if expiry else None,
                "policy_version": policy_version,
                "status_reason": "authoritative_deposit_percentage_required",
                "state_prevented": "payment_authorization",
            }
        deposit = (total * int(deposit_bps)) // 10000
        return {
            "plan_type": plan,
            "status": "deposit_authorization_required",
            "currency": currency,
            "total_amount_cents": total,
            "deposit_amount_cents": deposit,
            "balance_amount_cents": total - deposit,
            "terms_days": None,
            "authorization_expires_at": expiry.isoformat() if expiry else None,
            "policy_version": policy_version,
            "status_reason": "balance_held_until_supplier_confirmation",
            "state_prevented": "balance_capture",
        }
    if plan == "b2b_terms":
        if not account_terms_approved or not b2b_terms_days:
            return {
                "plan_type": plan,
                "status": "terms_not_approved",
                "currency": currency,
                "total_amount_cents": total,
                "deposit_amount_cents": None,
                "balance_amount_cents": total,
                "terms_days": b2b_terms_days,
                "authorization_expires_at": None,
                "policy_version": policy_version,
                "status_reason": "authoritative_account_terms_required",
                "state_prevented": "create_b2b_receivable",
            }
        return {
            "plan_type": plan,
            "status": "terms_approved",
            "currency": currency,
            "total_amount_cents": total,
            "deposit_amount_cents": 0,
            "balance_amount_cents": total,
            "terms_days": int(b2b_terms_days),
            "authorization_expires_at": None,
            "policy_version": policy_version,
            "status_reason": f"net_{int(b2b_terms_days)}_approved",
            "state_prevented": None,
        }
    raise ValueError("unsupported_payment_plan")


def record_payment_consequence(
    db, *, tenant_id: str, case_id: str, result: dict[str, Any], created_at: str | None = None
) -> dict[str, Any]:
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    identity = hashlib.sha256(
        json.dumps(
            {"tenant": tenant_id, "case": case_id, "result": result, "created": timestamp},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    db.execute(
        text(
            "UPDATE procurement_payment_consequence SET superseded_at=:timestamp "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND superseded_at IS NULL"
        ),
        {"timestamp": timestamp, "tenant": tenant_id, "case_id": case_id},
    )
    db.execute(
        text(
            "INSERT INTO procurement_payment_consequence "
            "(id,tenant_id,case_id,plan_type,status,currency,total_amount_cents,deposit_amount_cents,"
            "balance_amount_cents,terms_days,authorization_expires_at,consequence_json,policy_version,"
            "status_reason,created_at,superseded_at) VALUES "
            "(:id,:tenant,:case_id,:plan,:status,:currency,:total,:deposit,:balance,:terms,:expiry,"
            ":payload,:policy,:reason,:created,NULL)"
        ),
        {
            "id": identity,
            "tenant": tenant_id,
            "case_id": case_id,
            "plan": result["plan_type"],
            "status": result["status"],
            "currency": result["currency"],
            "total": result["total_amount_cents"],
            "deposit": result.get("deposit_amount_cents"),
            "balance": result.get("balance_amount_cents"),
            "terms": result.get("terms_days"),
            "expiry": result.get("authorization_expires_at"),
            "payload": json.dumps(result, sort_keys=True, separators=(",", ":")),
            "policy": result["policy_version"],
            "reason": result["status_reason"],
            "created": timestamp,
        },
    )
    db.commit()
    return {"id": identity, **result}
