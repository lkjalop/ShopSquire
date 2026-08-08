"""Canonical, tenant-scoped conversation case state and append-only amendments.

Language models may propose the same typed structure, but only this reducer can
accept it.  Commerce execution remains outside this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import inspect, text


_STATUS = re.compile(r"\b(status|summary|where (?:is|are)|what(?:'s| is) happening)\b", re.I)
_DESTINATION = re.compile(
    r"\b(?:actually\s+|correction:\s*)?(?:send|ship|deliver)(?:\s+(?:it|them|the order))?\s+to\s+"
    r"(?P<destination>[A-Za-z0-9][A-Za-z0-9 .,'\-/]{1,100}?)(?=[.!?]|$)",
    re.I,
)
_QUANTITY_TO = re.compile(
    r"\b(?:set|change|increase|raise|update|reduce)(?:\s+(?:the|my|order|total|it))?\s*"
    r"(?:quantity|units?)\s+to\s+(?P<quantity>\d{1,7})\b",
    re.I,
)
_QUANTITY_REDUCE_TO = re.compile(
    r"\b(?:reduce|decrease|lower|cut)(?:\s+(?:the|my|order|total|quantity|units?))?"
    r"\s+(?:it\s+)?to\s+(?P<quantity>\d{1,7})(?:\s+units?)?\b",
    re.I,
)
_QUANTITY_REDUCE_BY = re.compile(
    r"\b(?:reduce|decrease|lower|cut)(?:\s+(?:the|my|order|total|quantity|units?|it))?"
    r"\s+by\s+(?P<quantity>\d{1,7})(?:\s+units?)?\b",
    re.I,
)
_DOUBLE = re.compile(r"\b(?:make|double)\s+(?:it|the quantity|the units?)\s*(?:double)?\b", re.I)
_DEADLINE = re.compile(
    r"\b(?:need|deliver|delivery|arrive|required)(?:\s+it|\s+them|\s+the order)?\s+"
    r"(?:by|before|no later than)\s+(?P<deadline>[^,.!?;]{2,80})",
    re.I,
)
_BUDGET_TOTAL = re.compile(r"\btotal\s+(?:budget\s+)?for\s+all\s+(?P<count>\d{1,7})\b", re.I)
_SKU = re.compile(r"\b(?P<sku>[A-Z][A-Z0-9]{1,15}-[A-Z0-9]{2,20})\b")
_COMMITMENT = re.compile(
    r"\b(?:"
    r"(?:confirm|commit|approve)(?:\s+(?:the|this|my))?\s*"
    r"(?:purchase\s+order|order|purchase|selection)?"
    r"|place(?:\s+(?:the|this|my))?\s+(?:purchase\s+order|order|purchase)"
    r")\b",
    re.I,
)
_PAYMENT = re.compile(
    r"\b(?:pay|payment|deposit|invoice|net[- ]?(?:7|15|30|45|60|90)|"
    r"authorization\s+hold|payment\s+plan|finance|financing)\b",
    re.I,
)
_PRODUCT_SELECTION = re.compile(
    r"\b(?:choose|select|pick)\b(?:\s+(?:this|that|the|it))?",
    re.I,
)
_POLICY_QUESTION = re.compile(
    r"\b(?:return|refund|exchange|warrant(?:y|ies)|repair)\b.*\b(?:policy|terms?|window|"
    r"eligible|eligibility|covered|coverage|fee|fees|how long)\b|"
    r"\b(?:policy|terms?|window|eligible|eligibility|covered|coverage|fee|fees|how long)\b.*"
    r"\b(?:return|refund|exchange|warrant(?:y|ies)|repair)\b",
    re.I,
)
_SUPPORT_QUESTION = re.compile(
    r"\b(?:my|this|the)\s+(?:order|laptop|product|item|device)\b.*"
    r"\b(?:broken|damaged|faulty|return|refund|repair|warrant(?:y|ies)|claim|support)\b|"
    r"\b(?:file|submit|start|open|make)\b.*\b(?:return|refund|repair|warranty|claim|case)\b",
    re.I,
)
_SUPPLIER_STATUS = re.compile(
    r"\b(?:supplier|vendor|rfq|quote|sourcing)\b.*\b(?:status|respond(?:ed)?|reply|replied|"
    r"heard back|eta|arrival|confirmed|confirmation|waiting|pending|update)\b|"
    r"\b(?:status|respond(?:ed)?|reply|replied|heard back|eta|arrival|confirmed|confirmation|"
    r"waiting|pending|update)\b.*\b(?:supplier|vendor|rfq|quote|sourcing)\b",
    re.I,
)


@dataclass(frozen=True)
class CaseTurn:
    dialogue_act: str
    field_name: str | None
    proposed_value: Any
    confidence: float
    risk: str
    requires_confirmation: bool
    reason: str
    retrieval_required: bool = False


def decompose_case_obligations(
    message: str, *, current_state: dict[str, Any], allow_unselected_quantity: bool = False,
) -> tuple[dict[str, Any], ...]:
    """Return every bounded obligation in a mixed commerce turn.

    This is deliberately a recognizer, not an executor.  It prevents the first matched intent
    from swallowing later consequential requests while leaving acceptance to the canonical
    reducer and policy boundaries.
    """
    source = re.sub(r"\s+", " ", str(message or "")).strip()
    if not source:
        return ()
    obligations: list[dict[str, Any]] = []

    def append(kind: str, *, operation: CaseTurn | None = None) -> None:
        row: dict[str, Any] = {
            "kind": kind,
            "authority": "proposed",
            "requires_reducer": True,
        }
        if operation is not None:
            row.update({
                "dialogue_act": operation.dialogue_act,
                "field_name": operation.field_name,
                "proposed_value": operation.proposed_value,
                "requires_confirmation": operation.requires_confirmation,
                "reason": operation.reason,
            })
        obligations.append(row)

    # Field amendments are evaluated independently so a deadline cannot hide a quantity change.
    field_patterns = (
        ("quantity_amendment", _QUANTITY_REDUCE_BY),
        ("quantity_amendment", _QUANTITY_REDUCE_TO),
        ("quantity_amendment", _QUANTITY_TO),
        ("destination", _DESTINATION),
        ("deadline", _DEADLINE),
        ("budget_scope", _BUDGET_TOTAL),
    )
    for kind, pattern in field_patterns:
        match = pattern.search(source)
        if not match:
            continue
        operation = classify_case_turn(
            match.group(0),
            current_state=current_state,
            allow_unselected_quantity=allow_unselected_quantity,
        )
        append(kind, operation=operation)

    if _PRODUCT_SELECTION.search(source) or _SKU.search(source):
        append("product_selection")
    if _COMMITMENT.search(source):
        append("buyer_commitment")
    if _PAYMENT.search(source):
        append("payment_request")
    if _POLICY_QUESTION.search(source):
        append("policy_question")
    if _SUPPORT_QUESTION.search(source):
        append("support_question")
    if _SUPPLIER_STATUS.search(source):
        append("supplier_status")
    return tuple(obligations)


def reduce_case_obligations(
    message: str,
    *,
    current_state: dict[str, Any],
    catalog_authority: str,
    selected_sku_candidate: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Validate every obligation in a mixed turn without granting commerce authority.

    The recognizer above is a bounded fallback for explicit money/quantity/date/identity
    grammar. A model may eventually propose the same obligation envelope, but this reducer
    owns ordering, case consistency and authority. Later obligations cannot leapfrog an
    amendment that still needs confirmation.
    """
    authority_permitted = str(catalog_authority or "").strip().lower() == "permitted"
    proposed = decompose_case_obligations(
        message,
        current_state=current_state,
        allow_unselected_quantity=not authority_permitted,
    )
    if not proposed:
        return ()
    rows: list[dict[str, Any]] = []
    pending_dependency = False
    effective_sku = str(
        selected_sku_candidate
        or current_state.get("sku")
        or current_state.get("product_sku")
        or ""
    ).strip()
    atp = current_state.get("atp_snapshot")
    versioned_atp = bool(
        isinstance(atp, dict)
        and str(atp.get("source_version") or "").strip()
        and str(atp.get("observed_at") or "").strip()
    )

    for obligation in proposed:
        row = dict(obligation)
        kind = str(row.get("kind") or "")
        row["authorization_granted"] = False
        if pending_dependency and kind in {"buyer_commitment", "payment_request"}:
            row.update(
                status="blocked",
                reason="prior_obligation_requires_confirmation",
                residual_route="ASK",
            )
            rows.append(row)
            continue
        if kind == "product_selection":
            if not authority_permitted:
                row.update(
                    status="blocked",
                    reason="catalog_authority_blocked",
                    residual_route="ASK",
                )
            elif not str(selected_sku_candidate or "").strip():
                row.update(
                    status="clarify",
                    reason="explicit_catalog_sku_selection_required",
                    residual_route="ASK",
                )
            else:
                row.update(
                    status="accepted",
                    reason="explicit_qualified_sku_selected",
                    residual_route="CONNECTOR",
                    field_name="sku",
                    proposed_value=str(selected_sku_candidate),
                )
            rows.append(row)
            continue
        if kind in {"quantity_amendment", "destination", "deadline", "budget_scope"}:
            if row.get("dialogue_act") == "clarify":
                row.update(status="clarify", residual_route="ASK")
            elif bool(row.get("requires_confirmation")):
                row.update(status="pending_confirmation", residual_route="ASK")
                pending_dependency = True
            else:
                row.update(status="accepted", residual_route="CONNECTOR")
            rows.append(row)
            continue
        if kind == "buyer_commitment":
            # Carry the exact authority inputs into the decision trace.  These are
            # references to the sealed case state, not fresh claims inferred from
            # the buyer's wording.
            row.update(
                selected_sku=effective_sku or None,
                quantity=current_state.get("quantity"),
                atp_snapshot=dict(atp) if isinstance(atp, dict) else None,
            )
            if not authority_permitted:
                row.update(status="blocked", reason="catalog_authority_blocked", residual_route="ASK")
            elif not effective_sku:
                row.update(status="blocked", reason="selected_product_anchor_required", residual_route="ASK")
            elif not isinstance(current_state.get("quantity"), int) or current_state["quantity"] <= 0:
                row.update(status="blocked", reason="quantity_anchor_required", residual_route="ASK")
            elif not versioned_atp:
                row.update(status="blocked", reason="versioned_atp_snapshot_required", residual_route="CONNECTOR")
            else:
                row.update(
                    status="authorization_required",
                    reason="buyer_commitment_requires_policy",
                    residual_route="AUTHORIZE",
                )
            rows.append(row)
            continue
        if kind == "payment_request":
            row.update(
                status="authorization_required",
                reason="payment_terms_require_policy_and_provider",
                residual_route="AUTHORIZE",
            )
            rows.append(row)
            continue
        if kind in {"policy_question", "support_question"}:
            row.update(
                status="read_only",
                reason="approved_facts_or_handoff_only",
                residual_route="POLICY" if kind == "policy_question" else "SUPPORT",
            )
            rows.append(row)
            continue
        if kind == "supplier_status":
            has_anchor = bool(
                current_state.get("rfq_ref")
                or current_state.get("case_id")
                or current_state.get("last_sourcing_intent")
            )
            row.update(
                status="read_only" if has_anchor else "clarify",
                reason=(
                    "persisted_sourcing_status_required"
                    if has_anchor else "sourcing_case_anchor_required"
                ),
                residual_route="CONNECTOR" if has_anchor else "ASK",
            )
            rows.append(row)
            continue
        row.update(status="clarify", reason="unsupported_obligation", residual_route="ASK")
        rows.append(row)
    return tuple(rows)


