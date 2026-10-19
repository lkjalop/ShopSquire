from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from src.app.services.market_analysis import MarketFinding, persist_findings, load_recent_findings
from src.app.services.market_intelligence_agent import gather_market_context


@pytest.mark.parametrize('expired', [False, True])
def test_delivered_market_claim_keeps_its_source_and_current_validity(tmp_path, expired):
    engine = create_engine('sqlite:///' + str(tmp_path / 'market.sqlite3'))
    now = datetime.now(timezone.utc)
    finding = MarketFinding('demand_shift', 'SKU-1', 'warn', 0.8,
        'Demand increased in the reviewed seven-day order aggregate.', {
            'subject_type': 'sku', 'subject_id': 'SKU-1', 'source_system': 'owned-orders',
            'source_record_id': 'aggregate-17', 'lineage_root': 'orders',
            'provenance_chain': ['orders/aggregate-17'], 'status': 'observed',
            'observed_at': (now - timedelta(days=2)).isoformat(),
            'effective_from': (now - timedelta(days=2)).isoformat(),
            'effective_to': (now + timedelta(days=-1 if expired else 1)).isoformat(),
        }, '7d')
    try:
        with Session(engine) as db:
            persist_findings(db, [finding], tenant_id='tenant-a')
            db.commit()
            result = gather_market_context(db, query='Market intelligence for this request',
                tenant_id='tenant-a', result_skus=['SKU-1'], force=True)
        if expired:
            assert result['delivery_status'] == 'blocked'
            assert result['market_evidence']['findings'] == []
            assert result['market_evidence']['citations'] == []
        else:
            assert result['delivery_status'] == 'available'
            citation = result['market_evidence']['citations'][0]
            assert citation['source_system'] == 'owned-orders'
            assert citation['source_record_id'] == 'aggregate-17'
            assert citation['observed_at'] == finding.evidence['observed_at']
            assert citation['effective_to'] == finding.evidence['effective_to']
            assert result['market_evidence']['findings'][0]['citation_ref'] == citation['id']
            assert 'owned-orders:aggregate-17' in result['narration_note']
    finally:
        engine.dispose()


def test_market_provider_failure_is_distinct_from_no_current_evidence(monkeypatch):
    monkeypatch.setattr('src.app.services.hippograph_feedback.build_hippograph_insights', lambda *a, **k: [])

    def unavailable(*args, **kwargs):
        raise RuntimeError('owned-provider-fault')

    monkeypatch.setattr('src.app.services.market_analysis.load_recent_findings', unavailable)
    result = gather_market_context(object(), query='market intelligence', force=True, tenant_id='tenant-a')
    assert result['delivery_status'] == 'unavailable'
    assert result['delivery_reason'] == 'market_evidence_unavailable'
    assert result['market_evidence']['findings'] == []
    assert result['market_evidence']['citations'] == []


def test_market_read_does_not_attempt_schema_mutation(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'empty.sqlite3'))
    statements = []
    event.listen(engine, 'before_cursor_execute',
        lambda conn, cursor, statement, parameters, context, many: statements.append(statement))
    try:
        with Session(engine) as db:
            assert load_recent_findings(db, tenant_id='tenant-a') == []
        assert not any(sql.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'INSERT ', 'UPDATE ', 'DELETE '))
                       for sql in statements)
    finally:
        engine.dispose()
