from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


LIFECYCLE_STATES = ("active", "sell_through", "procurement_blocked", "discontinued")
_FORWARD = {
    "active": {"sell_through"},
    "sell_through": {"procurement_blocked"},
    "procurement_blocked": {"discontinued"},
    "discontinued": set(),
}
_PERMISSIONS = {
    "active": (True, True),
    "sell_through": (True, False),
    "procurement_blocked": (True, False),
    "discontinued": (False, False),
}


class LifecyclePermissionDenied(RuntimeError):
    def __init__(self, permission: str, state: str) -> None:
        self.permission = permission
        self.state = state
        super().__init__(f"lifecycle_{permission}_blocked:{state}")


def lifecycle_permissions(db, *, tenant_id: str, sku: str) -> dict[str, Any]:
    """Resolve the execution policy; absence means the declared active default."""
    tenant = str(tenant_id or "").strip()
    key = str(sku or "").strip()
    if not tenant or not key:
        raise ValueError("lifecycle_permission_scope_required")
    try:
        row = db.execute(
            text(
                """
                SELECT state, version, selling_allowed, procurement_allowed,
                       updated_at, updated_by
                FROM product_lifecycle_state
                WHERE tenant_id=:tenant AND sku=:sku
                """
            ),
            {"tenant": tenant, "sku": key},
        ).fetchone()
    except Exception as exc:
        raise RuntimeError("lifecycle_policy_unavailable") from exc
    if not row:
        state, version, selling, procurement, updated_at, updated_by = (
            "active", 0, True, True, None, None,
        )
    else:
        state, version, selling, procurement, updated_at, updated_by = row
    return {
        "tenant_id": tenant,
        "sku": key,
        "state": str(state),
        "version": int(version),
        "selling_allowed": bool(selling),
        "procurement_allowed": bool(procurement),
        "updated_at": str(updated_at or "") or None,
        "updated_by": str(updated_by or "") or None,
    }


def require_lifecycle_permission(
    db,
    *,
    tenant_id: str,
    sku: str,
    permission: str,
) -> dict[str, Any]:
    if permission not in {"selling", "procurement"}:
        raise ValueError("unsupported_lifecycle_permission")
    policy = lifecycle_permissions(db, tenant_id=tenant_id, sku=sku)
    if not bool(policy[f"{permission}_allowed"]):
        raise LifecyclePermissionDenied(permission, str(policy["state"]))
    return policy


def filter_sellable_skus(
    db,
    *,
    tenant_id: str,
    skus: list[str],
) -> set[str]:
    """Batch catalog gate. Products without a transition retain active defaults."""
    keys = sorted({str(sku).strip() for sku in skus if str(sku).strip()})
    if not keys:
        return set()
    placeholders = ", ".join(f":sku_{index}" for index in range(len(keys)))
    params = {"tenant": str(tenant_id), **{
        f"sku_{index}": sku for index, sku in enumerate(keys)
    }}
    try:
        rows = db.execute(
            text(
                f"""
                SELECT sku, selling_allowed
                FROM product_lifecycle_state
                WHERE tenant_id=:tenant AND sku IN ({placeholders})
                """
            ),
            params,
        ).fetchall()
    except Exception as exc:
        raise RuntimeError("lifecycle_policy_unavailable") from exc
    explicit = {str(sku): bool(allowed) for sku, allowed in rows}
    return {sku for sku in keys if explicit.get(sku, True)}


def _current(db, *, tenant_id: str, sku: str) -> tuple[str, int]:
    row = db.execute(
        text(
            """
            SELECT state, version
            FROM product_lifecycle_state
            WHERE tenant_id=:tenant AND sku=:sku
            """
        ),
        {"tenant": tenant_id, "sku": sku},
    ).fetchone()
    return (str(row[0]), int(row[1])) if row else ("active", 0)