def _now(value: str | None = None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class _DurableOnlyCache:
    """The DB pointer fails closed even when no provider cache adapter is in this call path."""

    @staticmethod
    def delete(_key: str) -> None:
        return None


def _propagate_case_supersession(
    db,
    *,
    tenant_id: str,
    case_id: str,
    amendment_id: str,
    trace_id: str | None,
    prior_version: int,
    new_version: int,
    timestamp: str,
) -> dict[str, Any]:
    """Invalidate exact prior-version consumers and expose one evidence-only graph edge."""
    tables = set(inspect(db.connection()).get_table_names())
    temporal: dict[str, Any] = {"invalidated_count": 0, "rebuilds_enqueued": 0}
    if "temporal_dependency" in tables:
        from src.app.services.temporal_invalidation import (
            invalidate_source_and_schedule_rebuild,
            invalidate_source_dependencies,
        )

        values = {
            "tenant_id": tenant_id,
            "source_type": "conversation_case_state",
            "source_id": case_id,
            "source_version": str(prior_version),
            "reason": f"case_amended:{amendment_id}",
        }
        if {"temporal_cache_entry", "temporal_cache_rebuild_job"}.issubset(tables):
            temporal = invalidate_source_and_schedule_rebuild(
                db, cache=_DurableOnlyCache(), **values
            )
        else:
            temporal = invalidate_source_dependencies(db, **values)

    if trace_id and "decision_trace_events" in tables:
        columns = {
            item["name"]
            for item in inspect(db.connection()).get_columns("decision_trace_events")
        }
        event_id = hashlib.sha256(
            f"{tenant_id}|{case_id}|{prior_version}|{new_version}|{amendment_id}".encode()
        ).hexdigest()
        values = {
            "id": event_id,
            "trace": trace_id,
            "event": "case_revision_superseded",
            "source_type": "case_revision",
            "source_id": f"{case_id}@v{prior_version}",
            "target_type": "case_revision",
            "target_id": f"{case_id}@v{new_version}",
            "payload": _json({
                "amendment_id": amendment_id,
                "superseded_version": prior_version,
                "active_version": new_version,
                "authority": "evidence_only",
            }),
            "created": timestamp,
            "tenant": tenant_id,
        }
        names = [
            "id", "trace_id", "event_type", "source_type", "source_id",
            "target_type", "target_id", "payload", "created_at",
        ]
        params = [
            ":id", ":trace", ":event", ":source_type", ":source_id",
            ":target_type", ":target_id", ":payload", ":created",
        ]
        if "tenant_id" in columns:
            names.append("tenant_id")
            params.append(":tenant")
        db.execute(
            text(
                f"INSERT INTO decision_trace_events ({','.join(names)}) "
                f"VALUES ({','.join(params)})"
            ),
            values,
        )
    return temporal


def classify_case_turn(
    message: str,
    *,
    current_state: dict[str, Any],
    allow_unselected_quantity: bool = False,
) -> CaseTurn:
    """Classify the bounded amendment vocabulary without mutating state."""
    source = re.sub(r"\s+", " ", str(message or "")).strip()
    if not source:
        return CaseTurn("clarify", None, None, 1.0, "none", False, "empty_message")
    if _STATUS.search(source):
        return CaseTurn("request_status", None, None, 0.98, "none", False, "read_existing_case")
    case_status = str(current_state.get("case_status") or "").strip().lower()
    consequential_case = case_status in {
        "committed",
        "allocated",
        "rfq_approved",
        "po_approved",
        "payment_authorized",
        "in_fulfillment",
    }
    match = _DESTINATION.search(source)
    if match:
        return CaseTurn(
            "amend_destination", "destination", match.group("destination").strip(),
            0.97,
            "high" if consequential_case else "low",
            consequential_case,
            "explicit_destination",
        )
    match = _QUANTITY_REDUCE_BY.search(source)
    if match:
        if (
            not allow_unselected_quantity
            and not str(current_state.get("sku") or current_state.get("product_sku") or "").strip()
        ):
            return CaseTurn(
                "clarify", "quantity", None, 1.0, "medium", False,
                "selected_product_anchor_required",
            )
        current_quantity = current_state.get("quantity")
        if not isinstance(current_quantity, int) or current_quantity <= 0:
            return CaseTurn(
                "clarify", "quantity", None, 1.0, "medium", False,
                "quantity_anchor_required",
            )
        delta = int(match.group("quantity"))
        if delta <= 0 or delta >= current_quantity:
            return CaseTurn(
                "clarify", "quantity", None, 1.0, "medium", False,
                "relative_quantity_out_of_bounds",
            )
        return CaseTurn(
            "amend_quantity", "quantity", current_quantity - delta,
            1.0, "medium", True, "relative_quantity_reduction",
        )
    match = _QUANTITY_REDUCE_TO.search(source)
    if match:
        if (
            not allow_unselected_quantity
            and not str(current_state.get("sku") or current_state.get("product_sku") or "").strip()
        ):
            return CaseTurn(
                "clarify", "quantity", None, 1.0, "medium", False,
                "selected_product_anchor_required",
            )
        return CaseTurn(
            "amend_quantity", "quantity", int(match.group("quantity")),
            1.0, "medium", True, "absolute_quantity",
        )
    match = _QUANTITY_TO.search(source)
    if match:
        return CaseTurn(
            "amend_quantity", "quantity", int(match.group("quantity")),
            0.99, "medium", True, "explicit_quantity",
        )
    if _DOUBLE.search(source):
        quantity = current_state.get("quantity")
        if not isinstance(quantity, int) or quantity <= 0:
            return CaseTurn("clarify", "quantity", None, 0.4, "medium", False, "quantity_anchor_required")
        return CaseTurn("amend_quantity", "quantity", quantity * 2, 0.82, "medium", True, "single_quantity_anchor")
    match = _DEADLINE.search(source)
    if match:
        return CaseTurn(
            "amend_deadline", "deadline", match.group("deadline").strip(),
            0.9,
            "high" if consequential_case else "low",
            consequential_case,
            "explicit_deadline",
        )
    match = _BUDGET_TOTAL.search(source)
    if match:
        current = current_state.get("budget") if isinstance(current_state.get("budget"), dict) else {}
        return CaseTurn(
            "amend_budget_scope", "budget",
            {**current, "scope": "total", "quantity_scope": int(match.group("count"))},
            0.98, "low", False, "explicit_total_scope",
        )
    match = _SKU.search(source)
    if match and match.group("sku") != current_state.get("sku"):
        return CaseTurn(
            "amend_product", "sku", match.group("sku"), 0.99,
            "high", True, "explicit_sku_change", retrieval_required=True,
        )
    return CaseTurn("clarify", None, None, 0.35, "none", False, "unsupported_or_ambiguous_turn")


def ensure_case_state(
    db,
    *,
    tenant_id: str,
    case_id: str,
    session_epoch: str,
    subject_ref: str,
    authoritative_anchor: dict[str, Any],
    now_iso: str | None = None,
) -> dict[str, Any]:
    if not all(str(value or "").strip() for value in (tenant_id, case_id, session_epoch, subject_ref)):
        raise ValueError("conversation_case_scope_required")
    timestamp = _now(now_iso)
    row = db.execute(
        text(
            "SELECT id,version,state_json FROM conversation_case_state "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND session_epoch=:epoch"
        ),
        {"tenant": tenant_id, "case_id": case_id, "epoch": session_epoch},
    ).first()
    if row:
        return {"case_state_id": row[0], "version": int(row[1]), "state": json.loads(row[2]), "created": False}
    state_id = f"ccs-{uuid.uuid4().hex}"
    state = {key: value for key, value in authoritative_anchor.items() if value is not None}
    db.execute(
        text(
            "INSERT INTO conversation_case_state "
            "(id,tenant_id,case_id,session_epoch,subject_ref,version,state_json,created_at,updated_at) "
            "VALUES (:id,:tenant,:case_id,:epoch,:subject,1,:state,:timestamp,:timestamp)"
        ),
        {
            "id": state_id, "tenant": tenant_id, "case_id": case_id, "epoch": session_epoch,
            "subject": subject_ref, "state": _json(state), "timestamp": timestamp,
        },
    )
    db.commit()
    return {"case_state_id": state_id, "version": 1, "state": state, "created": True}


def get_case_state(db, *, tenant_id: str, case_id: str, session_epoch: str) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT state_json FROM conversation_case_state "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND session_epoch=:epoch"
        ),
        {"tenant": tenant_id, "case_id": case_id, "epoch": session_epoch},
    ).first()
    return json.loads(row[0]) if row else {}


