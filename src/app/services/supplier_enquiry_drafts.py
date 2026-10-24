"""Immutable versions of the same supplier composition used by chat previews.

The workflow owns commits. Versions never confer approval, resolve recipients,
or enqueue messages. Old enquiries remain explicitly legacy compositions.
"""

import hashlib
import json

from sqlalchemy import inspect, text


DDL = """CREATE TABLE IF NOT EXISTS supplier_enquiry_draft (
 tenant_id TEXT NOT NULL,enquiry_id TEXT NOT NULL,version INTEGER NOT NULL,
 content_hash TEXT NOT NULL,draft_json TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,enquiry_id,version))"""


def seal(content):
    value = {key: item for key, item in content.items() if key != "content_hash"}
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**value, "content_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def canonical_state(db, row):
    fallback = dict(
        case_id=row["case_id"],
        revision=row["case_revision"],
        requested_quantity=row["requested_quantity"],
    )
    if not inspect(db.connection()).has_table("conversation_case_state"):
        return fallback
    rows = (
        db.execute(
            text(
                "SELECT state_json FROM conversation_case_state WHERE tenant_id=:tenant "
                "AND case_id=:case AND version=:revision"
            ),
            dict(tenant=row["tenant_id"], case=row["case_id"], revision=row["case_revision"]),
        )
        .scalars()
        .all()
    )
    if not rows:
        return fallback
    states = [json.loads(raw).get("procurement_case_state") or {} for raw in rows]
    if any(value != states[0] for value in states[1:]):
        raise ValueError("enquiry_case_state_ambiguous")
    state = states[0]
    if any(state.get(key) != value for key, value in fallback.items()):
        raise ValueError("enquiry_case_state_stale")
    return state


def compose(db, row, *, now, include_budget=True):
    from src.app.services.shortfall_enquiry_preview import shortfall_draft

    preview = shortfall_draft(
        db,
        tenant_id=row["tenant_id"],
        case_id=row["case_id"],
        revision=row["case_revision"],
        state=canonical_state(db, row),
        now=now,
        include_budget=include_budget,
    )
    if preview["shortfall"] != row["shortfall"] or preview.get("sku") != row["sku"]:
        raise ValueError("enquiry_draft_selection_stale")
    return preview["draft_artifact"]


def append(db, row, artifact, *, version, now):
    db.execute(
        text(
            "INSERT INTO supplier_enquiry_draft "
            "(tenant_id,enquiry_id,version,content_hash,draft_json,created_at) "
            "VALUES (:tenant,:id,:version,:hash,:draft,:now)"
        ),
        dict(
            tenant=row["tenant_id"],
            id=row["id"],
            version=version,
            hash=artifact["content_hash"],
            draft=json.dumps(artifact, ensure_ascii=False),
            now=now.isoformat(),
        ),
    )


def load(db, row):
    if not inspect(db.connection()).has_table("supplier_enquiry_draft"):
        return None
    stored = db.execute(
        text(
            "SELECT version,content_hash,draft_json FROM supplier_enquiry_draft "
            "WHERE tenant_id=:tenant AND enquiry_id=:id ORDER BY version DESC LIMIT 1"
        ),
        dict(tenant=row["tenant_id"], id=row["id"]),
    ).first()
    if not stored:
        return None
    artifact = json.loads(stored[2])
    if seal(artifact)["content_hash"] != stored[1] or artifact.get("content_hash") != stored[1]:
        raise ValueError("enquiry_draft_integrity_failed")
    for key in ("tenant_id", "case_id", "case_revision", "requested_quantity", "shortfall", "sku"):
        if artifact.get(key) != row[key]:
            raise ValueError("enquiry_draft_binding_failed")
    return dict(draft_version=int(stored[0]), draft_artifact=artifact)


def revise(db, row, *, expected_version, include_budget, operator_principal, now):
    from src.app.services.fulfillment import person_approval as approval, outbound_queue as queue

    approval._person(db, row["tenant_id"], operator_principal)
    if not isinstance(include_budget, bool):
        raise ValueError("budget_disclosure_choice_required")
    stored = load(db, row)
    if not stored or stored["draft_version"] != expected_version:
        raise ValueError("draft_version_conflict")
    if queue.get_by_key(
        db, tenant_id=row["tenant_id"], idempotency_key="supplier-enquiry:" + row["id"]
    ):
        raise ValueError("draft_already_queued")
    artifact = compose(db, row, now=now, include_budget=include_budget)
    if artifact["content_hash"] == stored["draft_artifact"]["content_hash"]:
        return
    if row["approval_id"]:
        approval.revoke(
            db,
            tenant_id=row["tenant_id"],
            approval_id=row["approval_id"],
            revoked_by=operator_principal,
            now=now,
        )
    changed = db.execute(
        text(
            "UPDATE supplier_enquiry_request SET status='pending',approval_id=NULL,requester_principal=:editor "
            "WHERE tenant_id=:tenant AND id=:id AND status=:status"
        ),
        dict(
            tenant=row["tenant_id"], id=row["id"], status=row["status"], editor=operator_principal
        ),
    )
    if changed.rowcount != 1:
        raise ValueError("enquiry_draft_edit_conflict")
    append(db, row, artifact, version=expected_version + 1, now=now)
