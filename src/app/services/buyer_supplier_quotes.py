"""Buyer-safe read model of reviewed supplier replies; caller authenticates ownership.

Procurement costs, contacts and operator credentials never enter this projection.
The current catalogue price plus disclosed freight is an estimate, not a checkout
offer, inventory reservation or purchase permission.
"""
import hashlib
import json
from datetime import datetime, timezone
from sqlalchemy import text
from src.app.services import supplier_enquiry_journey as enquiries
from src.app.services.buyer_supplier_constraints import assess as assess_constraints


def project_quotes(db, *, tenant_id, case_id, now=None):
    ids=db.execute(text('SELECT id FROM supplier_enquiry_request WHERE tenant_id=:tenant '
        'AND case_id=:case ORDER BY created_at,id'),{'tenant':tenant_id,'case':case_id}).scalars().all()
    quotes=[]
    waiting_review=False
    for enquiry_id in ids:
        enquiry=enquiries.view(db,tenant_id=tenant_id,enquiry_id=enquiry_id,now=now)
        product=db.execute(text('SELECT price_cents,currency,active FROM products WHERE sku=:sku'),
            {'sku':enquiry['sku']}).first()
        for row in enquiry['quotes']:
            if row['status']!='reviewed':
                waiting_review=True
                continue
            terms=row['terms'];assessment=row['assessment']
            price_known=bool(product and product[2] and type(product[0]) is int and product[0]>=0
                and product[1]==terms['currency'])
            eligible=bool(assessment['eligible'] and price_known)
            quantity=assessment['sourced_quantity']
            covered=enquiry['requested_quantity']-enquiry['shortfall']+quantity
            constraints=assess_constraints(db,tenant_id=tenant_id,case_id=case_id,
                revision=enquiry['case_revision'],currency=terms['currency'],
                unit_price_cents=product[0] if price_known else 0,
                covered_total_cents=covered*product[0]+terms['freight_cents'] if price_known else 0,
                lead_days=terms['lead_days'],now=now or datetime.now(timezone.utc))
            eligible=eligible and constraints['status']!='blocked'
            projection=dict(quote_id=row['id'],enquiry_id=enquiry_id,case_revision=enquiry['case_revision'],
                sku=terms['sku'],quantity=quantity,offered_quantity=terms['quantity'],
                requested_quantity=enquiry['requested_quantity'],covered_order_quantity=covered,
                uncovered_quantity=max(0,enquiry['shortfall']-quantity),
                minimum_order=terms['minimum_order'],coverage=assessment['coverage'],
                eligible=eligible,reason=row['reason'] or ('current_retail_price_required' if not price_known else constraints['reason']),
                requirement_assessment=constraints,
                currency=terms['currency'],unit_price_cents=product[0] if price_known else None,
                freight_cents=terms['freight_cents'],
                total_price_cents=quantity*product[0]+terms['freight_cents'] if eligible else None,
                covered_order_total_price_cents=covered*product[0]+terms['freight_cents'] if eligible else None,
                estimated_lead_days=terms['lead_days'],expires_at=terms['expires_at'],
                pricing_basis='current_catalogue_price_plus_disclosed_freight',
                commerce_authority='none')
            projection['selection_digest']=hashlib.sha256(json.dumps(projection,sort_keys=True).encode()).hexdigest()
            quotes.append(projection)
    return dict(case_id=case_id,quotes=quotes,
        status='reviewed_options' if quotes else 'awaiting_review' if waiting_review else 'awaiting_reply' if ids else 'no_enquiry',
        commerce_authority='none')