def record_case_turn(
    db,
    *,
    tenant_id: str,
    case_id: str,
    session_epoch: str,
    subject_ref: str,
    source_message_id: str,
    message: str,
    trace_id: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT id,state_json,version FROM conversation_case_state "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND session_epoch=:epoch AND subject_ref=:subject"
        ),
        {"tenant": tenant_id, "case_id": case_id, "epoch": session_epoch, "subject": subject_ref},
    ).first()
    if not row:
        raise ValueError("conversation_case_not_found")
    current = json.loads(row[1])
    turn = classify_case_turn(message, current_state=current)
    timestamp = _now(now_iso)
    identity = f"{tenant_id}|{session_epoch}|{source_message_id}|{turn.dialogue_act}|{turn.field_name or ''}"
    amendment_id = hashlib.sha256(identity.encode()).hexdigest()
    prior = None
    if turn.field_name:
        prior = db.execute(
            text(
                "SELECT id FROM conversation_case_amendment WHERE case_state_id=:state_id "
                "AND field_name=:field AND status='accepted' ORDER BY effective_at DESC LIMIT 1"
            ),
            {"state_id": row[0], "field": turn.field_name},
        ).first()
    status = "observed" if turn.field_name is None else (
        "pending_confirmation" if turn.requires_confirmation else "accepted"
    )
    existing = db.execute(
        text("SELECT status FROM conversation_case_amendment WHERE id=:id"), {"id": amendment_id}
    ).first()
    if existing:
        return {
            "amendment_id": amendment_id, "dialogue_act": turn.dialogue_act,
            "status": existing[0], "state_changed": False, "idempotent": True,
            "retrieval_required": turn.retrieval_required,
        }
    db.execute(
        text(
            "INSERT INTO conversation_case_amendment "
            "(id,case_state_id,tenant_id,case_id,session_epoch,source_message_id,trace_id,dialogue_act,"
            "field_name,old_value_json,proposed_value_json,confidence,risk,requires_confirmation,status,reason,"
            "provenance_json,supersedes_id,observed_at,effective_at,created_at) VALUES "
            "(:id,:state_id,:tenant,:case_id,:epoch,:message,:trace,:act,:field,:old,:proposed,:confidence,"
            ":risk,:confirmation,:status,:reason,:provenance,:supersedes,:observed,:effective,:created)"
        ),
        {
            "id": amendment_id, "state_id": row[0], "tenant": tenant_id, "case_id": case_id,
            "epoch": session_epoch, "message": source_message_id, "trace": trace_id,
            "act": turn.dialogue_act, "field": turn.field_name,
            "old": _json(current.get(turn.field_name)) if turn.field_name else None,
            "proposed": _json(turn.proposed_value), "confidence": turn.confidence, "risk": turn.risk,
            # Bind the semantic type. SQLite accepts bool for its integer affinity;
            # PostgreSQL requires bool for the migration-owned BOOLEAN column.
            "confirmation": bool(turn.requires_confirmation), "status": status, "reason": turn.reason,
            "provenance": _json({"kind": "buyer_conversation", "source_message_id": source_message_id, "classifier": "bounded_case_turns_v1"}),
            "supersedes": prior[0] if prior and status == "accepted" else None,
            "observed": timestamp, "effective": timestamp if status == "accepted" else None, "created": timestamp,
        },
    )
    state_changed = False
    if status == "accepted" and turn.field_name:
        if prior:
            db.execute(text("UPDATE conversation_case_amendment SET status='superseded' WHERE id=:id"), {"id": prior[0]})
        current[turn.field_name] = turn.proposed_value
        changed = db.execute(
            text(
                "UPDATE conversation_case_state SET state_json=:state,version=version+1,updated_at=:timestamp "
                "WHERE id=:id"
            ),
            {"state": _json(current), "timestamp": timestamp, "id": row[0]},
        ).rowcount
        state_changed = changed == 1
        if state_changed:
            _propagate_case_supersession(
                db,
                tenant_id=tenant_id,
                case_id=case_id,
                amendment_id=amendment_id,
                trace_id=trace_id,
                prior_version=int(row[2]),
                new_version=int(row[2]) + 1,
                timestamp=timestamp,
            )
    db.commit()
    return {
        "amendment_id": amendment_id, "dialogue_act": turn.dialogue_act,
        "status": status, "state_changed": state_changed, "idempotent": False,
        "requires_confirmation": turn.requires_confirmation,
        "retrieval_required": turn.retrieval_required, "reason": turn.reason,
    }


