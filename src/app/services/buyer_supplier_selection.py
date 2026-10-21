"""Persist buyer intent for a reviewed estimate; no supplier reservation or purchase.

The authenticated API owns commit/rollback. Every read and acceptance revalidates
the revision, remaining demand, quote status/expiry and currently displayed price.
"""
from datetime import datetime, timezone
import json
import uuid
from sqlalchemy import text
from src.app.services.buyer_supplier_quotes import project_quotes
from src.app.services.case_contract_binding import _owned_case
from src.app.services.inventory_transactions import _atomic


def _quote(db, *, tenant_id, case_id, quote_id, now):
    return next((row for row in project_quotes(db,tenant_id=tenant_id,case_id=case_id,now=now)['quotes']
                 if row['quote_id']==quote_id), None)


def _receipt(row, status):
    return dict(selection_id=row['id'],case_id=row['case_id'],case_revision=row['case_revision'],
        status=status,quote=json.loads(row['quote_json']),accepted_at=row['accepted_at'],
        commerce_authority='none',supplier_stock_reserved=False,purchase_commitment=False)


def read_selection(db, *, tenant_id, case_id, uid, now=None):
    case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
    row=db.execute(text('SELECT * FROM buyer_supplier_quote_selection WHERE tenant_id=:tenant '
        'AND case_id=:case AND uid=:uid ORDER BY case_revision DESC LIMIT 1'),
        dict(tenant=tenant_id,case=case_id,uid=uid)).mappings().first()
    if not row:return dict(status='unselected',case_revision=case.revision,commerce_authority='none')
    current=_quote(db,tenant_id=tenant_id,case_id=case_id,quote_id=row['quote_id'],now=now)
    status='current' if (case.revision==row['case_revision'] and current and current['eligible']
        and current['selection_digest']==row['quote_digest']) else 'revalidation_required'
    return _receipt(row,status)


def accept_quote(db, *, tenant_id, case_id, uid, expected_revision, quote_id, expected_digest, now=None):
    clock=now or datetime.now(timezone.utc)
    with _atomic(db):
        if db.get_bind().dialect.name=='postgresql':
            db.execute(text('SELECT case_id FROM shopping_cases WHERE tenant_id=:tenant AND case_id=:case FOR UPDATE'),
                       dict(tenant=tenant_id,case=case_id))
        case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
        if case.revision!=expected_revision:raise ValueError('case_revision_conflict')
        quote=_quote(db,tenant_id=tenant_id,case_id=case_id,quote_id=quote_id,now=clock)
        if not quote or not quote['eligible']:raise ValueError('current_reviewed_supplier_quote_required')
        if quote['selection_digest']!=expected_digest:raise ValueError('supplier_quote_changed_refresh_required')
        previous=db.execute(text('SELECT * FROM buyer_supplier_quote_selection WHERE tenant_id=:tenant '
            'AND case_id=:case AND case_revision=:revision'),
            dict(tenant=tenant_id,case=case_id,revision=expected_revision)).mappings().first()
        if previous:
            if (previous['uid'],previous['quote_id'],previous['quote_digest'])!=(uid,quote_id,expected_digest):
                raise ValueError('supplier_selection_requires_new_revision')
            return _receipt(previous,'current')
        row=dict(id=str(uuid.uuid4()),tenant_id=tenant_id,case_id=case_id,uid=uid,case_revision=expected_revision,
            quote_id=quote_id,quote_digest=expected_digest,quote_json=json.dumps(quote,sort_keys=True),accepted_at=clock.isoformat())
        db.execute(text('INSERT INTO buyer_supplier_quote_selection ('+','.join(row)+') VALUES ('+
                        ','.join(':'+key for key in row)+')'),row)
        return _receipt(row,'current')
