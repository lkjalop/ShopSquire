"""Read-only SQLite diagnosis of a fictional shop's forecast readiness.

Does not seed facts, fill missing dates with zero, or authorize procurement.
"""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def report(db, tenant, sku, as_of):
    def rows(sql, params=()):
        return [dict(row) for row in db.execute(sql, params)]

    scope = (tenant, sku)
    stock = rows('SELECT location_id,on_hand,reserved,available FROM inventory_level '
                 'WHERE tenant_id=? AND sku=?', scope)
    history = rows('SELECT scenario_id,fixture_digest,events_json FROM synthetic_shop_history '
                   'WHERE tenant_id=? AND sku=?', scope)
    events = [event for row in history for event in json.loads(row['events_json'])]
    offers = rows('SELECT supplier_id,currency,landed_unit_cost_cents,effective_from,effective_to,'
                  'simulation_only,status FROM supplier_offer WHERE tenant_id=? AND sku=?', scope)
    purchases = rows("SELECT COUNT(*) AS count,MIN(occurred_at) AS first_event,"
                     "MAX(occurred_at) AS last_event,COUNT(DISTINCT substr(occurred_at,1,10)) AS days "
                     "FROM marketing_event_fact WHERE tenant_id=? AND sku=? "
                     "AND event_type='purchase' AND status='active'", scope)[0]
    gaps = []
    if not stock:
        gaps.append('No scoped stock balances.')
    if not offers:
        gaps.append('No scoped supplier offers.')
    for offer in offers:
        start = datetime.fromisoformat(offer['effective_from'])
        end = datetime.fromisoformat(offer['effective_to']) if offer['effective_to'] else None
        offer['valid_at_cutoff'] = (offer['status'] == 'active' and start <= as_of
                                    and (end is None or as_of < end))
    if offers and not any(offer['valid_at_cutoff'] for offer in offers):
        gaps.append('All scoped supplier offers are expired, future-dated or inactive at the cutoff.')
    if purchases['count'] == 0:
        gaps.append('Forecast input has no active purchase facts for this tenant/SKU.')
    observed_days = sorted({str(e.get('observed_at', ''))[:10] for e in events})
    if len(observed_days) < 28:
        gaps.append('Fixture snapshots do not establish a daily demand history.')
    gaps.extend([
        'Daily reporting coverage and stockout censoring need explicit evidence; missing days are not zero demand.',
        'Join returns, cancellations, inbound commitments and dated supplier capacity/lead times before decision scoring.',
        'Freeze availability-time cutoffs and held-out periods; distinguish known bulk orders from forecast demand.',
        'Verify event-to-balance reconciliation before treating observations as decision-ready.',
    ])
    return dict(tenant_id=tenant, sku=sku, as_of=as_of.isoformat(), simulation_only=True, commerce_authority='none',
                status='not_ready_for_forecast_benchmark', stock=stock, supplier_offers=offers,
                fixture_scenarios=[{k:v for k,v in row.items() if k!='events_json'} for row in history],
                fixture_event_count=len(events), fixture_observed_days=observed_days,
                forecast_input=purchases, gaps=gaps,
                next_baseline='Reorder point using reconciled available stock, dated lead time, '
                              'explicit commitments and a covered demand window; measure total cost and stockouts.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--tenant', required=True)
    parser.add_argument('--sku', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--as-of', default=None, help='ISO timestamp with timezone; defaults to UTC now')
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        as_of = datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc)
        if as_of.tzinfo is None:
            parser.error('--as-of requires a timezone')
        result = report(db, args.tenant, args.sku, as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'status':result['status'], 'gaps':len(result['gaps'])}))


if __name__ == '__main__':
    main()
