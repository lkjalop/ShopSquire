"""Owned ordinary-case offers over evidence-backed product relationships."""
from datetime import datetime,timezone
from fastapi import APIRouter,Depends,Header,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import select,text
from src.app.models.db import get_db
from src.app.models.orm import ProductConfiguration,ProductEvidenceObservation
from src.app.services.case_contract_binding import _owned_case
from src.app.services import governed_product_offers as offers

router=APIRouter()


class Buyer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    uid: str=Field(min_length=1,max_length=200)


class Proposal(Buyer):
    expected_revision: int=Field(strict=True,ge=1)
    base_configuration_id: str=Field(min_length=1,max_length=200)
    target_configuration_id: str=Field(min_length=1,max_length=200)
    need: str=Field(min_length=1,max_length=100)
    quantity: int=Field(strict=True,ge=1,le=10000)


def failure(exc):
    return HTTPException({'shopping_case_not_owned':403,'shopping_case_not_found':404}.get(str(exc),409),detail=str(exc))


@router.get('/{case_id}/product-offer-options')
def options(case_id: str,uid: str,sku: str,x_tenant_id: str|None=Header(default=None),db=Depends(get_db)):
    tenant=x_tenant_id or 'default'
    try:
        case=_owned_case(db,tenant_id=tenant,case_id=case_id,uid=uid)
        configurations=db.execute(select(ProductConfiguration).where(ProductConfiguration.tenant_id==tenant,
            ProductConfiguration.sku==sku,ProductConfiguration.active.is_(True))).scalars().all()
        if len(configurations)!=1:
            return dict(case_revision=case.revision,candidates=[],reason='exact_configuration_required')
        base=configurations[0]
        facts=db.execute(select(ProductEvidenceObservation).where(ProductEvidenceObservation.configuration_id==base.id,
            ProductEvidenceObservation.attribute_key=='supported_product_relation')).scalars().all()
        candidates=[];seen=set()
        for fact in facts:
            value=fact.value_json if isinstance(fact.value_json,dict) else {}
            target=value.get('target_configuration_id');need=value.get('need')
            if not isinstance(target,str) or not isinstance(need,str) or (target,need) in seen:continue
            seen.add((target,need))
            # Suggestions inherit the same current evidence checks as acceptance.
            try:
                projection=offers.evaluate(db,tenant_id=tenant,base_configuration_id=base.id,
                    target_configuration_id=target,need=need,quantity=1,now=datetime.now(timezone.utc))
            except ValueError:continue
            config=db.get(ProductConfiguration,target)
            candidates.append(dict(configuration_id=target,sku=config.sku,label=config.title,need=need,
                kind=projection['kind'],benefit=projection['benefit']))
        return dict(case_revision=case.revision,base_configuration_id=base.id,candidates=candidates,
            reason='' if candidates else 'no_current_supported_relationship',commerce_authority='none')
    except ValueError as exc:raise failure(exc) from exc


@router.post('/{case_id}/product-offers')
def propose(case_id: str,body: Proposal,x_tenant_id: str|None=Header(default=None),db=Depends(get_db)):
    tenant=x_tenant_id or 'default'
    try:
        _owned_case(db,tenant_id=tenant,case_id=case_id,uid=body.uid)
        cart=db.execute(text("SELECT id FROM draft_orders WHERE tenant_id=:tenant AND customer_id=:uid AND status='draft' ORDER BY created_at DESC LIMIT 1"),
            dict(tenant=tenant,uid=body.uid)).scalar()
        if not cart:raise ValueError('scoped_draft_cart_required')
        result=offers.propose(db,tenant_id=tenant,case_id=case_id,cart_id=cart,**body.model_dump())
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise failure(exc) from exc


@router.post('/{case_id}/product-offers/{offer_id}/accept')
def accept(case_id: str,offer_id: str,body: Buyer,x_tenant_id: str|None=Header(default=None),db=Depends(get_db)):
    try:
        result=offers.accept(db,tenant_id=x_tenant_id or 'default',case_id=case_id,offer_id=offer_id,uid=body.uid)
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise failure(exc) from exc


@router.post('/{case_id}/product-offers/{offer_id}/decline')
def decline(case_id: str,offer_id: str,body: Buyer,x_tenant_id: str|None=Header(default=None),db=Depends(get_db)):
    try:
        result=offers.decline(db,tenant_id=x_tenant_id or 'default',case_id=case_id,offer_id=offer_id,uid=body.uid)
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise failure(exc) from exc
