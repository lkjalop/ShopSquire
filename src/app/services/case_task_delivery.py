"""Deliver explicit read-only buyer tasks from the owned canonical case."""
import json
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.platform.tenant_session import bind_session_tenant


_DRAFT = re.compile(r'\b(?:draft|compose|prepare|write)\b.{0,100}\b(?:email|e-mail|enquiry|inquiry)\b', re.I)
_MARKET = re.compile(r'\b(?:market\s+(?:intelligence|analysis)|supply\s+outlook)\b', re.I)
_AMENDMENT = re.compile(r'\b(?:make\s+(?:it|that)|change|increase|decrease|amend|replace|instead|start\s+over|new\s+(?:request|search)|forget|add\s+\d)\b', re.I)
_ENQUIRY_SCOPE = re.compile(r'\b(?:shortfall|supplier|stock|quantity|units?|procurement|current\s+(?:request|case|order))\b', re.I)
_COUNT_WORD = r'(?:\d[\d,]*|[a-z]+(?:-[a-z]+)?)'
_SHORTFALL_COUNT = re.compile(
    rf'\b(?:{_COUNT_WORD}\s*[- ]\s*(?:units?|items?)\s+(?:stock\s+)?(?:shortfall|shortage)'
    rf'|(?:shortfall|shortage)\s+(?:of\s+)?{_COUNT_WORD}\s+(?:units?|items?)'
    rf'|remaining\s+{_COUNT_WORD}\s+(?:units?|items?))\b', re.I)
_FACT_RECALL = re.compile(r'\b(?:summari[sz]e|recap|remind\s+me|how\s+many|what\s+(?:is|was|are|were)\s+(?:my|our))\b', re.I)
_OWNED_FACTS = re.compile(r'\b(?:my|our|i|we|current|existing|same|retained)\b', re.I)
_FACT_SUBJECT = re.compile(r'\b(?:quantity|units?|budget|deadline|destination|delivery|request(?:ed)?|ask(?:ed)?)\b', re.I)
_NEW_FACTS = re.compile(r'\b(?:also|add|include|switch|replace|use|run|play|support|new|now|actually|correction|search|research|find|fetch|check|look\s+up)\b|[$\u00a3\u20ac]|\b(?:AUD|USD|EUR|GBP)\s*\d', re.I)


def case_task_intent(query):
    if _DRAFT.search(str(query or '')) and _ENQUIRY_SCOPE.search(str(query or '')):
        return 'shortfall_email'
    if _MARKET.search(str(query or '')):
        return 'market_intelligence'
    if _FACT_RECALL.search(str(query or '')) and _OWNED_FACTS.search(str(query or '')) and _FACT_SUBJECT.search(str(query or '')):
        return 'case_facts'
    return None


def is_case_task_read(query, state):
    """Mixed amendments use the normal reducer before any task is delivered."""
    intent = case_task_intent(query)
    if not intent or _AMENDMENT.search(str(query or '')):
        return False
    if intent == 'case_facts':
        from src.app.services.conversation_case_state import decompose_case_obligations
        if _NEW_FACTS.search(str(query or '')) or decompose_case_obligations(str(query or ''), current_state=state):
            return False
    # A count explicitly naming the shortage is task context, not the buyer's
    # total requested quantity. Delivery still calculates the real shortage
    # from accepted selection and inventory; this prose grants no authority.
    quantity_query = _SHORTFALL_COUNT.sub(' ', str(query or ''))
    from src.app.services.bulk_intent import extract_quantity_span
    quantity = extract_quantity_span(quantity_query, unit_nouns={'unit', 'units', 'item', 'items'})
    if quantity is None and re.search(r'\b\d[\d,]*\s+(?:units?|items?)\b', quantity_query, re.I):
        return False
    return not quantity or quantity[0] == state.get('requested_quantity')


def deliver_case_task(*, out, request_db, tenant_id, uid, session_epoch, query):
    intent = case_task_intent(query)
    case_id = out.get('shopping_case_id') or out.get('case_id')
    if not intent or not case_id:
        return
    from src.app.deps import hash_uid

    # Read through the request owner's engine, with a separate transaction.
    # Failed optional evidence queries must not poison chat persistence.
    with Session(bind=request_db.get_bind()) as db:
        bind_session_tenant(db, tenant_id=tenant_id)
        case = db.execute(text('SELECT uid,revision FROM shopping_cases '
            'WHERE tenant_id=:tenant AND case_id=:case'), dict(tenant=tenant_id, case=case_id)).first()
        if not case or case[0] != uid:
            raise ValueError('case_task_not_owned')
        revision = int(case[1])
        row = db.execute(text('SELECT state_json FROM conversation_case_state '
            'WHERE tenant_id=:tenant AND case_id=:case AND session_epoch=:epoch '
            'AND subject_ref=:subject AND version=:revision'),
            dict(tenant=tenant_id, case=case_id, epoch=session_epoch,
                 subject=hash_uid(uid), revision=revision)).first()
        if not row:
            raise ValueError('case_task_state_not_current')
        stored = json.loads(row[0])
        state = stored.get('procurement_case_state') or {}
        if state.get('case_id') != case_id or state.get('revision') != revision:
            raise ValueError('case_task_state_not_current')
        if intent == 'shortfall_email':
            from src.app.services.shortfall_enquiry_preview import shortfall_draft
            draft = shortfall_draft(db, tenant_id=tenant_id, case_id=case_id,
                                   revision=revision, state=state)
            out['email_draft'] = draft
            out['supplier_email_draft'] = draft
            out['assistant_message'] = 'Draft — choose a supplier contact before sending.\nSubject: ' + draft['subject'] + '\n\n' + draft['body']
        elif intent == 'market_intelligence':
            from src.app.services.market_intelligence_agent import gather_market_context
            sku = state.get('selected_sku')
            context = gather_market_context(db, query=query, tenant_id=tenant_id,
                result_skus=[sku] if sku else [], force=True, include_graph=False)
            context.update(case_id=case_id, case_revision=revision, commerce_authority='none')
            out['market_intelligence'] = context
            findings = context['market_evidence'].get('findings') or []
            if findings:
                out['assistant_message'] = 'Market intelligence for this request:\n' + '\n'.join(
                    f"{finding['summary']} [{finding['citation_ref']}]" for finding in findings)
            else:
                out['assistant_message'] = (
                    'Current market intelligence is unavailable for this request.'
                    if context['delivery_status'] == 'unavailable' else
                    'I have no current, scoped market evidence for this request. Its quantity and budget are retained.')
        else:
            out['assistant_message'] = _case_facts_message(state)
        _project_task_snapshot(out, state, revision, query)


