"""Fictional buyer offer showcase over the generic evidence/acceptance service."""
import json,uuid
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import text
from src.app.models.db import get_db
from src.app.models.orm import ShoppingCase
from src.app.services.case_contract_binding import _owned_case
from src.app.services import governed_product_offers as offers

async def enabled(request: Request):
    from src.app.routers.demo import _ensure_demo_enabled
    _ensure_demo_enabled()
    from src.app.security.buyer_principal import require_shopping_case_principal
    principal=await require_shopping_case_principal(request)
    if principal.tenant_id!=config()['tenant_id']:
        raise HTTPException(403,detail='fictional_tenant_required')

router=APIRouter(prefix='/product-offer-cases',dependencies=[Depends(enabled)])

def config():return json.loads((Path(__file__).resolve().parents[3]/'config/product_offer_demo.json').read_text())

class Buyer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    uid: str=Field(min_length=1,max_length=200)

class Proposal(Buyer):
    expected_revision: int=Field(strict=True,ge=1)
    target_configuration_id: str=Field(min_length=1,max_length=200)
    need: str=Field(min_length=1,max_length=100)
    quantity: int=Field(strict=True,ge=1,le=10000)

@router.post('')
def create(body: Buyer,db=Depends(get_db)):
    cfg=config();case=ShoppingCase(case_id='offer-demo-'+str(uuid.uuid4()),tenant_id=cfg['tenant_id'],uid=body.uid,
        revision=1,retained_purpose='simulation:'+cfg['version'])
    db.add(case);db.commit()
    from src.app.routers.cart import _get_or_create_cart
    _get_or_create_cart(body.uid,tenant_id=cfg['tenant_id'])
    return read(case.case_id,body.uid,db)

@router.get('/{case_id}')
def read(case_id: str,uid: str,db=Depends(get_db)):
    cfg=config();tenant=cfg['tenant_id']
    try:case=_owned_case(db,tenant_id=tenant,case_id=case_id,uid=uid)
    except ValueError as exc:raise HTTPException(403,detail=str(exc)) from exc
    cart=db.execute(text("SELECT id,line_items,version FROM draft_orders WHERE tenant_id=:tenant AND customer_id=:uid AND status='draft' ORDER BY created_at DESC LIMIT 1"),
        dict(tenant=tenant,uid=uid)).first()
    return dict(case_id=case_id,case_revision=case.revision,tenant_id=tenant,
        base_configuration_id=tenant+':'+cfg['base']['sku'],base=cfg['base'],
        candidates=[dict(item,configuration_id=tenant+':'+item['sku']) for item in cfg['candidates']],
        cart=dict(id=cart[0],items=json.loads(cart[1]),version=cart[2]) if cart else None,simulation_only=True)

@router.post('/{case_id}/offers')
def propose(case_id: str,body: Proposal,db=Depends(get_db)):
    state=read(case_id,body.uid,db)
    try:
        result=offers.propose(db,tenant_id=state['tenant_id'],case_id=case_id,uid=body.uid,
            expected_revision=body.expected_revision,cart_id=state['cart']['id'],base_configuration_id=state['base_configuration_id'],
            target_configuration_id=body.target_configuration_id,need=body.need,quantity=body.quantity)
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise HTTPException(409,detail=str(exc)) from exc

@router.post('/{case_id}/offers/{offer_id}/accept')
def accept(case_id: str,offer_id: str,body: Buyer,db=Depends(get_db)):
    try:
        result=offers.accept(db,tenant_id=config()['tenant_id'],case_id=case_id,uid=body.uid,offer_id=offer_id)
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise HTTPException(409,detail=str(exc)) from exc

@router.post('/{case_id}/offers/{offer_id}/decline')
def decline(case_id: str,offer_id: str,body: Buyer,db=Depends(get_db)):
    try:
        result=offers.decline(db,tenant_id=config()['tenant_id'],case_id=case_id,uid=body.uid,offer_id=offer_id)
        db.commit();return result
    except ValueError as exc:
        db.rollback();raise HTTPException(409,detail=str(exc)) from exc
