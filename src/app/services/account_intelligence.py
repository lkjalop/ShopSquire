from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from src.app.models.db import db_session


PARTY_TYPES = frozenset({"person", "organisation", "supplier", "buyer_account"})
ACTIVITY_TYPES = frozenset(
    {"quote", "order", "return", "refusal", "support_case", "communication", "procurement_outcome"}
)
RELATIONSHIP_TYPES = frozenset(
    {"employee_of", "contact_for", "supplies", "buys_for", "related_account", "possible_duplicate"}
)
IDENTITY_PROPOSAL_TYPES = frozenset({"merge_proposal", "split_proposal"})
IDENTITY_RESOLUTIONS = frozenset({"approved", "rejected"})


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _party_exists(db, *, tenant_id: str, party_id: str) -> bool:
    return bool(
        db.execute(
            text("SELECT 1 FROM party WHERE tenant_id=:tenant AND id=:party LIMIT 1"),
            {"tenant": tenant_id, "party": party_id},
        ).fetchone()
    )


def _require_party_pair(db, *, tenant_id: str, left_party_id: str, right_party_id: str) -> None:
    if left_party_id == right_party_id:
        raise ValueError("identity_proposal_requires_distinct_parties")
    if not _party_exists(db, tenant_id=tenant_id, party_id=left_party_id):
        raise ValueError("party_not_in_tenant")
    if not _party_exists(db, tenant_id=tenant_id, party_id=right_party_id):
        raise ValueError("party_not_in_tenant")


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


