"""Release invariants, tested through normal application imports."""
from contextlib import contextmanager
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_missing_evaluator_has_no_quality_scores(monkeypatch):
    from src.app.services.ragas_eval import _compute_ragas_like
    monkeypatch.setitem(sys.modules, 'ragas', None)
    monkeypatch.setitem(sys.modules, 'ragas.metrics', None)
    scores = _compute_ragas_like('price?', {'order': 'price 10'}, 'price 99999. ' * 50)
    assert all(scores.get(key) is None for key in (
        'faithfulness', 'answer_relevance', 'context_precision', 'context_recall'))


def test_empty_evaluation_window_blocks_release(monkeypatch):
    from src.app.services import ragas_eval
    @contextmanager
    def session():
        yield SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchall=lambda: []))
    monkeypatch.setattr(ragas_eval, 'db_session', session)
    assert ragas_eval.ci_guard_check()['ok'] is False


def test_security_analytics_excludes_foreign_and_unowned_rows(monkeypatch):
    from src.app.routers import analytics
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as db:
        db.execute(text('CREATE TABLE security_events(tenant_id TEXT, details TEXT, event_time TEXT)'))
        for tenant in ['a', 'b', None]:
            db.execute(text('INSERT INTO security_events VALUES (:t, :d, :s)'),
                       {'t': tenant, 'd': '{"analysis":{"tenant":"' + str(tenant) + '"}}', 's': '2026-09-15'})
    @contextmanager
    def session(**kwargs):
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(analytics, 'read_session', session)
    monkeypatch.setattr(analytics, 'call_with_resilience', lambda name, fn, **kw: fn())
    token = set_active_tenant_id('a')
    try:
        assert analytics._load_security_events() == [{'tenant': 'a'}]
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def test_failed_stage_preserves_accepted_output():
    from src.app.services.recommendation_core.stage_runner import run_guarded_stage
    response = SimpleNamespace(_msg_priority=1, products=['accepted'], extras={'nested': [1]},
                               record_stage=lambda *a, **kw: None)
    def broken():
        response.products.clear()
        response.extras['nested'].append(2)
        response._msg_priority = 999
        raise ValueError('after mutation')
    run_guarded_stage(response, 'enrichment', broken)
    assert response.products == ['accepted']
    assert response.extras == {'nested': [1]}
    assert response._msg_priority == 1


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


def test_unknown_stage_dependency_rejected():
    from src.app.services.recommendation_core.typed_stage_coordinator import (
        CoordinatedStage, RecommendationPhase, validate_stage_order)
    with pytest.raises(ValueError):
        validate_stage_order([CoordinatedStage(RecommendationPhase.FIT, 'fit', lambda: None,
            stage_id='fit', dependency_stage_ids=('missing',))])


def test_resilience_worker_preserves_tenant_context():
    from src.app.services.dependency_resilience import call_with_resilience, shutdown_resilience_executor
    from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id, current_tenant_id
    token = set_active_tenant_id('worker-tenant')
    try:
        assert call_with_resilience('test.tenant', current_tenant_id) == 'worker-tenant'
    finally:
        reset_active_tenant_id(token)
        shutdown_resilience_executor(wait=True)


def test_failed_dependency_blocks_downstream_side_effects():
    from src.app.services.recommendation_core.typed_stage_coordinator import (
        CoordinatedStage, RecommendationPhase, run_coordinated_stages)
    events = []
    response = SimpleNamespace(_msg_priority=0, record_stage=lambda name, **kw: events.append((name, kw['status'])))
    def broken():
        raise RuntimeError('evidence failed')
    run_coordinated_stages(response, [
        CoordinatedStage(RecommendationPhase.EVIDENCE, 'evidence', broken, stage_id='e'),
        CoordinatedStage(RecommendationPhase.FIT, 'fit', lambda: pytest.fail('must not run'), dependency_stage_ids=('e',))])
    assert events == [('evidence', 'error'), ('fit', 'blocked')]


def test_isolated_stage_does_not_publish_before_success():
    from src.app.services.recommendation_core.stage_runner import run_guarded_stage
    response = SimpleNamespace(_msg_priority=0, products=['old'], record_stage=lambda *a, **kw: None)
    def operation(candidate):
        candidate.products[:] = ['new']
        assert response.products == ['old']
    assert run_guarded_stage(response, 'fit', operation, isolated=True) == 'ok'
    assert response.products == ['new']


@pytest.mark.parametrize('value', ['not-a-price', None, -1, True, 1.5, float('inf')])
def test_invalid_spend_cannot_select_auto_tier(value):
    from src.app.services.fulfillment.approval_policy import required_approval_tier
    with pytest.raises((TypeError, ValueError)):
        required_approval_tier(value)