def propose_lifecycle_transition(
    *,
    tenant_id: str,
    sku: str,
    to_state: str,
    reason: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    product_sku = str(sku or "").strip()
    target = str(to_state or "").strip().lower()
    actor = str(proposed_by or "").strip()
    if not all((tenant, product_sku, reason, actor)):
        raise ValueError("lifecycle_transition_fields_required")
    if target not in LIFECYCLE_STATES:
        raise ValueError("unsupported_lifecycle_state")
    with db_session() as db:
        current, version = _current(db, tenant_id=tenant, sku=product_sku)
        forward = target in _FORWARD[current]
        reopening = LIFECYCLE_STATES.index(target) < LIFECYCLE_STATES.index(current)
        if not forward and not reopening:
            raise ValueError(f"invalid_lifecycle_transition:{current}:{target}")
        transition_id = f"lifecycle-{uuid.uuid4().hex}"
        db.execute(
            text(
                """
                INSERT INTO product_lifecycle_transition
                (id, tenant_id, sku, from_state, to_state, reason,
                 evidence_json, status, proposed_by, proposed_at, expected_version)
                VALUES
                (:id, :tenant, :sku, :from_state, :to_state, :reason,
                 :evidence, 'pending', :actor, :now, :version)
                """
            ),
            {
                "id": transition_id,
                "tenant": tenant,
                "sku": product_sku,
                "from_state": current,
                "to_state": target,
                "reason": str(reason),
                "evidence": json.dumps(evidence or {}, sort_keys=True),
                "actor": actor,
                "now": datetime.now(timezone.utc).isoformat(),
                "version": version,
            },
        )
        db.commit()
    return {
        "id": transition_id,
        "status": "pending",
        "from_state": current,
        "to_state": target,
        "human_approval_required": True,
        "reopening": reopening,
    }


def resolve_lifecycle_transition(
    *,
    tenant_id: str,
    transition_id: str,
    approved: bool,
    resolved_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    actor = str(resolved_by or "").strip()
    if not tenant or not actor:
        raise ValueError("lifecycle_resolution_identity_required")
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT sku, from_state, to_state, status, expected_version
                FROM product_lifecycle_transition
                WHERE id=:id AND tenant_id=:tenant
                """
            ),
            {"id": transition_id, "tenant": tenant},
        ).fetchone()
        if not row:
            raise ValueError("lifecycle_transition_not_found")
        if str(row[3]) != "pending":
            raise ValueError("lifecycle_transition_already_resolved")
        sku, from_state, to_state, _, expected_version = row
        current, version = _current(db, tenant_id=tenant, sku=str(sku))
        if current != str(from_state) or version != int(expected_version):
            raise RuntimeError("lifecycle_transition_stale")
        now = datetime.now(timezone.utc).isoformat()
        status = "approved" if approved else "rejected"
        if approved:
            selling, procurement = _PERMISSIONS[str(to_state)]
            params = {
                "id": f"lifecycle-state:{tenant}:{sku}",
                "tenant": tenant,
                "sku": sku,
                "state": to_state,
                "version": version + 1,
                "selling": selling,
                "procurement": procurement,
                "now": now,
                "actor": actor,
            }
            if version == 0:
                db.execute(
                    text(
                        """
                        INSERT INTO product_lifecycle_state
                        (id, tenant_id, sku, state, version, selling_allowed,
                         procurement_allowed, updated_at, updated_by)
                        VALUES
                        (:id, :tenant, :sku, :state, :version, :selling,
                         :procurement, :now, :actor)
                        """
                    ),
                    params,
                )
            else:
                result = db.execute(
                    text(
                        """
                        UPDATE product_lifecycle_state
                        SET state=:state, version=:version,
                            selling_allowed=:selling,
                            procurement_allowed=:procurement,
                            updated_at=:now, updated_by=:actor
                        WHERE tenant_id=:tenant AND sku=:sku
                          AND version=:expected
                        """
                    ),
                    {**params, "expected": version},
                )
                if int(result.rowcount or 0) != 1:
                    raise RuntimeError("lifecycle_transition_conflict")
        db.execute(
            text(
                """
                UPDATE product_lifecycle_transition
                SET status=:status, resolved_by=:actor, resolved_at=:now
                WHERE id=:id AND tenant_id=:tenant AND status='pending'
                """
            ),
            {
                "status": status,
                "actor": actor,
                "now": now,
                "id": transition_id,
                "tenant": tenant,
            },
        )
        db.commit()
    return {
        "id": transition_id,
        "status": status,
        "state": str(to_state) if approved else current,
        "selling_allowed": _PERMISSIONS[str(to_state)][0] if approved else None,
        "procurement_allowed": _PERMISSIONS[str(to_state)][1] if approved else None,
    }
