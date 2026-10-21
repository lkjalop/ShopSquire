"""Recheck current typed requirements against a sourcing estimate, without effects."""
from datetime import datetime, timedelta
import json
from sqlalchemy import inspect, text
from src.app.services.procurement_case_state import TemporalConstraint


def assess(db, *, tenant_id, case_id, revision, currency, unit_price_cents,
           covered_total_cents, lead_days, now):
    result = dict(status='not_recorded', reason='', deadline_status='not_requested',
                  budget_status='not_requested', required_by=None)
    def blocked(reason):
        return dict(result, status='blocked', reason=reason)
    if not inspect(db.connection()).has_table('conversation_case_state'):
        return blocked('supplier_requirements_unavailable')
    rows = db.execute(text('SELECT version,state_json FROM conversation_case_state '
        'WHERE tenant_id=:tenant AND case_id=:case'),dict(tenant=tenant_id,case=case_id)).all()
    if not rows:
        return result
    if len(rows)!=1 or rows[0][0]!=revision:
        return blocked('supplier_requirement_revision_conflict')
    try:
        state=json.loads(rows[0][1]) if isinstance(rows[0][1],str) else rows[0][1]
        typed=state['procurement_case_state']
        if typed.get('revision')!=revision:
            return blocked('supplier_requirement_revision_conflict')
        temporal=TemporalConstraint.model_validate(typed['temporal']) if typed.get('temporal') else None
        if temporal and (temporal.original_expression or temporal.required_by or temporal.resolution_status in ('ambiguous','unresolved')):
            result['deadline_status']='unresolved'
            if temporal.resolution_status!='resolved':return blocked('delivery_deadline_unresolved')
            result['required_by']=temporal.required_by
            if now+timedelta(days=lead_days)>datetime.fromisoformat(temporal.required_by.replace('Z','+00:00')):
                result['deadline_status']='estimate_late'
                return blocked('estimated_delivery_after_deadline')
            result['deadline_status']='estimate_within_deadline'
        budget=typed.get('budget')
        if budget:
            result['budget_status']='unresolved'
            if budget.get('currency')!=currency:return blocked('supplier_budget_currency_mismatch')
            amount=budget.get('amount_minor')
            if type(amount) is not int or amount<0:return blocked('supplier_budget_invalid')
            if budget.get('scope')=='total':
                if covered_total_cents>amount:return blocked('supplier_estimate_exceeds_total_budget')
                result['budget_status']='covered_units_within_total_budget'
            elif budget.get('scope')=='per_unit':
                if unit_price_cents>amount:return blocked('supplier_estimate_exceeds_unit_budget')
                result['budget_status']='unit_price_within_budget_freight_separate'
            else:return blocked('supplier_budget_scope_unresolved')
    except (ValueError,TypeError,KeyError,AttributeError):
        return blocked('supplier_requirements_invalid')
    return dict(result,status='checked')
