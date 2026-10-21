"""Read-only current stock and lifecycle projection for an owned buyer case."""
from datetime import datetime, timezone
from sqlalchemy import text
from src.app.services.case_contract_binding import _owned_case


def read_case_stock(db, *, tenant_id, case_id, uid, sku, now=None):
    case = _owned_case(db, tenant_id=tenant_id, case_id=case_id, uid=uid)
    clock = now or datetime.now(timezone.utc)
    rows=db.execute(text('SELECT location_id,on_hand,reserved,available FROM inventory_level '
        'WHERE tenant_id=:tenant AND sku=:sku ORDER BY location_id'),{'tenant':tenant_id,'sku':sku}).mappings().all()
    selection=db.execute(text('SELECT selection_id,requested_quantity,revision FROM shopping_case_fulfillment_selections '
        'WHERE tenant_id=:tenant AND case_id=:case AND preferred_sku=:sku ORDER BY revision DESC LIMIT 1'),
        {'tenant':tenant_id,'case':case_id,'sku':sku}).mappings().first()
    accepted=None
    if selection:
        held=db.execute(text("SELECT COALESCE(SUM(quantity),0) FROM inventory_reservation WHERE tenant_id=:tenant "
            "AND status='reserved' AND reservation_id LIKE :prefix AND (expires_at IS NULL OR expires_at>:now)"),
            {'tenant':tenant_id,'prefix':'selection:'+selection['selection_id']+':%',
             'now':clock.isoformat()}).scalar()
        expiry=db.execute(text("SELECT MIN(expires_at) FROM inventory_reservation WHERE tenant_id=:tenant "
            "AND status='reserved' AND reservation_id LIKE :prefix"),
            {'tenant':tenant_id,'prefix':'selection:'+selection['selection_id']+':%'}).scalar()
        accepted=dict(selection,held_quantity=held,shortfall=selection['requested_quantity']-held,
                      hold_expires_at=expiry)
        lifecycle=db.execute(text("SELECT COALESCE(SUM(CASE WHEN status IN ('shipped','returned') THEN quantity ELSE 0 END),0), "
            "COALESCE(SUM(returned_quantity),0) FROM inventory_reservation WHERE tenant_id=:tenant AND reservation_id LIKE :prefix"),
            {'tenant':tenant_id,'prefix':'selection:'+selection['selection_id']+':%'}).one()
        accepted.update(shipped_quantity=lifecycle[0],returned_quantity=lifecycle[1],
            shortfall=max(0,selection['requested_quantity']-held-lifecycle[0]))
    return dict(case_revision=case.revision,sku=sku,locations=[dict(r) for r in rows],
                available=sum(r['available'] for r in rows),accepted=accepted)
