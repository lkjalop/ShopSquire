"""Connect a versioned fictional scenario to canonical observations and a decision snapshot."""
import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path('config/merchant_market_pilot.json'))
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    cfg=json.loads(args.config.read_text())
    from sqlalchemy import text
    from src.app.models.db import db_session
    from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
    from src.app.services.merchant_decision_dataset import build_dataset, persist_snapshot, reorder_baseline
    from src.app.services.authoritative_business_feed import ingest_authoritative_observations
    from src.app.services.market_facts import record_marketing_event
    from src.app.services.merchant_evidence_retrieval import extract_proposals,review_document
    with db_session() as db:
        product=db.execute(text('SELECT sku,name,currency FROM products WHERE sku=:sku'),{'sku':cfg['sku']}).mappings().first()
        if not product or product['currency']!=cfg['currency']:
            raise ValueError('existing_catalogue_configuration_required')
        product=dict(product)
    replay=materialize_canonical_replay(cfg['scenario_id'],seed=cfg['seed'],days=cfg['days'],
        tenant_id=cfg['tenant_id'],start_date=date.fromisoformat(cfg['start_date']),
        target_variant_id=cfg['sku'],currency=cfg['currency'],include_lifecycle_probes=False)
    cutoff=datetime.fromisoformat(cfg['as_of'])
    if cfg.get('include_operational_lifecycle'):
        from src.app.adapters.synthetic_market_operations import append_after_close_operations
        replay=append_after_close_operations(replay,as_of=cfg['as_of'])
    dataset=build_dataset(replay,as_of=cutoff)
    quote={**cfg['quote'],**{k:cfg[k] for k in ('tenant_id','sku','currency')}}
    decision=reorder_baseline(dataset,quote=quote,now=cutoff)
    if decision['status']!='advisory':
        raise ValueError('pilot_inputs_not_reconciled:'+decision['reason'])
    source='synthetic_supply_replay:'+replay['manifest']['parameter_hash']
    receipt=ingest_authoritative_observations(tenant_id=cfg['tenant_id'],source=source,
        observations=[o for o in replay['observations'] if datetime.fromisoformat(o.event_time)<=cutoff])
    inserted=0
    with db_session() as db:
        for day in dataset['daily']:
            if not day['observed_sales_units']:
                continue  # explicit zero-day coverage is in the immutable snapshot
            record=dataset['source_id']+':purchase:'+day['date']
            inserted+=int(record_marketing_event(db,dict(tenant_id=cfg['tenant_id'],sku=cfg['sku'],
                deduplication_id=record,event_type='purchase',quantity=day['observed_sales_units'],
                currency=cfg['currency'],consent_state='not_required',source_system='synthetic_scenario',
                source_record_id=record,occurred_at=day['available_at'],confidence=1.0,
                provenance_chain=[dataset['source_id'],cfg['id'],'simulation_only'],
                freshness_policy='scenario_history_only'),commit=False))
        documents=[]
        for field,value,unit,sentence in [
            ('lead_time',quote['lead_time_days'],'days',f"Delivery lead time is {quote['lead_time_days']} days."),
            ('capacity',quote['capacity_units'],'units',f"Supplier delivery capacity is {quote['capacity_units']} units.")]:
            document=dict(id=quote['source_id']+':'+field,tenant_id=cfg['tenant_id'],sku=cfg['sku'],
                source_id=quote['source_id'],text='Fictional supplier fixture. '+sentence,
                observed_at=quote['observed_at'],expires_at=quote['expires_at'],simulation_only=True)
            claims=[dict(field=field,value=value,unit=unit,quote=sentence)]
            proposals=extract_proposals(document,{'claims':claims})
            documents.append(review_document(document,proposals,expected_claims=claims,reviewer='fixture-author-reviewed-terms'))
        snapshot=persist_snapshot(db,dataset=dataset,quote=quote,evidence_documents=documents)
        db.commit()
    result=dict(snapshot_id=snapshot,product=product,canonical_ingestion=receipt,
        purchase_facts_inserted=inserted,covered_days=len(dataset['daily']),decision=decision,
        catalogue_binding=replay['manifest']['catalog_binding'],assumptions=cfg,
        historical_prices_and_demand_are_synthetic=True,live_operational_stock_modified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(snapshot_id=snapshot,decision=decision['decision'],purchase_facts_inserted=inserted)))


if __name__=='__main__':
    main()
