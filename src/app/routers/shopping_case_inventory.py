"""Explicit simulated holds for ordinary authenticated cases; no purchase authority."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from src.app.models.db import get_db
from src.app.services.case_inventory_acceptance import accept_request, release_holds
from src.app.services.case_inventory_view import read_case_stock


def enabled():
    from src.app.routers.demo import _ensure_demo_enabled
    _ensure_demo_enabled()


router = APIRouter(dependencies=[Depends(enabled)])


class ReleaseRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    uid: str=Field(min_length=1,max_length=200)
    expected_revision: int=Field(strict=True,ge=1)


class AcceptanceRequest(ReleaseRequest):
    sku: str=Field(min_length=1,max_length=200)
    quantity: int=Field(strict=True,ge=1,le=10000)
    idempotency_key: str=Field(min_length=8,max_length=120)


class QuoteSelectionRequest(ReleaseRequest):
    quote_id: str=Field(min_length=1,max_length=200)
    expected_digest: str=Field(pattern='^[a-f0-9]{64}$')


def failure(exc):
    code=str(exc)
    return HTTPException({'shopping_case_not_owned':403,'shopping_case_not_found':404}.get(code,409),detail=code)


@router.get('/{case_id}/supplier-quotes')
def supplier_quotes(case_id: str, uid: str, x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    from src.app.services.case_contract_binding import _owned_case
    from src.app.services.buyer_supplier_quotes import project_quotes
    tenant_id=x_tenant_id or 'default'
    try:
        case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
        return dict(project_quotes(db,tenant_id=tenant_id,case_id=case_id),case_revision=case.revision,simulation_only=True)
    except ValueError as exc:raise failure(exc) from exc


@router.get('/{case_id}/supplier-quote-selection')
def selected_quote(case_id: str,uid: str,x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    from src.app.services.buyer_supplier_selection import read_selection
    try:
        return dict(read_selection(db,tenant_id=x_tenant_id or 'default',case_id=case_id,uid=uid),simulation_only=True)
    except ValueError as exc:raise failure(exc) from exc


@router.post('/{case_id}/supplier-quote-selection')
def select_quote(case_id: str,body: QuoteSelectionRequest,x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    from src.app.services.buyer_supplier_selection import accept_quote
    try:
        receipt=accept_quote(db,tenant_id=x_tenant_id or 'default',case_id=case_id,**body.model_dump())
        db.commit()
        return dict(receipt,simulation_only=True)
    except ValueError as exc:
        db.rollback()
        raise failure(exc) from exc


@router.get('/{case_id}/stock')
def stock(case_id: str, uid: str, sku: str, x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    try:
        return dict(read_case_stock(db,tenant_id=x_tenant_id or 'default',case_id=case_id,uid=uid,sku=sku),simulation_only=True)
    except ValueError as exc:raise failure(exc) from exc


@router.post('/{case_id}/stock-acceptance')
def accept(case_id: str,body: AcceptanceRequest,x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    try:
        receipt=accept_request(db,tenant_id=x_tenant_id or 'default',case_id=case_id,**body.model_dump())
        db.commit()
        return dict(receipt,simulation_only=True)
    except ValueError as exc:
        db.rollback()
        raise failure(exc) from exc


@router.post('/{case_id}/release-holds')
def release(case_id: str,body: ReleaseRequest,x_tenant_id: str | None=Header(default=None),db=Depends(get_db)):
    try:
        receipt=release_holds(db,tenant_id=x_tenant_id or 'default',case_id=case_id,**body.model_dump())
        db.commit()
        return dict(receipt,simulation_only=True)
    except ValueError as exc:
        db.rollback()
        raise failure(exc) from exc
