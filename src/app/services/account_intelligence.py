from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session


PARTY_TYPES = frozenset({"person", "organisation", "supplier", "buyer_account"})
ACTIVITY_TYPES = frozenset(
    {"quote", "order", "return", "refusal", "support_case", "communication", "procurement_outcome"}
)
RELATIONSHIP_TYPES = frozenset(
    {"employee_of", "contact_for", "supplies", "buys_for", "related_account", "possible_duplicate"}
)


def resolve_exact_external_identity(
    *,
    tenant_id: str,
    source: str,
    object_type: str,
    external_id: str,
    party_type: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    object_name = str(object_type or "").strip().lower()
    external = str(external_id or "").strip()
    kind = str(party_type or "").strip().lower()
    if not all((tenant, source_name, object_name, external)):
        raise ValueError("external_identity_scope_required")
    if kind not in PARTY_TYPES:
        raise ValueError("unsupported_party_type")
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT party_id
                FROM party_external_identity
                WHERE tenant_id=:tenant AND source=:source
                  AND object_type=:object_type AND external_id=:external_id
                LIMIT 1
                """
            ),
            {
                "tenant": tenant,
                "source": source_name,
                "object_type": object_name,
                "external_id": external,
            },
        ).fetchone()
        if row:
            return {"party_id": str(row[0]), "created": False, "match_type": "exact_external_id"}
        party_id = f"party-{uuid.uuid4().hex}"
        db.execute(
            text(
                """
                INSERT INTO party
                (id, tenant_id, party_type, display_name, status, created_at, updated_at)
                VALUES (:id, :tenant, :kind, :name, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            ),
            {"id": party_id, "tenant": tenant, "kind": kind, "name": display_name},
        )
        db.execute(
            text(
                """
                INSERT INTO party_external_identity
                (id, tenant_id, party_id, source, object_type, external_id, created_at)
                VALUES (:id, :tenant, :party_id, :source, :object_type, :external_id, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": f"identity-{uuid.uuid4().hex}",
                "tenant": tenant,
                "party_id": party_id,
                "source": source_name,
                "object_type": object_name,
                "external_id": external,
            },
        )
        db.commit()
    return {"party_id": party_id, "created": True, "match_type": "exact_external_id"}


def record_account_activity(
    *,
    tenant_id: str,
    party_id: str,
    activity_type: str,
    external_ref: str,
    occurred_at: str,
    payload: dict[str, Any],
    amount_cents: int | None = None,
    currency: str | None = None,
) -> str:
    tenant = str(tenant_id or "").strip()
    party = str(party_id or "").strip()
    kind = str(activity_type or "").strip().lower()
    reference = str(external_ref or "").strip()
    if kind not in ACTIVITY_TYPES:
        raise ValueError("unsupported_account_activity")
    parsed = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    payload_json = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
    activity_id = hashlib.sha256(
        f"{tenant}|{party}|{kind}|{reference}|{parsed.isoformat()}|{payload_json}".encode()
    ).hexdigest()
    with db_session() as db:
        owner = db.execute(
            text("SELECT 1 FROM party WHERE id=:party AND tenant_id=:tenant"),
            {"party": party, "tenant": tenant},
        ).fetchone()
        if not owner:
            raise ValueError("party_not_in_tenant")
        exists = db.execute(
            text("SELECT 1 FROM account_activity WHERE id=:id"), {"id": activity_id}
        ).fetchone()
        if not exists:
            db.execute(
                text(
                    """
                    INSERT INTO account_activity
                    (id, tenant_id, party_id, activity_type, external_ref,
                     occurred_at, amount_cents, currency, payload_json)
                    VALUES
                    (:id, :tenant, :party, :kind, :reference,
                     :occurred, :amount, :currency, :payload)
                    """
                ),
                {
                    "id": activity_id,
                    "tenant": tenant,
                    "party": party,
                    "kind": kind,
                    "reference": reference,
                    "occurred": parsed.astimezone(timezone.utc).isoformat(),
                    "amount": amount_cents,
                    "currency": currency,
                    "payload": payload_json,
                },
            )
            db.commit()
    return activity_id


def rebuild_account_snapshot(*, tenant_id: str, party_id: str) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    party = str(party_id or "").strip()
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT activity_type, amount_cents, occurred_at
                FROM account_activity
                WHERE tenant_id=:tenant AND party_id=:party
                ORDER BY occurred_at
                """
            ),
            {"tenant": tenant, "party": party},
        ).fetchall()
        counts: dict[str, int] = {}
        gross_value_cents = 0
        watermark = None
        for kind, amount, occurred in rows:
            key = str(kind)
            counts[key] = counts.get(key, 0) + 1
            if key in {"order", "procurement_outcome"}:
                gross_value_cents += int(amount or 0)
            watermark = str(occurred)
        measures = {
            "activity_counts": counts,
            "gross_value_cents": gross_value_cents,
            "return_rate": round(
                counts.get("return", 0) / max(1, counts.get("order", 0)), 4
            ),
            "open_commitments": 0,
        }
        snapshot_id = f"snapshot:{tenant}:{party}"
        params = {
            "id": snapshot_id,
            "tenant": tenant,
            "party": party,
            "measures": json.dumps(measures, sort_keys=True),
            "watermark": watermark,
            "rebuilt": datetime.now(timezone.utc).isoformat(),
        }
        dialect = str(getattr(getattr(db.get_bind(), "dialect", None), "name", ""))
        if dialect == "postgresql":
            db.execute(
                text(
                    """
                    INSERT INTO account_intelligence_snapshot
                    (id, tenant_id, party_id, measures_json, source_watermark, rebuilt_at)
                    VALUES (:id, :tenant, :party, :measures, :watermark, :rebuilt)
                    ON CONFLICT (tenant_id, party_id) DO UPDATE SET
                      measures_json=EXCLUDED.measures_json,
                      source_watermark=EXCLUDED.source_watermark,
                      rebuilt_at=EXCLUDED.rebuilt_at
                    """
                ),
                params,
            )
        else:
            db.execute(
                text(
                    """
                    INSERT OR REPLACE INTO account_intelligence_snapshot
                    (id, tenant_id, party_id, measures_json, source_watermark, rebuilt_at)
                    VALUES (:id, :tenant, :party, :measures, :watermark, :rebuilt)
                    """
                ),
                params,
            )
        db.commit()
    return measures


