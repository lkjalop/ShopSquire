"""Citation learning must keep reads and verification within its controller."""
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_citation_learning_reads_and_verification_are_tenant_bound(monkeypatch):
    from src.app.services import citation_memory as memory
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
    engine = create_engine('sqlite:///:memory:')
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(memory, 'db_session', session)
    monkeypatch.setattr(memory, '_TABLE_ENSURED', False)
    ids = {}
    for tenant in ('a', 'b'):
        token = set_active_tenant_id(tenant)
        try:
            ids[tenant] = memory.store_claim(memory.AgentClaim('agent', 'recommendation', tenant, '{}'))
            memory.verify_claim(ids[tenant], outcome='observed', outcome_correct=True)
        finally:
            reset_active_tenant_id(token)
    token = set_active_tenant_id('a')
    try:
        assert [row['id'] for row in memory.get_trusted_claims(None, None, min_trust=0)] == [ids['a']]
        assert memory.get_claim_stats()['total_claims'] == 1
        assert memory.get_agent_trust_score('agent') == .55
        memory.verify_claim(ids['b'], outcome='foreign update', outcome_correct=False)
        with Session(engine) as db:
            assert db.execute(text('SELECT trust_score FROM agent_learnings WHERE id=:id'),
                              {'id': ids['b']}).scalar() == .55
    finally:
        reset_active_tenant_id(token)
        engine.dispose()