def apply_case_amendment(
    db,
    *,
    tenant_id: str,
    case_id: str,
    session_epoch: str,
    amendment_id: str,
    actor_id: str,
    now_iso: str | None = None,
) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT a.case_state_id,a.field_name,a.proposed_value_json,a.status,s.state_json,"
            "s.version,a.trace_id "
            "FROM conversation_case_amendment a JOIN conversation_case_state s ON s.id=a.case_state_id "
            "WHERE a.id=:id AND a.tenant_id=:tenant AND a.case_id=:case_id AND a.session_epoch=:epoch"
        ),
        {"id": amendment_id, "tenant": tenant_id, "case_id": case_id, "epoch": session_epoch},
    ).first()
    if not row:
        return {"ok": False, "reason": "amendment_not_found", "state_changed": False}
    if row[3] == "accepted":
        return {"ok": True, "idempotent": True, "state_changed": False}
    if row[3] != "pending_confirmation" or not row[1]:
        return {"ok": False, "reason": f"amendment_not_applicable:{row[3]}", "state_changed": False}
    timestamp = _now(now_iso)
    state = json.loads(row[4])
    state[row[1]] = json.loads(row[2])
    db.execute(
        text("UPDATE conversation_case_state SET state_json=:state,version=version+1,updated_at=:timestamp WHERE id=:id"),
        {"state": _json(state), "timestamp": timestamp, "id": row[0]},
    )
    db.execute(
        text(
            "UPDATE conversation_case_amendment SET status='accepted',effective_at=:timestamp,"
            "provenance_json=:provenance WHERE id=:id AND status='pending_confirmation'"
        ),
        {
            "timestamp": timestamp, "id": amendment_id,
            "provenance": _json({"kind": "buyer_confirmation", "actor_id": actor_id, "classifier": "bounded_case_turns_v1"}),
        },
    )
    _propagate_case_supersession(
        db,
        tenant_id=tenant_id,
        case_id=case_id,
        amendment_id=amendment_id,
        trace_id=row[6],
        prior_version=int(row[5]),
        new_version=int(row[5]) + 1,
        timestamp=timestamp,
    )
    db.commit()
    return {"ok": True, "idempotent": False, "state_changed": True}