def propose_party_link(
    *,
    tenant_id: str,
    left_party_id: str,
    right_party_id: str,
    relationship_type: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    """Propose a non-destructive relationship; never merges party records."""
    tenant = str(tenant_id or "").strip()
    left = str(left_party_id or "").strip()
    right = str(right_party_id or "").strip()
    kind = str(relationship_type or "").strip().lower()
    actor = str(proposed_by or "").strip()
    if not tenant or not left or not right or not actor or left == right:
        raise ValueError("party_link_scope_required")
    if kind not in RELATIONSHIP_TYPES:
        raise ValueError("unsupported_party_relationship")
    evidence_json = json.dumps(evidence or {}, sort_keys=True, separators=(",", ":"))
    proposal_id = hashlib.sha256(
        f"{tenant}|link|{left}|{right}|{kind}|{evidence_json}".encode()
    ).hexdigest()
    with db_session() as db:
        count = db.execute(
            text(
                "SELECT COUNT(*) FROM party WHERE tenant_id=:tenant AND id IN (:left,:right)"
            ),
            {"tenant": tenant, "left": left, "right": right},
        ).scalar()
        if int(count or 0) != 2:
            raise ValueError("party_not_in_tenant")
        exists = db.execute(
            text("SELECT status FROM identity_resolution_decision WHERE id=:id"),
            {"id": proposal_id},
        ).fetchone()
        if not exists:
            db.execute(
                text(
                    """
                    INSERT INTO identity_resolution_decision
                    (id, tenant_id, decision_type, left_party_id, right_party_id,
                     status, evidence_json, proposed_at, resolved_by)
                    VALUES (:id,:tenant,:kind,:left,:right,'proposed',:evidence,
                            CURRENT_TIMESTAMP,:actor)
                    """
                ),
                {
                    "id": proposal_id,
                    "tenant": tenant,
                    "kind": f"link:{kind}",
                    "left": left,
                    "right": right,
                    "evidence": evidence_json,
                    "actor": actor,
                },
            )
            db.commit()
    return {
        "id": proposal_id,
        "status": str(exists[0]) if exists else "proposed",
        "decision_type": f"link:{kind}",
        "execution_allowed": False,
    }


def propose_party_merge(
    *,
    tenant_id: str,
    left_party_id: str,
    right_party_id: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    """Record a reversible-review proposal. This function cannot execute a merge."""
    result = propose_party_link(
        tenant_id=tenant_id,
        left_party_id=left_party_id,
        right_party_id=right_party_id,
        relationship_type="possible_duplicate",
        evidence={**(evidence or {}), "merge_requested": True},
        proposed_by=proposed_by,
    )
    with db_session() as db:
        db.execute(
            text(
                """
                UPDATE identity_resolution_decision
                SET decision_type='merge_proposal'
                WHERE id=:id AND tenant_id=:tenant AND status='proposed'
                """
            ),
            {"id": result["id"], "tenant": str(tenant_id).strip()},
        )
        db.commit()
    return {**result, "decision_type": "merge_proposal", "human_review_required": True}
