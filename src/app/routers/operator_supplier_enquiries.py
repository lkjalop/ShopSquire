"""Authenticated fictional supplier workflow. No route accepts an outbound address."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from src.app.models.db import db_session
from src.app.security.auth import require_role_or_oidc, ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER
from src.app.services import supplier_enquiry_journey as journey
from src.app.services import supplier_enquiry_recovery as recovery
from src.app.services.fulfillment.transport import SandboxTransport
from src.app.services.synthetic_supplier_directory import recipient_for

router = APIRouter(prefix="/supplier-enquiries")
roles = Depends(require_role_or_oidc([ROLE_OWNER, ROLE_MERCHANT, ROLE_DEVELOPER]))


class EnquiryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str = Field(min_length=1, max_length=200)
    expected_revision: int = Field(strict=True, ge=1)
    supplier_ref: str = Field(min_length=1, max_length=100)
    source_reference: str = Field(min_length=8, max_length=200)


class ReplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=200)
    sender_ref: str = Field(min_length=1, max_length=100)
    terms: journey.QuoteTerms


class RecoveryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern="^(submitted|not_delivered)$")
    evidence_ref: str = Field(min_length=1, max_length=500)
    provider_ref: str = Field(default="", max_length=200)


class RenewalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(strict=True, ge=1)
    reference: str = Field(min_length=1, max_length=100)


class DraftRevisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(strict=True, ge=1)
    include_budget: bool = Field(strict=True)


@router.post("/{enquiry_id}/draft")
def revise_draft(enquiry_id: str, body: DraftRevisionBody, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            result = journey.revise_draft(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                operator_principal=who.principal_hash,
                **body.model_dump(),
            )
            db.commit()
            return result
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


def actor(request):
    from src.app.routers.admin_inventory import _inventory_operator

    return _inventory_operator(request)


@router.post("/{enquiry_id}/revoke-approval")
def revoke(enquiry_id: str, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            result = recovery.revoke(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                operator_principal=who.principal_hash,
            )
            db.commit()
            return result
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/{enquiry_id}/recovery")
def reconcile(enquiry_id: str, body: RecoveryBody, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            recovery.reconcile(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                operator_principal=who.principal_hash,
                **body.model_dump(),
            )
            db.commit()
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=enquiry_id)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/{enquiry_id}/renew")
def renew(enquiry_id: str, body: RenewalBody, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            row = recovery.renew(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                operator_principal=who.principal_hash,
                recipient_resolver=recipient_for,
                **body.model_dump(),
            )
            db.commit()
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=row["id"])
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("")
def create(body: EnquiryBody, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            row = journey.create(
                db,
                tenant_id=who.tenant_id,
                requester_principal=who.principal_hash,
                recipient_resolver=recipient_for,
                **body.model_dump(),
            )
            db.commit()
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=row["id"])
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.get("/{enquiry_id}")
def read(enquiry_id: str, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=enquiry_id)
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc)) from exc


@router.post("/{enquiry_id}/approve")
def approve(enquiry_id: str, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            journey.approve(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                approver_principal=who.principal_hash,
            )
            db.commit()
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=enquiry_id)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/{enquiry_id}/dispatch")
def dispatch(enquiry_id: str, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            return journey.dispatch(
                db, tenant_id=who.tenant_id, enquiry_id=enquiry_id, transport=SandboxTransport()
            )
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/{enquiry_id}/simulated-replies")
def receive(enquiry_id: str, body: ReplyBody, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            reply = journey.receive(
                db, tenant_id=who.tenant_id, enquiry_id=enquiry_id, **body.model_dump()
            )
            db.commit()
            return reply
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


@router.post("/{enquiry_id}/replies/{reply_id}/review")
def review(enquiry_id: str, reply_id: str, request: Request, role=roles):
    who = actor(request)
    try:
        with db_session() as db:
            journey.review(
                db,
                tenant_id=who.tenant_id,
                enquiry_id=enquiry_id,
                reply_id=reply_id,
                reviewer_principal=who.principal_hash,
            )
            db.commit()
            return journey.view(db, tenant_id=who.tenant_id, enquiry_id=enquiry_id)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
