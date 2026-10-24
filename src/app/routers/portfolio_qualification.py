"""Fictional buyer showcase and explicit synthetic stock holds; no external sends or payments."""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from src.app.models.db import get_db
from src.app.services import portfolio_qualification as journey
from sqlalchemy import text

router=APIRouter()
from src.app.routers.product_offer_demo import router as product_offer_router
router.include_router(product_offer_router)


class BuyerRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    uid: str=Field(min_length=1,max_length=200)


async def enabled(request: Request):
    from src.app.routers.demo import _ensure_demo_enabled
    _ensure_demo_enabled()
    from src.app.security.buyer_principal import require_shopping_case_principal
    principal = await require_shopping_case_principal(request)
    if principal.tenant_id != journey.TENANT:
        raise HTTPException(403, detail='fictional_tenant_required')


@router.post('/qualification-cases',dependencies=[Depends(enabled)])
def create(body: BuyerRequest,db=Depends(get_db)):
    try:
        result=journey.create_case(db,uid=body.uid)
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409,detail=str(exc)) from exc


@router.get('/qualification-cases/{case_id}',dependencies=[Depends(enabled)])
def read(case_id: str,uid: str,expired: bool=False,db=Depends(get_db)):
    try:
        return journey.project_case(db,case_id=case_id,uid=uid,
            now=journey.NOW+timedelta(days=2 if expired else 0))
    except ValueError as exc:
        status={'shopping_case_not_found':404,'shopping_case_not_owned':403}.get(str(exc),409)
        raise HTTPException(status,detail=str(exc)) from exc


class StockAcceptance(BuyerRequest):
    expected_revision: int=Field(strict=True,ge=1)
    quantity: int=Field(strict=True,ge=1,le=10000)
    idempotency_key: str=Field(min_length=8,max_length=120)


class HoldRelease(BuyerRequest):
    expected_revision: int=Field(strict=True,ge=1)


def _stock_case(db,case_id,uid):
    case=journey.bindings._owned_case(db,tenant_id=journey.TENANT,case_id=case_id,uid=uid)
    if case.retained_purpose!='simulation:'+journey.CONTRACT_ID:
        raise ValueError('fictional_case_required')
    configuration=db.get(journey.ProductConfiguration,journey.CONFIGURATION_ID)
    if not configuration or configuration.tenant_id!=journey.TENANT:
        raise ValueError('fictional_configuration_required')
    return case,configuration.sku


@router.get('/qualification-cases/{case_id}/stock',dependencies=[Depends(enabled)])
def stock(case_id: str,uid: str,db=Depends(get_db)):
    try:
        case,sku=_stock_case(db,case_id,uid)
        from src.app.services.case_inventory_view import read_case_stock
        return dict(read_case_stock(db,tenant_id=journey.TENANT,case_id=case_id,uid=uid,sku=sku),simulation_only=True)
    except ValueError as exc:
        raise HTTPException(403 if str(exc)=='shopping_case_not_owned' else 409,detail=str(exc)) from exc


@router.post('/qualification-cases/{case_id}/stock-acceptance',dependencies=[Depends(enabled)])
def accept_stock(case_id: str,body: StockAcceptance,db=Depends(get_db)):
    from src.app.services.case_inventory_acceptance import accept_request
    try:
        _,sku=_stock_case(db,case_id,body.uid)
        receipt=accept_request(db,tenant_id=journey.TENANT,case_id=case_id,uid=body.uid,
            expected_revision=body.expected_revision,sku=sku,quantity=body.quantity,
            idempotency_key=body.idempotency_key)
        db.commit()
        return dict(receipt,simulation_only=True)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(403 if str(exc)=='shopping_case_not_owned' else 409,detail=str(exc)) from exc


@router.post('/qualification-cases/{case_id}/release-holds',dependencies=[Depends(enabled)])
def release_stock(case_id: str,body: HoldRelease,db=Depends(get_db)):
    from src.app.services.case_inventory_acceptance import release_holds
    try:
        _stock_case(db,case_id,body.uid)
        receipt=release_holds(db,tenant_id=journey.TENANT,case_id=case_id,uid=body.uid,
                              expected_revision=body.expected_revision)
        db.commit()
        return dict(receipt,simulation_only=True)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(403 if str(exc)=='shopping_case_not_owned' else 409,detail=str(exc)) from exc
