"""Prepare fresh fictional evidence for ordinary-chat qualification diagnostics.

Only modifies a NEW copy of a disposable shop. This is not real product evidence.
It deliberately uses the existing compiler and contract, without pre-qualified SKUs.
"""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--vision',action='store_true',help='Enable the bounded installed vision model for image browser checks')
    parser.add_argument('--offline', action='store_true', help='Use fictional evidence with all model endpoints disabled')
    args=parser.parse_args()
    if args.offline and args.vision:
        parser.error('--vision requires a separately owned model runtime')
    source=args.source.resolve();directory=args.directory.resolve()
    if not all(p.is_relative_to(ROOT/'.artifacts') for p in [source,directory]):
        parser.error('Disposable artifacts only')
    directory.mkdir(parents=True,exist_ok=False)
    config=json.loads((source/'runtime-private.json').read_text(encoding='utf-8'))
    database=directory/'shop.sqlite3'
    with sqlite3.connect(source/'shop.sqlite3') as src,sqlite3.connect(database) as dest:src.backup(dest)
    config.update(DATABASE_URL='sqlite:///'+database.as_posix(),DATABASE_URL_RO='sqlite:///'+database.as_posix())
    profile=json.loads((ROOT/'config/local_demo_runtime.json').read_text(encoding='utf-8'))
    if profile['context_length']>4096 or profile['num_parallel']!=1 or profile['max_loaded_models']!=1:
        raise ValueError('bounded_model_configuration_required')
    url='http://127.0.0.1:'+str(profile['ollama_port']);model=profile['text_model']
    tags = {'models': []}
    digest = ''
    if not args.offline:
        with urllib.request.urlopen(url+'/api/tags',timeout=5) as response:tags=json.load(response)
        digest=next(row['digest'] for row in tags['models'] if row['name']==model)
    for key in ['ROUTER_MODEL','CLASSIFIER_MODEL','OLLAMA_DEFAULT_MODEL','OLLAMA_SMALL_MODEL',
        'OLLAMA_SUMMARY_MODEL','MULTI_INTENT_LLM_MODEL','LLM_PLANNER_MODEL','OPEN_WORLD_QUERY_MODEL','PORTFOLIO_NARRATION_MODEL']:
        config[key]=model
    for key in ['OLLAMA_DEFAULT_MODEL_DIGEST','OLLAMA_SMALL_MODEL_DIGEST','OLLAMA_MEDIUM_MODEL_DIGEST',
        'ROUTER_MODEL_DIGEST','CLASSIFIER_MODEL_DIGEST','RECOMMEND_INTENT_MODEL_DIGEST','MULTI_INTENT_LLM_MODEL_DIGEST','LLM_PLANNER_MODEL_DIGEST']:
        config[key]=digest
    config.update(OLLAMA_URL=url,ROUTER_MODEL_ENABLED='1',RECOMMEND_CORE_MODE='primary',OLLAMA_CONTEXT_LENGTH='4096',
        LOCAL_MODEL_MAX_CONCURRENCY='1',MODEL_ARTIFACT_ENROLLMENT_MODE='local_demo_observed_manifest',
        SEMANTIC_RESEARCH_FIXTURES_ENABLED='1',SEMANTIC_SIMULATION_AUTHORITY_ENABLED='1',
        SEMANTIC_RESEARCH_FIXTURE_ID='fictional-memory-runtime-v1',VITE_STOREFRONT_TENANT_ID='synthetic-electronics',
        VITE_ENABLE_SIMULATED_STOCK='1',RECOMMEND_PROCUREMENT_ADVICE_MODE='on',
        SEMANTIC_RESEARCH_FIXTURE_PATH=str(directory/'research.json'))
    if args.offline:
        config.update(ROUTER_MODEL_ENABLED='0', OLLAMA_URL='http://127.0.0.1:1',
            OLLAMA_BASE_URL='http://127.0.0.1:1', OLLAMA_HOST='http://127.0.0.1:1',
            CUDA_VISIBLE_DEVICES='-1', CV_PROVIDER='basic', CV_VISION_ENABLED='0',
            DISABLE_TRACING='1', JAEGER_ENABLED='0')
    if args.vision:
        vision=profile['vision_model']
        vision_digest=next(row['digest'] for row in tags['models'] if row['name']==vision)
        config.update(CV_PROVIDER='ollama',CV_VISION_ENABLED='1',CV_VISION_MODEL=vision,OLLAMA_VISION_MODEL=vision,
            CV_MODEL=vision,OLLAMA_VISION_MODEL_DIGEST=vision_digest,CV_VISION_MODEL_DIGEST=vision_digest,
            CV_IDENTITY_MODEL_DIGEST=vision_digest,
            CV_VISION_TOTAL_TIMEOUT_SEC=str(profile['vision_timeout_seconds']),
            CV_PROVIDER_TOTAL_TIMEOUT_S=str(profile['vision_timeout_seconds']+5),
            CV_VISION_MAX_OUTPUT_TOKENS=str(profile['vision_max_output_tokens']),OLLAMA_KEEP_ALIVE='2m')
    os.environ.update(config)
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import Session
    from src.app.services import portfolio_qualification as demo
    from src.app.models.orm import Product,ProductConfiguration,ProductEvidenceObservation,ProductAvailabilityObservation
    from src.app.services.taxonomy_registry import add_sold_node, upsert_classification
    now=datetime.now(timezone.utc)
    claim=demo._claim();claim['observed_at']=now.isoformat()
    with Session(create_engine(config['DATABASE_URL'])) as db:
        cfg=db.get(ProductConfiguration,demo.CONFIGURATION_ID)
        cfg.specification_observed_at=cfg.price_observed_at=cfg.availability_observed_at=now
        db.add(ProductEvidenceObservation(configuration_id=cfg.id,attribute_key='ram_gb',
            value_json={'value':cfg.ram_installed_gb,'simulation_only':True},unit='GB',claim_class='attested',
            evidence_status='observed',source_id='simulation:shop-inventory',source_record_id='fixture:current-replay',
            source_excerpt='Invented RAM capacity for current fictional replay only.',observed_at=now))
        db.add(ProductAvailabilityObservation(configuration_id=cfg.id,location_id='simulation-network',status='in_stock',
            quantity=15,source_record_id='simulation:current-replay',observed_at=now))
        companion=json.loads((ROOT/'config/conversational_product_offer_fixture.json').read_text(encoding='utf-8'))
        if companion['base_configuration_id']!=cfg.id or companion['simulation_only'] is not True:
            raise ValueError('scoped_simulation_pair_required')
        product=db.execute(select(Product).where(Product.sku==companion['target_sku'])).scalar_one()
        target_id=demo.TENANT+':'+product.sku
        target=db.get(ProductConfiguration,target_id)
        if not target:
            target=ProductConfiguration(id=target_id,tenant_id=demo.TENANT,product_id=product.id,sku=product.sku,
                title=companion['target_title'],configuration_hash=hashlib.sha256(companion['version'].encode()).hexdigest())
            db.add(target)
        target.price_cents=product.price_cents;target.currency=product.currency;target.price_observed_at=now
        from src.app.services.commerce_catalog import upsert_inventory
        upsert_inventory(db,tenant_id=demo.TENANT,sku=product.sku,location_id='simulation-companion',on_hand=10,reserved=0)
        db.merge(ProductEvidenceObservation(id=companion['version'],configuration_id=cfg.id,
            attribute_key='supported_product_relation',claim_class='attested',evidence_status='observed',
            source_id='simulation:reviewed-pair-fixture',source_record_id=companion['version'],
            value_json=dict(target_configuration_id=target_id,kind=companion['kind'],need=companion['need'],
                supported=True,benefit=companion['benefit'],simulation_only=True),
            source_excerpt=companion['benefit'],observed_at=now,expires_at=now+timedelta(days=1)))
        add_sold_node(db,node_handle='el-6-6',tenant_id=demo.TENANT)
        # This explicit fixture classification permits retrieval only. Product
        # fit still requires the selected contract and the independent compiler.
        if not upsert_classification(db, sku=cfg.sku, node_handle='el-6-6', tenant_id=demo.TENANT,
                source='simulation:qualification-fixture', status='approved',
                approved_by='fictional-fixture'):
            raise ValueError('fixture_catalog_classification_failed')
        db.commit()
    policy=dict(policy_version='semantic-source-v1',review_status='simulation_contract',reviewer_type='deterministic_fixture',
        reviewed_by='versioned-test-contract',licence='synthetic-demonstration-only',trust_tier='simulation',
        allowed_claim_types=['minimum_requirements'],freshness_status='fresh',simulation_only=True)
    fixture=dict(fixture_version='fictional-memory-runtime-v1',simulation_only=True,tenant_ids=[demo.TENANT],
        requires_explicit_consent=True,concept_triggers=['fictional memory lab'],result_authority='simulation_contract_only',
        sources=[dict(title='Fictional Memory Lab bounded specification',url='fixture://memory-lab-v1',
            snippet=claim['source_excerpt'],fetched_ts=now.isoformat())],claims=[claim],
        normalized_evidence=[dict(concept='Fictional Memory Lab',status='resolved',claim=claim['source_excerpt'],
            claim_type='minimum_requirements',source_id=claim['source_id'],source_record_id=claim['source_record_id'],
            source_revision=claim['source_revision'],observed_at=now.isoformat(),citation_id='fixture:memory-lab-runtime-v1',source_policy=policy)])
    (directory/'research.json').write_text(json.dumps(fixture,indent=2),encoding='utf-8')
    (directory/'runtime-private.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print(json.dumps(dict(directory=str(directory),model=None if args.offline else model,
        offline=args.offline, simulation_only=True,prequalified_skus=[])))


if __name__=='__main__':main()
