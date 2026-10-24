import json
from contextlib import contextmanager
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from src.app.services import ragas_eval
from src.app.services.evaluation_contract import METRICS, CONTRACT_VERSION, persist_evaluation
from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id


@pytest.fixture
def evaluation_db(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE ragas_eval_results (eval_id TEXT PRIMARY KEY, decision_log_id TEXT,
            tenant_id TEXT, evaluation_status TEXT, faithfulness REAL, answer_relevance REAL,
            context_precision REAL, context_recall REAL, evaluator_model TEXT, created_at TEXT, metadata_json TEXT)'''))
        db.execute(text('CREATE TABLE ragas_baseline (id TEXT PRIMARY KEY, tenant_id TEXT, baseline_score REAL, metadata_json TEXT)'))
        db.execute(text('CREATE TABLE decision_logs (id TEXT, tenant_id TEXT, input_data TEXT, retrieved_context TEXT, proposed_action TEXT, created_at TEXT)'))
    @contextmanager
    def session():
        with Session(engine) as db:
            yield db
    monkeypatch.setattr(ragas_eval, 'db_session', session)
    token = set_active_tenant_id('tenant-a')
    try:
        yield session
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def seed_measurement(session, *, score=.9, status='evaluated', tenant='tenant-a', stamp=None, model='model-1'):
    import uuid
    metadata = {'dataset_id': 'reviewed-v1', 'model_id': model, 'prompt_version': 'prompt-1',
                'config_hash': 'config-1', 'evaluator_version': 'test-evaluator-1'}
    with session() as db:
        persist_evaluation(db, {'eval_id': uuid.uuid4().hex, 'status': status,
            'metrics': dict.fromkeys(METRICS, score if status == 'evaluated' else None),
            'evaluated_at': stamp or datetime.now(timezone.utc).isoformat(), **metadata},
            decision_id='d1', tenant_id=tenant)
        db.commit()
    return metadata


def approve_baseline(session, metadata, *, minimum=1):
    with session() as db:
        db.execute(text('INSERT INTO ragas_baseline VALUES (:id, :tenant, :score, :metadata)'),
            {'id': 'tenant-a', 'tenant': 'tenant-a', 'score': .9,
             'metadata': json.dumps({**metadata, 'approved_by': 'reviewer',
                'approved_at': datetime.now(timezone.utc).isoformat(), 'min_samples': minimum})})
        db.commit()


def test_no_implicit_baseline_from_first_measurement(evaluation_db):
    seed_measurement(evaluation_db)
    assert ragas_eval.ci_guard_check() == {'ok': False, 'reason': 'approved_baseline_required'}
    with evaluation_db() as db:
        assert db.execute(text('SELECT COUNT(*) FROM ragas_baseline')).scalar() == 0


def test_reviewed_fresh_matching_measurement_passes(evaluation_db):
    approve_baseline(evaluation_db, seed_measurement(evaluation_db))
    assert ragas_eval.ci_guard_check()['ok'] is True


@pytest.mark.parametrize('variation', ['unavailable', 'foreign', 'stale', 'different_model'])
def test_unusable_measurements_do_not_pass(evaluation_db, variation):
    expected = {'dataset_id': 'reviewed-v1', 'model_id': 'model-1', 'prompt_version': 'prompt-1',
                'config_hash': 'config-1', 'evaluator_version': 'test-evaluator-1'}
    approve_baseline(evaluation_db, expected)
    seed_measurement(evaluation_db, status='unavailable' if variation == 'unavailable' else 'evaluated',
        tenant='tenant-b' if variation == 'foreign' else 'tenant-a',
        stamp='2020-01-01T00:00:00+00:00' if variation == 'stale' else None,
        model='different' if variation == 'different_model' else 'model-1')
    assert ragas_eval.ci_guard_check()['ok'] is False


def test_summary_keeps_missing_scores_null_and_tenant_scoped(evaluation_db):
    seed_measurement(evaluation_db, status='unavailable')
    seed_measurement(evaluation_db, tenant='tenant-b', score=1)
    with evaluation_db() as db:
        summary = ragas_eval.evaluation_summary(db)
    assert summary['count'] == 1
    assert summary['evaluated_count'] == 0
    assert summary['averages'] == dict.fromkeys(METRICS)


def test_api_outer_verdict_matches_failed_gate(monkeypatch):
    from src.app.routers.analytics import ragas_ci_guard
    monkeypatch.setattr(ragas_eval, 'ci_guard_check', lambda: {'ok': False, 'reason': 'no_data'})
    assert ragas_ci_guard(role='owner')['ok'] is False