def _case_facts_message(state):
    """Only facts from the just-validated canonical revision enter this answer."""
    parts = []
    if type(state.get('requested_quantity')) is int:
        parts.append(f"{state['requested_quantity']} units")
    budget = state.get('budget') or {}
    if type(budget.get('amount_minor')) is int and budget.get('currency'):
        scope = {'per_unit': 'per unit', 'total': 'total'}.get(budget.get('scope'), '(scope unresolved)')
        parts.append(f"budget {budget['currency']} {budget['amount_minor'] / 100:.2f} {scope}")
    destinations = state.get('destinations') or []
    if destinations:
        parts.append('delivery: ' + ', '.join(f"{row['quantity']} units to {row['location_ref']}" for row in destinations))
    temporal = state.get('temporal') or {}
    if temporal.get('original_expression'):
        parts.append(f"deadline: {temporal['original_expression']} ({temporal.get('resolution_status', 'unresolved')})")
    return 'Your retained request: ' + '; '.join(parts) + '.' if parts else 'The current request has no confirmed quantity, budget or destination yet.'


def _project_task_snapshot(out, state, revision, query):
    from src.app.services.research_outcome import ResearchOutcome
    from src.app.services.turn_transition import (
        RevisionBoundTurnReadModel, PendingClarificationCommit, RequirementCommit, TurnTransition,
    )
    case_id = state['case_id']
    operation = out['operation_id']
    trace_id = out.get('decision_trace_id') or case_id.removeprefix('sc-')
    # A saved display projection is a cache, including when its schema is
    # valid. Rebuild task facts from canonical state; old products/authority
    # cannot re-enter a read response through a stale or corrupt projection.
    shared = {key: state[key] for key in ('requested_quantity', 'budget', 'destinations', 'temporal') if state.get(key)}
    view = RevisionBoundTurnReadModel(case_id=case_id, case_revision=revision,
        transition=TurnTransition.UNRESOLVED, objective=state.get('objective'),
        workloads=state.get('workloads') or [], shared_constraints=shared,
        pending_clarification=PendingClarificationCommit(),
        external_research_authorized=False, requirements=RequirementCommit(),
        catalog_authority='blocked', commerce_authority='none',
        research_outcome=ResearchOutcome(case_id=case_id, case_revision=revision, catalog_authority='blocked'))
    outcome = view.research_outcome.model_copy(update={'operation_id': operation})
    facts = {key: state[key] for key in ('requested_quantity', 'budget', 'destinations', 'temporal') if state.get(key)}
    panel = {**(view.right_panel or {}), 'retained_buyer_facts': facts}
    view = view.model_copy(update={'operation_id': operation, 'buyer_query': query,
        'trace_id': trace_id, 'assistant_message': out['assistant_message'], 'right_panel': panel,
        'research_outcome': outcome, 'commerce_authority': 'none'})
    slots = {'order_quantity': state.get('requested_quantity')}
    budget = state.get('budget') or {}
    if budget:
        slots.update(currency=budget['currency'], budget_scope=budget['scope'], budget_max=budget['amount_minor'] / 100)
    out.update(case_id=case_id, shopping_case_id=case_id, case_revision=revision,
        shopping_case_revision=revision, decision_trace_id=trace_id,
        retained_purpose=state.get('objective'), requested_quantity=state.get('requested_quantity'),
        procurement_case_state=state, retained_buyer_facts=facts, confirmed_slots=slots,
        turn_read_model=view.model_dump(mode='json'), right_panel=panel, next_questions=[],
        products=list(view.products), research_outcome=outcome.model_dump(mode='json'),
        state_changed=not out.get('read_only_case_task', False), action_executed=False)
    out['terminal_outcome'] = dict(schema_version='turn-terminal-outcome-v1',
        operation_id=operation, case_id=case_id, case_revision=revision, decision_trace_id=trace_id,
        read_only_case_task=bool(out.get('read_only_case_task')), recommendation_status='not_requested',
        research_status='not_requested', research_outcome=out['research_outcome'],
        commerce_authority='none', catalog_authority=view.catalog_authority,
        catalog_scope=view.catalog_scope, retained_buyer_facts=facts, products=out['products'],
        right_panel=panel, next_questions=[], assistant_message=out['assistant_message'])
