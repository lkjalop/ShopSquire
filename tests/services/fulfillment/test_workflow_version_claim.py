from types import SimpleNamespace
from src.app.services.fulfillment import repository


def test_lost_version_claim_cannot_append_a_parallel_dispatch(monkeypatch):
    monkeypatch.setattr(repository,'ensure_tables',lambda *_:None)
    monkeypatch.setattr(repository,'current_version',lambda *_:SimpleNamespace(state_json={},version_id='old'))
    inserted=[]
    monkeypatch.setattr(repository,'_insert_version',lambda *a,**k:inserted.append(k) or 'new')
    class DB:
        def execute(self,*args,**kwargs):return SimpleNamespace(rowcount=0)
    result=repository.append_version(DB(),case_id='case',new_state='PROCUREMENT_IN_PROGRESS',
        event='purchase_order_dispatch_started',reason_code='claim',actor_type='HUMAN_OPERATOR',actor_id='operator',
        evidence={},state_patch={})
    assert result is None
    assert inserted==[]
