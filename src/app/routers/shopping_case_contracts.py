"""Explicit buyer selections; these endpoints issue no qualification or effect permit."""
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.app.models.db import get_db
from src.app.services import case_contract_binding as bindings
from src.app.services.requirement_contract import ContractContext

router = APIRouter()


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uid: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    contract_id: str
    contract_revision: str
    context: ContractContext


class RevocationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    uid: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    binding_id: str


def _scope(tenant, case_id, uid):
    return dict(tenant_id=str(tenant or 'default').strip() or 'default',case_id=case_id,uid=uid)


def _error(error):
    code = str(error)
    status = {'shopping_case_not_found':404,'shopping_case_not_owned':403}.get(code,409)
    return HTTPException(status_code=status,detail=code)


def _projection(db, scope):
    return dict(selection=bindings.read_case_contract_binding(db,**scope),contracts=[
        dict(contract.model_dump(mode='json'),revision=contract.revision)
        for contract in bindings.available_contracts()])


@router.get('/{case_id}/requirement-contract')
def read_selection(case_id: str, uid: str, x_tenant_id: str | None = Header(default=None), db=Depends(get_db)):
    try:
        return _projection(db,_scope(x_tenant_id,case_id,uid))
    except ValueError as exc:
        raise _error(exc) from exc


@router.put('/{case_id}/requirement-contract')
def select_contract(case_id: str, body: SelectionRequest, x_tenant_id: str | None = Header(default=None), db=Depends(get_db)):
    scope = _scope(x_tenant_id,case_id,body.uid)
    try:
        bindings.read_case_contract_binding(db,**scope)
        contract = bindings.load_contract_by_id(body.contract_id)
        if contract.revision != body.contract_revision:
            raise ValueError('contract_revision_conflict')
        bindings.select_case_contract(db,**scope,expected_revision=body.expected_revision,
            contract_id=body.contract_id,context=body.context)
        db.commit()
        return _projection(db,scope)
    except ValueError as exc:
        db.rollback()
        raise _error(exc) from exc


@router.post('/{case_id}/requirement-contract/revoke')
def revoke_contract(case_id: str, body: RevocationRequest, x_tenant_id: str | None = Header(default=None), db=Depends(get_db)):
    scope = _scope(x_tenant_id,case_id,body.uid)
    try:
        bindings.revoke_case_contract(db,**scope,expected_revision=body.expected_revision,binding_id=body.binding_id)
        db.commit()
        return _projection(db,scope)
    except ValueError as exc:
        db.rollback()
        raise _error(exc) from exc
