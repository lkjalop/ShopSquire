"""Single revision authority for shopping, conversation, and procurement case state.

Material amendments advance ``shopping_cases.revision`` exactly once.  Every
durable conversation projection for the case is updated in the same database
transaction so asynchronous work can compare one revision number everywhere.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, select, text, update

from src.app.models.orm import ShoppingCase


def _stamp(value: str | None) -> datetime:
    if value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return datetime.now(timezone.utc)


def _tables(db: Any) -> set[str]:
    return set(inspect(db.connection()).get_table_names())


def canonical_case_revision(
    db: Any, *, tenant_id: str, case_id: str, fallback: int = 1,
) -> int:
    if "shopping_cases" not in _tables(db):
        return int(fallback)
    revision = db.execute(select(ShoppingCase.revision).where(
        ShoppingCase.tenant_id == tenant_id,
        ShoppingCase.case_id == case_id,
    )).scalar_one_or_none()
    return int(revision if revision is not None else fallback)


def advance_material_case_revision(
    db: Any,
    *,
    tenant_id: str,
    case_id: str,
    expected_revision: int,
    reason: str,
    conversation_state_overrides: dict[str, dict[str, Any]] | None = None,
    procurement_updates: dict[str, Any] | None = None,
    now_iso: str | None = None,
) -> int:
    """CAS-advance the canonical revision and all conversation projections.

    The caller owns commit/rollback.  A stale shopping or conversation writer
    raises ``case_revision_conflict`` before the transaction can be committed.
    ``conversation_state_overrides`` carries already-validated state changes by
    conversation row id; all other rows retain their facts and only mirror the
    new revision.
    """

    if procurement_updates is not None and set(procurement_updates) - {"requested_quantity", "selected_sku"}:
        raise ValueError("unsupported_fulfillment_intent_update")

    prior = int(expected_revision)
    current = canonical_case_revision(
        db, tenant_id=tenant_id, case_id=case_id, fallback=prior,
    )
    if current != prior:
        raise ValueError("case_revision_conflict")
    new_revision = prior + 1
    stamp = _stamp(now_iso)
    stamp_iso = stamp.isoformat()
    tables = _tables(db)

    if "shopping_cases" in tables:
        changed = db.execute(update(ShoppingCase).where(
            ShoppingCase.tenant_id == tenant_id,
            ShoppingCase.case_id == case_id,
            ShoppingCase.revision == prior,
        ).values(revision=new_revision, updated_at=stamp)).rowcount
        # Compatibility-only conversation cases may predate ShoppingCase.  If a
        # ShoppingCase exists it must advance exactly once.
        exists = db.execute(select(ShoppingCase.id).where(
            ShoppingCase.tenant_id == tenant_id,
            ShoppingCase.case_id == case_id,
        )).scalar_one_or_none()
        if exists is not None and int(changed or 0) != 1:
            raise ValueError("case_revision_conflict")

    if "conversation_case_state" in tables:
        rows = db.execute(text(
            "SELECT id,version,state_json FROM conversation_case_state "
            "WHERE tenant_id=:tenant AND case_id=:case_id"
        ), {"tenant": tenant_id, "case_id": case_id}).fetchall()
        overrides = conversation_state_overrides or {}
        for row in rows:
            if int(row[1]) != prior:
                raise ValueError("case_revision_conflict")
            state = dict(overrides.get(str(row[0])) or json.loads(row[2]))
            typed = state.get("procurement_case_state")
            if procurement_updates:
                from src.app.services.procurement_case_state import ProcurementCaseState

                if not isinstance(typed, dict):
                    raise ValueError("canonical_procurement_state_required")
                if (typed.get("case_id"), typed.get("revision")) != (case_id, prior):
                    raise ValueError("canonical_procurement_state_scope_mismatch")
                # Existing money, workload and allocation constraints survive.
                # Invalid quantity/allocation combinations abort the caller's
                # transaction rather than silently clearing buyer obligations.
                typed = ProcurementCaseState.model_validate(
                    {**typed, **procurement_updates, "revision": new_revision}, strict=True,
                ).model_dump(mode="json")
            if isinstance(typed, dict):
                state["procurement_case_state"] = {**typed, "revision": new_revision}
            changed = db.execute(text(
                "UPDATE conversation_case_state SET state_json=:state,version=:revision,updated_at=:stamp "
                "WHERE id=:id AND version=:expected"
            ), {
                "state": json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                "revision": new_revision, "stamp": stamp_iso, "id": row[0], "expected": prior,
            }).rowcount
            if int(changed or 0) != 1:
                raise ValueError("case_revision_conflict")

    # Do not cancel interpretation work merely because a source receipt,
    # consent receipt, or other same-purpose observation advanced the case.
    # The worker compares its retained buyer purpose with the current case and
    # supersedes only a genuinely replaced objective.

    return new_revision


__all__ = ["advance_material_case_revision", "canonical_case_revision"]
