"""Persist and revalidate explicit case selections without inferring buyer intent."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, inspect

from src.app.models.orm import ShoppingCase, ShoppingCaseContractSelection
from src.app.services.requirement_contract import ContractContext, load_requirement_contract
from src.app.services.shopping_case_revision import advance_material_case_revision

CONTRACT_DIR = Path(__file__).resolve().parents[3] / "config/requirement_contracts"


def available_contracts():
    return [load_requirement_contract(p) for p in sorted(CONTRACT_DIR.glob("*.json"))]


def load_contract_by_id(contract_id):
    matches = [c for c in available_contracts() if c.id == contract_id]
    if len(matches) != 1:
        raise ValueError("requirement_contract_not_found_or_ambiguous")
    return matches[0]


def _owned_case(db, *, tenant_id, case_id, uid):
    case = db.execute(select(ShoppingCase).where(
        ShoppingCase.tenant_id == tenant_id, ShoppingCase.case_id == case_id,
    ).execution_options(populate_existing=True)).scalar_one_or_none()
    if case is None:
        raise ValueError("shopping_case_not_found")
    if case.uid != uid:
        raise ValueError("shopping_case_not_owned")
    return case


def _latest(db, *, tenant_id, case_id):
    return db.execute(select(ShoppingCaseContractSelection).where(
        ShoppingCaseContractSelection.tenant_id == tenant_id,
        ShoppingCaseContractSelection.case_id == case_id,
    ).order_by(ShoppingCaseContractSelection.case_revision.desc()).limit(1)
        .execution_options(populate_existing=True)).scalar_one_or_none()


def read_case_contract_binding(db, *, tenant_id, case_id, uid):
    case = _owned_case(db, tenant_id=tenant_id, case_id=case_id, uid=uid)
    row = _latest(db, tenant_id=tenant_id, case_id=case_id)
    result = dict(state="unselected", case_id=case_id, case_revision=case.revision,
                  fit_authority="none", commerce_authority="none")
    if row is None:
        return result
    state = "current"
    try:
        contract = load_contract_by_id(row.contract_id)
        if contract.revision != row.contract_revision or contract.context.model_dump() != row.context_json:
            state = "stale_contract_revision"
    except (ValueError, OSError):
        state = "contract_unavailable"
    if row.case_revision != case.revision:
        state = "stale_case_revision"
    if row.revoked_at is not None:
        state = "revoked"
    return dict(result, state=state, binding_id=row.id, selected_case_revision=row.case_revision,
                contract_id=row.contract_id, contract_revision=row.contract_revision,
                context=row.context_json)


def select_case_contract(db, *, tenant_id, case_id, uid, expected_revision, contract_id, context):
    case = _owned_case(db, tenant_id=tenant_id, case_id=case_id, uid=uid)
    if case.revision != expected_revision:
        raise ValueError("case_revision_conflict")
    contract = load_contract_by_id(contract_id)
    if ContractContext.model_validate(context) != contract.context:
        raise ValueError("contract_context_mismatch")
    revision = advance_material_case_revision(db, tenant_id=tenant_id, case_id=case_id,
        expected_revision=expected_revision, reason="requirement_contract_selected")
    db.add(ShoppingCaseContractSelection(tenant_id=tenant_id, case_id=case_id, uid=uid,
        case_revision=revision, contract_id=contract.id, contract_revision=contract.revision,
        context_json=contract.context.model_dump(), selected_at=datetime.now(timezone.utc)))
    db.flush()
    db.refresh(case)
    return read_case_contract_binding(db, tenant_id=tenant_id, case_id=case_id, uid=uid)


def revoke_case_contract(db, *, tenant_id, case_id, uid, expected_revision, binding_id):
    case = _owned_case(db, tenant_id=tenant_id, case_id=case_id, uid=uid)
    if case.revision != expected_revision:
        raise ValueError("case_revision_conflict")
    row = _latest(db, tenant_id=tenant_id, case_id=case_id)
    if row is None or row.id != binding_id:
        raise ValueError("contract_binding_mismatch")
    advance_material_case_revision(db, tenant_id=tenant_id, case_id=case_id,
        expected_revision=expected_revision, reason="requirement_contract_revoked")
    row.revoked_at = datetime.now(timezone.utc)
    db.flush()
    db.refresh(case)
    return read_case_contract_binding(db, tenant_id=tenant_id, case_id=case_id, uid=uid)


def require_current_case_contract(db, *, tenant_id, case_id, uid, binding_id):
    current = read_case_contract_binding(db, tenant_id=tenant_id, case_id=case_id, uid=uid)
    if current.get("binding_id") != binding_id:
        raise ValueError("contract_binding_mismatch")
    if current["state"] != "current":
        raise ValueError(current["state"])
    return load_contract_by_id(current["contract_id"]), ContractContext.model_validate(current["context"])


def gate_case_contract_consumption(db, *, tenant_id, case_id, uid, claims, now=None):
    """Additional case gate; accepted-claim and registry checks remain mandatory."""
    from src.app.services.requirement_contract import assess_contract_coverage
    receipt = read_case_contract_binding(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
    if receipt['state'] == 'unselected':
        return list(claims), receipt
    if receipt['state'] != 'current':
        return [], receipt
    contract, context = require_current_case_contract(db,tenant_id=tenant_id,case_id=case_id,
        uid=uid,binding_id=receipt['binding_id'])
    indexed = [dict(claim,claim_id=str(index) if claim.get('claim_id') else None)
               for index,claim in enumerate(claims)]
    coverage = assess_contract_coverage(contract,context=context,claims=indexed,now=now)
    receipt['coverage'] = coverage
    if not coverage['coverage_complete']:
        return [], receipt
    ids = {claim_id for row in coverage['obligations'] for claim_id in row['accepted_claim_ids']}
    return [claim for index,claim in enumerate(claims) if str(index) in ids], receipt


def assert_case_contract_unchanged(db, *, tenant_id, case_id, uid, receipt):
    current = read_case_contract_binding(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
    keys = ('case_revision','binding_id','contract_revision','state')
    if any(current.get(key) != receipt.get(key) for key in keys):
        raise ValueError('case_contract_changed_during_research')
    if current['state'] not in ('current','unselected'):
        raise ValueError(current['state'])
    return current


def continue_unchanged_contract(db, *, tenant_id, case_id, previous_revision, before, after):
    """Carry a selection across an evidence-only turn in the caller's CAS transaction.

    This preserves evaluation scope, never an approval, quote or product verdict.
    Buyer constraints and all non-evidence state must be identical. The turn's
    amendment ledger records this continuation and its previous revision.
    """
    def material(state):
        value=state.model_dump(mode='json',exclude={'revision','research','authority','requirements'})
        value['buyer_requirements']={'accepted':[row for row in state.requirements.get('accepted',[])
            if row.get('authority_status')!='verified_official']}
        value['buyer_requirements']={key:rows for key,rows in value['buyer_requirements'].items() if rows}
        return value
    if material(before)!=material(after):return None
    if 'shopping_case_contract_selections' not in inspect(db.connection()).get_table_names():return None
    row=_latest(db,tenant_id=tenant_id,case_id=case_id)
    if row is None:return None
    receipt=read_case_contract_binding(db,tenant_id=tenant_id,case_id=case_id,uid=row.uid)
    if receipt['state']!='current' or receipt['case_revision']!=previous_revision:return None
    row.case_revision=previous_revision+1
    db.flush()
    return dict(receipt,case_revision=previous_revision+1,selected_case_revision=previous_revision+1,
        previous_case_revision=previous_revision,reason='unchanged_material_inputs')
