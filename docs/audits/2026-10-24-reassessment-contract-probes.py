"""Assessment-only proposed consumer contract; no production or existing tests changed.

An absent effective_from may fall back to observed_at. An explicitly malformed
effective_from must not silently become a valid observation. The failing cases
are retained as new contract gaps, not counted as repaired behaviour.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
candidate=Path(__file__).resolve().parent/'candidate'
sys.path.insert(0,str(candidate if candidate.is_dir() else Path(__file__).resolve().parents[2]))
import pytest
from src.app.services.market_evidence_admission import market_evidence_admission

NOW=datetime(2026,10,24,9,0,tzinfo=timezone.utc)
def valid():
    return dict(status='observed',source_system='assessment-owned',source_record_id='q-1',
        lineage_root='assessment',provenance_chain=['q-1'],observed_at=NOW.isoformat(),
        effective_from=NOW.isoformat(),effective_to=(NOW+timedelta(hours=1)).isoformat())

def test_valid_interval_has_a_positive_admission_control():
    assert market_evidence_admission(valid(),now=NOW) is None

def test_missing_start_retains_the_documented_observation_fallback():
    row=valid();row.pop('effective_from')
    assert market_evidence_admission(row,now=NOW) is None

def test_expired_interval_has_a_negative_control():
    row=valid();row['effective_to']=(NOW-timedelta(seconds=1)).isoformat()
    assert market_evidence_admission(row,now=NOW) is not None

@pytest.mark.parametrize('malformed',['not-a-date','2026-99-99T00:00:00Z'])
def test_explicitly_malformed_start_is_not_silently_admitted(malformed):
    row=valid();row['effective_from']=malformed
    assert market_evidence_admission(row,now=NOW) is not None

def test_demand_only_evidence_does_not_complete_a_lead_time_question():
    """Proposed usefulness contract: relevant SKU alone is not a relevant answer."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from src.app.services.market_analysis import MarketFinding,persist_findings
    from src.app.services.market_intelligence_agent import gather_market_context
    clock=datetime.now(timezone.utc); row=valid()
    row.update(subject_type='sku',subject_id='SKU-1',observed_at=clock.isoformat(),
        effective_from=clock.isoformat(),effective_to=(clock+timedelta(hours=1)).isoformat())
    engine=create_engine('sqlite://')
    try:
        with Session(engine) as db:
            persist_findings(db,[MarketFinding('demand_shift','SKU-1','warn',0.8,
                'Demand increased in the seven-day reviewed order aggregate.',row,'7d')],tenant_id='assessment')
            db.commit()
            context=gather_market_context(db,query='Market intelligence: what are supplier lead times for SKU-1?',
                tenant_id='assessment',result_skus=['SKU-1'],force=True,include_graph=False)
            assert context['delivery_status'] != 'available',context
    finally:
        engine.dispose()

def test_failed_semantic_index_registration_cannot_leave_a_value_after_erasure():
    """Fault injection: value write succeeds, erasure-index registration fails."""
    from src.app.services.semantic_cache import SemanticCache,CacheContract
    class SharedBackend:
        def __init__(self): self.data={}
        def set(self,*,name,value,ex): self.data[name]=value
        def get(self,key): return self.data.get(key)
        def sadd(self,*args): raise ConnectionError('assessment-index-registration-fault')
        def smembers(self,key): return set()
        def expire(self,*args): return True
        def delete(self,key): return int(self.data.pop(key,None) is not None)
    backend=SharedBackend()
    contract=CacheContract.resolve(tenant_id='assessment',subject_id='synthetic-buyer',
        corpus_version='c1',policy_version='p1',model_version='m1',evidence_cutoff='2026-10-24')
    writer=SemanticCache(redis_client=backend)
    writer.set_versioned(namespace='review',request='same-question',contract=contract,
        value={'synthetic_private_canary':'MUST_BE_ERASED'},source_id='assessment:q1',trust_score=1,ex=60)
    replacement=SemanticCache(redis_client=backend)
    replacement.erase_scope(contract)
    assert replacement.get_versioned(namespace='review',request='same-question',contract=contract) is None