def list_parties(
    *,
    tenant_id: str,
    query: str | None = None,
    party_type: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List only parties inside the active tenant with their exact source identities."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("tenant_scope_required")
    kind = str(party_type or "").strip().lower()
    if kind and kind not in PARTY_TYPES:
        raise ValueError("unsupported_party_type")
    needle = str(query or "").strip().lower()
    capped_limit = max(1, min(int(limit), 200))
    where = ["p.tenant_id=:tenant"]
    params: dict[str, Any] = {"tenant": tenant, "limit": capped_limit}
    if kind:
        where.append("p.party_type=:kind")
        params["kind"] = kind
    if needle:
        where.append(
            """
            (
              LOWER(COALESCE(p.display_name,'')) LIKE :needle
              OR LOWER(p.id) LIKE :needle
              OR EXISTS (
                SELECT 1 FROM party_external_identity pei
                WHERE pei.tenant_id=p.tenant_id AND pei.party_id=p.id
                  AND LOWER(pei.external_id) LIKE :needle
              )
            )
            """
        )
        params["needle"] = f"%{needle}%"
    with db_session() as db:
        rows = db.execute(
            text(
                f"""
                SELECT p.id, p.party_type, p.display_name, p.status,
                       p.created_at, p.updated_at,
                       s.measures_json, s.source_watermark, s.rebuilt_at
                FROM party p
                LEFT JOIN account_intelligence_snapshot s
                  ON s.tenant_id=p.tenant_id AND s.party_id=p.id
                WHERE {' AND '.join(where)}
                ORDER BY COALESCE(p.display_name,p.id), p.id
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
        party_ids = [str(row[0]) for row in rows]
        identities: dict[str, list[dict[str, Any]]] = {party_id: [] for party_id in party_ids}
        if party_ids:
            # Avoid a dynamic IN list: the tenant result is already capped and this bounded second query
            # remains portable across SQLite and PostgreSQL.
            identity_rows = db.execute(
                text(
                    """
                    SELECT party_id, source, object_type, external_id, created_at
                    FROM party_external_identity
                    WHERE tenant_id=:tenant
                    ORDER BY created_at, id
                    """
                ),
                {"tenant": tenant},
            ).fetchall()
            for identity in identity_rows:
                party_id = str(identity[0])
                if party_id in identities:
                    identities[party_id].append(
                        {
                            "source": str(identity[1]),
                            "object_type": str(identity[2]),
                            "external_id": str(identity[3]),
                            "created_at": str(identity[4]) if identity[4] is not None else None,
                        }
                    )
        return [
            {
                "party_id": str(row[0]),
                "party_type": str(row[1]),
                "display_name": row[2],
                "status": str(row[3]),
                "created_at": str(row[4]) if row[4] is not None else None,
                "updated_at": str(row[5]) if row[5] is not None else None,
                "identities": identities.get(str(row[0]), []),
                "snapshot": {
                    "measures": _json_object(row[6]),
                    "source_watermark": str(row[7]) if row[7] is not None else None,
                    "rebuilt_at": str(row[8]) if row[8] is not None else None,
                } if row[6] is not None else None,
            }
            for row in rows
        ]


def get_account_timeline(
    *,
    tenant_id: str,
    party_id: str,
    limit: int = 200,
) -> dict[str, Any]:
    """Project authoritative records and observations without letting observations overwrite Party."""
    tenant = str(tenant_id or "").strip()
    party = str(party_id or "").strip()
    capped_limit = max(1, min(int(limit), 500))
    with db_session() as db:
        party_row = db.execute(
            text(
                """
                SELECT id, party_type, display_name, status, created_at, updated_at
                FROM party WHERE tenant_id=:tenant AND id=:party
                """
            ),
            {"tenant": tenant, "party": party},
        ).fetchone()
        if not party_row:
            raise ValueError("party_not_in_tenant")
        identity_rows = db.execute(
            text(
                """
                SELECT source, object_type, external_id, created_at
                FROM party_external_identity
                WHERE tenant_id=:tenant AND party_id=:party
                ORDER BY created_at, id
                """
            ),
            {"tenant": tenant, "party": party},
        ).fetchall()
        identities = [
            {
                "source": str(row[0]),
                "object_type": str(row[1]),
                "external_id": str(row[2]),
                "created_at": str(row[3]) if row[3] is not None else None,
            }
            for row in identity_rows
        ]
        timeline: list[dict[str, Any]] = []
        activity_rows = db.execute(
            text(
                """
                SELECT id, activity_type, external_ref, occurred_at,
                       amount_cents, currency, payload_json
                FROM account_activity
                WHERE tenant_id=:tenant AND party_id=:party
                ORDER BY occurred_at DESC
                LIMIT :limit
                """
            ),
            {"tenant": tenant, "party": party, "limit": capped_limit},
        ).fetchall()
        for row in activity_rows:
            timeline.append(
                {
                    "id": str(row[0]),
                    "event_type": str(row[1]),
                    "event_class": "operational_activity",
                    "occurred_at": str(row[3]),
                    "authority": "operational_record",
                    "external_ref": str(row[2]),
                    "amount_cents": row[4],
                    "currency": row[5],
                    "payload": _json_object(row[6]),
                    "provenance": {"table": "account_activity", "external_ref": str(row[2])},
                }
            )
        table_names = set(inspect(db.get_bind()).get_table_names())
        if "account_observation" in table_names:
            observation_rows = db.execute(
                text(
                    """
                    SELECT id, source, attribute_name, value_json, confidence,
                           occurred_at, observed_at, provenance_ref
                    FROM account_observation
                    WHERE tenant_id=:tenant AND party_id=:party
                    ORDER BY occurred_at DESC
                    LIMIT :limit
                    """
                ),
                {"tenant": tenant, "party": party, "limit": capped_limit},
            ).fetchall()
            for row in observation_rows:
                timeline.append(
                    {
                        "id": str(row[0]),
                        "event_type": str(row[2]),
                        "event_class": "account_observation",
                        "occurred_at": str(row[5]),
                        "observed_at": str(row[6]),
                        "authority": "observation_only",
                        "confidence": float(row[4]),
                        "payload": _json_object(row[3]),
                        "provenance": {
                            "source": str(row[1]),
                            "reference": str(row[7]) if row[7] is not None else None,
                        },
                    }
                )
        if "conversation_fact_observation" in table_names:
            aliases = sorted({party, *(str(row[2]) for row in identity_rows)})
            alias_params = {f"alias_{index}": alias for index, alias in enumerate(aliases)}
            alias_clause = ",".join(f":alias_{index}" for index in range(len(aliases)))
            conversation_rows = db.execute(
                text(
                    f"""
                    SELECT id, subject_ref, category, normalized_value_json,
                           source_excerpt, provenance_json, confidence, authority,
                           status, observed_at, expires_at, source_message_id, trace_id
                    FROM conversation_fact_observation
                    WHERE tenant_id=:tenant AND subject_ref IN ({alias_clause})
                    ORDER BY observed_at DESC
                    LIMIT :limit
                    """
                ),
                {"tenant": tenant, "limit": capped_limit, **alias_params},
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in conversation_rows:
                expires_at = datetime.fromisoformat(str(row[10]).replace("Z", "+00:00"))
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                derived_status = "expired" if expires_at <= now else str(row[8])
                timeline.append(
                    {
                        "id": str(row[0]),
                        "event_type": str(row[2]),
                        "event_class": "conversation_observation",
                        "occurred_at": str(row[9]),
                        "authority": str(row[7]),
                        "status": derived_status,
                        "confidence": float(row[6]),
                        "expires_at": str(row[10]),
                        "payload": _json_object(row[3]),
                        "source_excerpt": str(row[4]),
                        "provenance": {
                            **_json_object(row[5]),
                            "source_message_id": str(row[11]),
                            "trace_id": str(row[12]) if row[12] is not None else None,
                        },
                    }
                )
        relationship_rows = db.execute(
            text(
                """
                SELECT id, from_party_id, to_party_id, relationship_type,
                       valid_from, valid_to
                FROM party_relationship
                WHERE tenant_id=:tenant
                  AND (from_party_id=:party OR to_party_id=:party)
                ORDER BY valid_from DESC
                LIMIT :limit
                """
            ),
            {"tenant": tenant, "party": party, "limit": capped_limit},
        ).fetchall()
        for row in relationship_rows:
            timeline.append(
                {
                    "id": str(row[0]),
                    "event_type": str(row[3]),
                    "event_class": "party_relationship",
                    "occurred_at": str(row[4]),
                    "authority": "governed_relationship",
                    "status": "active" if row[5] is None else "ended",
                    "counterparty_id": str(row[2] if str(row[1]) == party else row[1]),
                    "valid_to": str(row[5]) if row[5] is not None else None,
                    "provenance": {"table": "party_relationship"},
                }
            )
        decision_rows = db.execute(
            text(
                """
                SELECT id, decision_type, left_party_id, right_party_id, status,
                       evidence_json, proposed_at, resolved_at, resolved_by,
                       proposed_by, resolution_note
                FROM identity_resolution_decision
                WHERE tenant_id=:tenant
                  AND (left_party_id=:party OR right_party_id=:party)
                ORDER BY proposed_at DESC
                LIMIT :limit
                """
            ),
            {"tenant": tenant, "party": party, "limit": capped_limit},
        ).fetchall()
        for row in decision_rows:
            timeline.append(
                {
                    "id": str(row[0]),
                    "event_type": str(row[1]),
                    "event_class": "identity_resolution",
                    "occurred_at": str(row[6]),
                    "authority": "human_governed_proposal",
                    "status": str(row[4]),
                    "counterparty_id": str(row[3] if str(row[2]) == party else row[2]),
                    "evidence": _json_object(row[5]),
                    "proposed_by": row[9],
                    "resolved_at": str(row[7]) if row[7] is not None else None,
                    "resolved_by": row[8],
                    "resolution_note": row[10],
                    "execution_allowed": False,
                }
            )
        if "party_redirect_event" in table_names:
            redirect_rows = db.execute(
                text(
                    """
                    SELECT id,event_type,source_party_id,target_party_id,
                           supersedes_event_id,graph_version,executed_by,
                           execution_note,executed_at
                    FROM party_redirect_event
                    WHERE tenant_id=:tenant
                      AND (source_party_id=:party OR target_party_id=:party)
                    ORDER BY graph_version DESC
                    LIMIT :limit
                    """
                ),
                {"tenant": tenant, "party": party, "limit": capped_limit},
            ).fetchall()
            for row in redirect_rows:
                timeline.append(
                    {
                        "id": str(row[0]),
                        "event_type": str(row[1]),
                        "event_class": "party_redirect_execution",
                        "occurred_at": str(row[8]),
                        "authority": "owner_executed_append_only_redirect",
                        "source_party_id": str(row[2]),
                        "target_party_id": str(row[3]),
                        "supersedes_event_id": str(row[4]) if row[4] else None,
                        "graph_version": int(row[5]),
                        "executed_by": str(row[6]),
                        "execution_note": str(row[7]),
                    }
                )
        snapshot_row = db.execute(
            text(
                """
                SELECT measures_json, source_watermark, rebuilt_at
                FROM account_intelligence_snapshot
                WHERE tenant_id=:tenant AND party_id=:party
                """
            ),
            {"tenant": tenant, "party": party},
        ).fetchone()
    timeline.sort(key=lambda item: str(item.get("occurred_at") or ""), reverse=True)
    return {
        "party": {
            "party_id": str(party_row[0]),
            "party_type": str(party_row[1]),
            "display_name": party_row[2],
            "status": str(party_row[3]),
            "created_at": str(party_row[4]) if party_row[4] is not None else None,
            "updated_at": str(party_row[5]) if party_row[5] is not None else None,
            "authority": "authoritative_party_record",
        },
        "identities": identities,
        "snapshot": {
            "measures": _json_object(snapshot_row[0]),
            "source_watermark": str(snapshot_row[1]) if snapshot_row[1] is not None else None,
            "rebuilt_at": str(snapshot_row[2]) if snapshot_row[2] is not None else None,
        } if snapshot_row else None,
        "timeline": timeline[:capped_limit],
        "authority_policy": {
            "party_record": "authoritative",
            "conversation_facts": "observation_only",
            "identity_resolution": "proposal_only_human_review",
        },
    }


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
    return _propose_identity_resolution(
        tenant_id=tenant_id,
        left_party_id=left_party_id,
        right_party_id=right_party_id,
        decision_type=f"link:{str(relationship_type or '').strip().lower()}",
        evidence=evidence,
        proposed_by=proposed_by,
    )


def _propose_identity_resolution(
    *,
    tenant_id: str,
    left_party_id: str,
    right_party_id: str,
    decision_type: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    left = str(left_party_id or "").strip()
    right = str(right_party_id or "").strip()
    kind = str(decision_type or "").strip().lower()
    actor = str(proposed_by or "").strip()
    if not tenant or not left or not right or not actor or left == right:
        raise ValueError("party_link_scope_required")
    if kind.startswith("link:") and kind.removeprefix("link:") not in RELATIONSHIP_TYPES:
        raise ValueError("unsupported_party_relationship")
    if not kind.startswith("link:") and kind not in IDENTITY_PROPOSAL_TYPES:
        raise ValueError("unsupported_identity_proposal")
    evidence_json = json.dumps(evidence or {}, sort_keys=True, separators=(",", ":"))
    proposal_id = hashlib.sha256(
        f"{tenant}|{kind}|{left}|{right}|{evidence_json}".encode()
    ).hexdigest()
    with db_session() as db:
        _require_party_pair(
            db, tenant_id=tenant, left_party_id=left, right_party_id=right
        )
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
                     status, evidence_json, proposed_at, proposed_by)
                    VALUES (:id,:tenant,:kind,:left,:right,'proposed',:evidence,
                            CURRENT_TIMESTAMP,:actor)
                    """
                ),
                {
                    "id": proposal_id,
                    "tenant": tenant,
                    "kind": kind,
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
        "decision_type": kind,
        "execution_allowed": False,
        "human_review_required": True,
    }


def propose_party_merge(
    *,
    tenant_id: str,
    left_party_id: str,
    right_party_id: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    """Record a human-review proposal. Approval still cannot execute a merge."""
    return _propose_identity_resolution(
        tenant_id=tenant_id,
        left_party_id=left_party_id,
        right_party_id=right_party_id,
        decision_type="merge_proposal",
        evidence=evidence,
        proposed_by=proposed_by,
    )


def propose_party_split(
    *,
    tenant_id: str,
    left_party_id: str,
    right_party_id: str,
    evidence: dict[str, Any],
    proposed_by: str,
) -> dict[str, Any]:
    """Propose separating identities/records between two parties; executes nothing."""
    return _propose_identity_resolution(
        tenant_id=tenant_id,
        left_party_id=left_party_id,
        right_party_id=right_party_id,
        decision_type="split_proposal",
        evidence=evidence,
        proposed_by=proposed_by,
    )


def list_identity_resolution_proposals(
    *,
    tenant_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    tenant = str(tenant_id or "").strip()
    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in {"proposed", *IDENTITY_RESOLUTIONS}:
        raise ValueError("unsupported_identity_resolution_status")
    where = "tenant_id=:tenant"
    params: dict[str, Any] = {"tenant": tenant, "limit": max(1, min(int(limit), 500))}
    if normalized_status:
        where += " AND status=:status"
        params["status"] = normalized_status
    with db_session() as db:
        rows = db.execute(
            text(
                f"""
                SELECT id, decision_type, left_party_id, right_party_id, status,
                       evidence_json, proposed_at, proposed_by, resolved_at,
                       resolved_by, resolution_note
                FROM identity_resolution_decision
                WHERE {where}
                ORDER BY proposed_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "decision_type": str(row[1]),
            "left_party_id": str(row[2]),
            "right_party_id": str(row[3]),
            "status": str(row[4]),
            "evidence": _json_object(row[5]),
            "proposed_at": str(row[6]),
            "proposed_by": row[7],
            "resolved_at": str(row[8]) if row[8] is not None else None,
            "resolved_by": row[9],
            "resolution_note": row[10],
            "execution_allowed": False,
            "human_review_required": True,
        }
        for row in rows
    ]


def resolve_identity_resolution_proposal(
    *,
    tenant_id: str,
    proposal_id: str,
    resolution: str,
    resolved_by: str,
    note: str,
) -> dict[str, Any]:
    """Record human disposition only. Approved proposals remain non-executable."""
    tenant = str(tenant_id or "").strip()
    proposal = str(proposal_id or "").strip()
    outcome = str(resolution or "").strip().lower()
    actor = str(resolved_by or "").strip()
    resolution_note = str(note or "").strip()
    if outcome not in IDENTITY_RESOLUTIONS:
        raise ValueError("unsupported_identity_resolution")
    if not all((tenant, proposal, actor, resolution_note)):
        raise ValueError("identity_resolution_scope_required")
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT decision_type, status
                FROM identity_resolution_decision
                WHERE tenant_id=:tenant AND id=:id
                """
            ),
            {"tenant": tenant, "id": proposal},
        ).fetchone()
        if not row:
            raise ValueError("identity_proposal_not_in_tenant")
        if str(row[1]) != "proposed":
            raise ValueError("identity_proposal_already_resolved")
        db.execute(
            text(
                """
                UPDATE identity_resolution_decision
                SET status=:status, resolved_at=CURRENT_TIMESTAMP,
                    resolved_by=:actor, resolution_note=:note
                WHERE tenant_id=:tenant AND id=:id AND status='proposed'
                """
            ),
            {
                "status": outcome,
                "actor": actor,
                "note": resolution_note,
                "tenant": tenant,
                "id": proposal,
            },
        )
        db.commit()
    return {
        "id": proposal,
        "decision_type": str(row[0]),
        "status": outcome,
        "resolved_by": actor,
        "resolution_note": resolution_note,
        "execution_allowed": False,
        "manual_execution_required": outcome == "approved",
    }


def _redirect_graph(db, *, tenant_id: str) -> tuple[int, dict[str, str], dict[str, Any]]:
    rows = db.execute(
        text(
            """
            SELECT id,event_type,source_party_id,target_party_id,
                   supersedes_event_id,graph_version
            FROM party_redirect_event
            WHERE tenant_id=:tenant
            ORDER BY graph_version,id
            """
        ),
        {"tenant": tenant_id},
    ).fetchall()
    superseded = {str(row[4]) for row in rows if row[4]}
    active_rows = [
        row for row in rows
        if str(row[1]) == "merge_redirect" and str(row[0]) not in superseded
    ]
    redirects = {str(row[2]): str(row[3]) for row in active_rows}
    active_by_pair = {
        (str(row[2]), str(row[3])): {
            "id": str(row[0]),
            "graph_version": int(row[5]),
        }
        for row in active_rows
    }
    return max((int(row[5]) for row in rows), default=0), redirects, active_by_pair


def _canonical_from_graph(party_id: str, redirects: dict[str, str]) -> str:
    current = party_id
    seen: set[str] = set()
    while current in redirects:
        if current in seen:
            raise ValueError("party_redirect_cycle_detected")
        seen.add(current)
        current = redirects[current]
    return current


def resolve_canonical_party(*, tenant_id: str, party_id: str) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    party = str(party_id or "").strip()
    with db_session() as db:
        if not _party_exists(db, tenant_id=tenant, party_id=party):
            raise ValueError("party_not_in_tenant")
        version, redirects, _ = _redirect_graph(db, tenant_id=tenant)
    canonical = _canonical_from_graph(party, redirects)
    path = [party]
    while path[-1] in redirects:
        path.append(redirects[path[-1]])
    return {
        "party_id": party,
        "canonical_party_id": canonical,
        "redirect_path": path,
        "graph_version": version,
        "redirected": canonical != party,
    }


def preview_identity_resolution_execution(
    *, tenant_id: str, proposal_id: str
) -> dict[str, Any]:
    """Return bounded impact counts without mutating Party-owned records."""
    tenant = str(tenant_id or "").strip()
    proposal = str(proposal_id or "").strip()
    with db_session() as db:
        row = db.execute(
            text(
                """
                SELECT decision_type,left_party_id,right_party_id,status,
                       proposed_by,resolved_by
                FROM identity_resolution_decision
                WHERE tenant_id=:tenant AND id=:proposal
                """
            ),
            {"tenant": tenant, "proposal": proposal},
        ).fetchone()
        if not row:
            raise ValueError("identity_proposal_not_in_tenant")
        kind, left, right = str(row[0]), str(row[1]), str(row[2])
        version, redirects, active_by_pair = _redirect_graph(db, tenant_id=tenant)
        canonical_left = _canonical_from_graph(left, redirects)
        canonical_right = _canonical_from_graph(right, redirects)
        tables = set(inspect(db.get_bind()).get_table_names())

        def count(table: str, predicate: str, params: dict[str, Any]) -> int:
            if table not in tables:
                return 0
            return int(
                db.execute(
                    text(f"SELECT COUNT(*) FROM {table} WHERE tenant_id=:tenant AND {predicate}"),
                    {"tenant": tenant, **params},
                ).scalar_one()
            )

        impacts = {
            "external_identities": count(
                "party_external_identity", "party_id=:party", {"party": left}
            ),
            "account_activities": count(
                "account_activity", "party_id=:party", {"party": left}
            ),
            "account_observations": count(
                "account_observation", "party_id=:party", {"party": left}
            ),
            "account_snapshots": count(
                "account_intelligence_snapshot", "party_id=:party", {"party": left}
            ),
            "relationships": count(
                "party_relationship",
                "(from_party_id=:party OR to_party_id=:party)",
                {"party": left},
            ),
        }
        reversal = (
            active_by_pair.get((left, right))
            or active_by_pair.get((right, left))
            if kind == "split_proposal"
            else None
        )
    conflicts: list[str] = []
    if kind == "merge_proposal":
        if canonical_left == canonical_right:
            conflicts.append("parties_already_resolve_to_same_canonical_party")
        if canonical_left != left:
            conflicts.append("source_party_already_redirected")
        if canonical_right == left:
            conflicts.append("merge_would_create_redirect_cycle")
    elif kind == "split_proposal" and reversal is None:
        conflicts.append("active_merge_redirect_not_found")
    else:
        if kind not in IDENTITY_PROPOSAL_TYPES:
            conflicts.append("proposal_type_is_not_executable")
    return {
        "proposal_id": proposal,
        "decision_type": kind,
        "status": str(row[3]),
        "source_party_id": left,
        "target_party_id": right,
        "canonical_source_party_id": canonical_left,
        "canonical_target_party_id": canonical_right,
        "graph_version": version,
        "impact_counts": impacts,
        "conflicts": conflicts,
        "executable": str(row[3]) == "approved" and not conflicts,
        "execution_policy": {
            "moves_historical_records": False,
            "append_only_redirect": True,
            "separate_owner_execution_required": True,
            "proposal_creator_may_execute": False,
        },
    }


def execute_identity_resolution_proposal(
    *,
    tenant_id: str,
    proposal_id: str,
    executed_by: str,
    expected_version: int,
    idempotency_key: str,
    note: str,
) -> dict[str, Any]:
    """Append a merge redirect or a split reversal after a separate approval."""
    tenant = str(tenant_id or "").strip()
    proposal = str(proposal_id or "").strip()
    actor = str(executed_by or "").strip()
    key = str(idempotency_key or "").strip()
    execution_note = str(note or "").strip()
    if not all((tenant, proposal, actor, key, execution_note)):
        raise ValueError("identity_execution_scope_required")
    if len(key) > 200:
        raise ValueError("identity_execution_idempotency_key_too_long")
    with db_session() as db:
        replay = db.execute(
            text(
                """
                SELECT id,proposal_id,event_type,source_party_id,target_party_id,
                       graph_version,executed_by,supersedes_event_id
                FROM party_redirect_event
                WHERE tenant_id=:tenant AND idempotency_key=:key
                """
            ),
            {"tenant": tenant, "key": key},
        ).fetchone()
        if replay:
            if str(replay[1]) != proposal or str(replay[6]) != actor:
                raise ValueError("identity_execution_idempotency_conflict")
            return {
                "event_id": str(replay[0]),
                "proposal_id": str(replay[1]),
                "event_type": str(replay[2]),
                "source_party_id": str(replay[3]),
                "target_party_id": str(replay[4]),
                "graph_version": int(replay[5]),
                "supersedes_event_id": str(replay[7]) if replay[7] else None,
                "idempotent_replay": True,
                "historical_records_moved": False,
            }
        decision = db.execute(
            text(
                """
                SELECT decision_type,left_party_id,right_party_id,status,proposed_by
                FROM identity_resolution_decision
                WHERE tenant_id=:tenant AND id=:proposal
                """
            ),
            {"tenant": tenant, "proposal": proposal},
        ).fetchone()
        if not decision:
            raise ValueError("identity_proposal_not_in_tenant")
        kind, left, right = (
            str(decision[0]), str(decision[1]), str(decision[2])
        )
        if str(decision[3]) != "approved":
            raise ValueError("identity_proposal_not_approved")
        if str(decision[4] or "") == actor:
            raise ValueError("identity_execution_four_eyes_required")
        version, redirects, active_by_pair = _redirect_graph(db, tenant_id=tenant)
        if int(expected_version) != version:
            raise ValueError("identity_graph_version_conflict")
        supersedes_event_id = None
        if kind == "merge_proposal":
            canonical_left = _canonical_from_graph(left, redirects)
            canonical_right = _canonical_from_graph(right, redirects)
            if canonical_left == canonical_right:
                raise ValueError("identity_parties_already_merged")
            if canonical_left != left:
                raise ValueError("source_party_already_redirected")
            if canonical_right == left:
                raise ValueError("party_redirect_cycle_detected")
            source, target = left, canonical_right
            event_type = "merge_redirect"
        elif kind == "split_proposal":
            active = active_by_pair.get((left, right))
            if active is None:
                active = active_by_pair.get((right, left))
            if active is None:
                raise ValueError("active_merge_redirect_not_found")
            source, target = (
                (left, right) if (left, right) in active_by_pair else (right, left)
            )
            supersedes_event_id = str(active["id"])
            event_type = "split_reversal"
        else:
            raise ValueError("proposal_type_is_not_executable")
        next_version = version + 1
        event_id = hashlib.sha256(
            f"{tenant}|{proposal}|{event_type}|{next_version}|{key}".encode()
        ).hexdigest()
        try:
            db.execute(
                text(
                    """
                    INSERT INTO party_redirect_event
                    (id,tenant_id,proposal_id,event_type,source_party_id,target_party_id,
                     supersedes_event_id,graph_version,idempotency_key,executed_by,
                     execution_note)
                    VALUES
                    (:id,:tenant,:proposal,:event_type,:source,:target,:supersedes,
                     :version,:key,:actor,:note)
                    """
                ),
                {
                    "id": event_id,
                    "tenant": tenant,
                    "proposal": proposal,
                    "event_type": event_type,
                    "source": source,
                    "target": target,
                    "supersedes": supersedes_event_id,
                    "version": next_version,
                    "key": key,
                    "actor": actor,
                    "note": execution_note,
                },
            )
        except IntegrityError as exc:
            db.rollback()
            concurrent = db.execute(
                text(
                    """
                    SELECT id,proposal_id,event_type,source_party_id,target_party_id,
                           graph_version,executed_by,supersedes_event_id
                    FROM party_redirect_event
                    WHERE tenant_id=:tenant AND idempotency_key=:key
                    """
                ),
                {"tenant": tenant, "key": key},
            ).fetchone()
            if concurrent and (
                str(concurrent[1]) != proposal or str(concurrent[6]) != actor
            ):
                raise ValueError("identity_execution_idempotency_conflict") from exc
            if concurrent:
                return {
                    "event_id": str(concurrent[0]),
                    "proposal_id": str(concurrent[1]),
                    "event_type": str(concurrent[2]),
                    "source_party_id": str(concurrent[3]),
                    "target_party_id": str(concurrent[4]),
                    "graph_version": int(concurrent[5]),
                    "supersedes_event_id": (
                        str(concurrent[7]) if concurrent[7] else None
                    ),
                    "idempotent_replay": True,
                    "historical_records_moved": False,
                }
            raise ValueError("identity_graph_version_conflict") from exc
        db.commit()
    return {
        "event_id": event_id,
        "proposal_id": proposal,
        "event_type": event_type,
        "source_party_id": source,
        "target_party_id": target,
        "graph_version": next_version,
        "supersedes_event_id": supersedes_event_id,
        "idempotent_replay": False,
        "historical_records_moved": False,
    }
