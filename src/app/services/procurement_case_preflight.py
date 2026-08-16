"""Pre-evaluation hydration and atomic case-patch application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from src.app.services.procurement_case_state import ProcurementCaseState


@dataclass(frozen=True)
class ProcurementCasePreflightResult:
    state: ProcurementCaseState | None
    application: dict[str, Any] | None


def apply_case_patches_before_evaluation(
    db: Any,
    *,
    tenant_id: str,
    uid: str,
    session_epoch: str,
    trace_id: str,
    session: dict[str, Any],
    patches: tuple[dict[str, Any], ...],
) -> ProcurementCasePreflightResult:
    """Apply grounded model proposals before fit/research/fulfilment evaluation.

    A dedicated SQLAlchemy session keeps the case transition independent from
    caller-owned recommendation reads. The function has no commerce authority.
    """
    raw = session.get("procurement_case_state")
    if not isinstance(raw, dict):
        return ProcurementCasePreflightResult(state=None, application=None)
    state = ProcurementCaseState.model_validate(raw)
    if not patches:
        return ProcurementCasePreflightResult(state=state, application=None)
    bind = db.get_bind() if hasattr(db, "get_bind") else getattr(db, "bind", None)
    if bind is None:
        raise RuntimeError("procurement_case_preflight_requires_database_bind")

    from src.app.deps import hash_uid
    from src.app.services.conversation_case_state import (
        get_case_state,
        record_typed_case_patch_set,
    )

    idempotency_key = str(session.get("case_patch_idempotency_key") or trace_id).strip()
    with Session(bind=bind, future=True) as case_db:
        application = record_typed_case_patch_set(
            case_db,
            tenant_id=tenant_id,
            case_id=state.case_id,
            session_epoch=session_epoch,
            subject_ref=hash_uid(uid),
            source_message_id=trace_id,
            idempotency_key=idempotency_key,
            expected_version=state.revision,
            patches=list(patches),
            trace_id=trace_id,
        )
        persisted = get_case_state(
            case_db,
            tenant_id=tenant_id,
            case_id=state.case_id,
            session_epoch=session_epoch,
        )
    updated_raw = persisted.get("procurement_case_state")
    if not isinstance(updated_raw, dict):
        raise RuntimeError("procurement_case_projection_missing_after_patch")
    updated = ProcurementCaseState.model_validate({
        **updated_raw,
        "revision": int(application.get("version") or updated_raw.get("revision") or state.revision),
    })
    return ProcurementCasePreflightResult(state=updated, application=application)


__all__ = ["ProcurementCasePreflightResult", "apply_case_patches_before_evaluation"]
