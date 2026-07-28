"""Tenant-scoped Party/account intelligence for the operator control room."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.app.platform.tenant_context import current_tenant_id
from src.app.security.auth import (
    ROLE_MERCHANT,
    ROLE_OWNER,
    OperatorSubject,
    operator_subject,
    require_role,
)
from src.app.services.account_intelligence import (
    get_account_timeline,
    list_identity_resolution_proposals,
    list_parties,
    propose_party_merge,
    propose_party_split,
    resolve_identity_resolution_proposal,
)


router = APIRouter(prefix="/api/v1/admin/accounts", tags=["admin", "accounts"])
_OPERATORS = [ROLE_MERCHANT, ROLE_OWNER]


class IdentityProposalBody(BaseModel):
    proposal_type: Literal["merge", "split"]
    left_party_id: str = Field(min_length=1, max_length=160)
    right_party_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=3, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)


class IdentityResolutionBody(BaseModel):
    resolution: Literal["approved", "rejected"]
    note: str = Field(min_length=3, max_length=1000)


def _tenant() -> str:
    return str(current_tenant_id() or "default")


def _actor(role: str, subject: OperatorSubject) -> str:
    return (subject.user_id or "").strip() or f"key:{role}"


def _translate(exc: ValueError) -> HTTPException:
    detail = str(exc)
    if detail in {"party_not_in_tenant", "identity_proposal_not_in_tenant"}:
        return HTTPException(status_code=404, detail=detail)
    if detail == "identity_proposal_already_resolved":
        return HTTPException(status_code=409, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.get("")
def accounts(
    query: str | None = Query(default=None, max_length=160),
    party_type: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    role: str = Depends(require_role(_OPERATORS)),
) -> dict[str, Any]:
    _ = role
    try:
        items = list_parties(
            tenant_id=_tenant(), query=query, party_type=party_type, limit=limit
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"tenant_id": _tenant(), "accounts": items}


@router.get("/{party_id}/timeline")
def account_timeline(
    party_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    role: str = Depends(require_role(_OPERATORS)),
) -> dict[str, Any]:
    _ = role
    try:
        return get_account_timeline(
            tenant_id=_tenant(), party_id=party_id, limit=limit
        )
    except ValueError as exc:
        raise _translate(exc) from exc


@router.get("/identity/proposals")
def identity_proposals(
    status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=100, ge=1, le=500),
    role: str = Depends(require_role(_OPERATORS)),
) -> dict[str, Any]:
    _ = role
    try:
        proposals = list_identity_resolution_proposals(
            tenant_id=_tenant(), status=status, limit=limit
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    return {"tenant_id": _tenant(), "proposals": proposals}


@router.post("/identity/proposals")
def create_identity_proposal(
    body: IdentityProposalBody,
    role: str = Depends(require_role(_OPERATORS)),
    subject: OperatorSubject = Depends(operator_subject),
) -> dict[str, Any]:
    evidence = {**body.evidence, "operator_reason": body.reason}
    if len(json.dumps(evidence, ensure_ascii=False)) > 16_384:
        raise HTTPException(status_code=413, detail="identity_proposal_evidence_too_large")
    kwargs = {
        "tenant_id": _tenant(),
        "left_party_id": body.left_party_id,
        "right_party_id": body.right_party_id,
        "evidence": evidence,
        "proposed_by": _actor(role, subject),
    }
    try:
        result = (
            propose_party_merge(**kwargs)
            if body.proposal_type == "merge"
            else propose_party_split(**kwargs)
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    return {
        **result,
        "authority": "proposal_only",
        "message": "Recorded for human review; no Party records were changed.",
    }


@router.post("/identity/proposals/{proposal_id}/resolve")
def resolve_identity_proposal(
    proposal_id: str,
    body: IdentityResolutionBody,
    role: str = Depends(require_role([ROLE_OWNER])),
    subject: OperatorSubject = Depends(operator_subject),
) -> dict[str, Any]:
    try:
        result = resolve_identity_resolution_proposal(
            tenant_id=_tenant(),
            proposal_id=proposal_id,
            resolution=body.resolution,
            resolved_by=_actor(role, subject),
            note=body.note,
        )
    except ValueError as exc:
        raise _translate(exc) from exc
    return {
        **result,
        "authority": "human_disposition_only",
        "message": "Disposition recorded; execution remains a separate manual workflow.",
    }
