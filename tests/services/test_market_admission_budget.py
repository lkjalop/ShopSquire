"""Admission budgets must not let ineligible diagnostics hide current evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.services.market_analysis import MarketFinding, persist_findings
from src.app.services.market_intelligence_agent import (
    _finding_dict, format_evidence_for_narration, gather_market_context,
)


def market_finding(key, *, validity='current', confidence=0.6, now=None):
    now = now or datetime.now(timezone.utc)
    evidence = {
        'subject_type': 'sku', 'subject_id': 'SKU-MARKET', 'source_system': 'owned-lab-orders',
        'source_record_id': 'aggregate-' + key, 'lineage_root': 'owned-lab-orders',
        'provenance_chain': ['owned-lab-orders/aggregate-' + key], 'status': 'observed',
        'observed_at': (now - timedelta(hours=2)).isoformat(),
        'effective_from': (now - timedelta(hours=2)).isoformat(),
        'effective_to': (now + timedelta(days=1)).isoformat(),
    }
    if validity == 'unverified':
        evidence['status'] = 'insufficient_data'
    elif validity == 'expired':
        evidence['effective_to'] = (now - timedelta(hours=1)).isoformat()
    elif validity == 'future':
        evidence.update(observed_at=(now + timedelta(days=1)).isoformat(),
            effective_from=(now + timedelta(days=1)).isoformat(),
            effective_to=(now + timedelta(days=2)).isoformat())
    elif validity == 'missing_provenance':
        evidence['provenance_chain'] = []
    return MarketFinding('lab_' + key, 'SKU-MARKET', 'warn', confidence,
        key + ': controlled lab aggregate', evidence, '7d')


@pytest.fixture
def database(tmp_path):
    engine = create_runtime_engine('sqlite:///' + (tmp_path / 'market.sqlite3').as_posix())
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def gather(db, *, limit=1):
    return gather_market_context(db, query='Market intelligence for the current request',
        result_skus=['SKU-MARKET'], tenant_id='lab-market-tenant', force=True,
        max_findings=limit, include_graph=False)


@pytest.mark.parametrize('validity', ['unverified', 'expired', 'future', 'missing_provenance'])
def test_ineligible_higher_ranked_records_do_not_consume_the_delivery_budget(database, validity):
    bad = [market_finding('WITHHELD_' + str(i), validity=validity, confidence=1.0) for i in range(4)]
    valid = market_finding('CURRENT_ADMITTED_RECORD')
    persist_findings(database, [*bad, valid], tenant_id='lab-market-tenant')
    database.commit()
    before = database.execute(text('SELECT id,evidence_json,status FROM market_finding ORDER BY id')).all()
    result = gather(database)
    assert result['delivery_status'] == 'available'
    assert [row['summary'] for row in result['market_evidence']['findings']] == [valid.summary]
    assert result['market_evidence']['citations'][0]['source_record_id'] == 'aggregate-CURRENT_ADMITTED_RECORD'
    assert 'CURRENT_ADMITTED_RECORD' in result['narration_note']
    assert 'WITHHELD_' not in result['narration_note']
    assert len(result['market_findings']) == 1
    assert result['market_findings'][0]['admission_status'] == 'admitted'
    assert result['withheld_market_findings']
    assert database.execute(text('SELECT id,evidence_json,status FROM market_finding ORDER BY id')).all() == before


def test_narration_counts_only_admitted_records_toward_its_limit():
    records = [market_finding('WITHHELD_' + str(i), validity='expired') for i in range(4)]
    records.append(market_finding('CURRENT_ADMITTED_RECORD'))
    normalized = [_finding_dict(row, tenant_id='lab-market-tenant') for row in records]
    note = format_evidence_for_narration(normalized, max_items=1)
    assert 'CURRENT_ADMITTED_RECORD' in note
    assert 'WITHHELD_' not in note
    assert format_evidence_for_narration(normalized, max_items=0) == ''


def test_available_structured_evidence_also_reaches_the_narrator(database):
    records = [market_finding('WITHHELD_' + str(i), validity='expired', confidence=1.0) for i in range(4)]
    records.append(market_finding('CURRENT_ADMITTED_RECORD'))
    persist_findings(database, records, tenant_id='lab-market-tenant')
    database.commit()
    result = gather(database, limit=8)
    assert result['delivery_status'] == 'available'
    assert 'CURRENT_ADMITTED_RECORD' in result['narration_note']
    assert 'WITHHELD_' not in result['narration_note']


def test_delivery_and_narration_keep_the_admitted_record_limit(database):
    records = [market_finding('VALID_' + str(i), confidence=0.9-i/10) for i in range(3)]
    persist_findings(database, records, tenant_id='lab-market-tenant')
    database.commit()
    result = gather(database)
    assert len(result['market_findings']) == len(result['market_evidence']['findings']) == len(result['market_evidence']['citations']) == 1
    assert 'VALID_0' in result['narration_note']
    assert 'VALID_1' not in result['narration_note']
    assert 'VALID_2' not in result['narration_note']


def test_no_admitted_evidence_still_blocks_delivery(database):
    persist_findings(database, [market_finding('WITHHELD', validity='expired')], tenant_id='lab-market-tenant')
    database.commit()
    result = gather(database)
    assert result['delivery_status'] == 'blocked'
    assert result['market_evidence']['findings'] == result['market_evidence']['citations'] == []
    assert result['narration_note'] == ''


def test_zero_delivery_budget_cannot_leak_an_admitted_record_into_narration(database):
    persist_findings(database, [market_finding('CURRENT_ADMITTED_RECORD')], tenant_id='lab-market-tenant')
    database.commit()
    result = gather(database, limit=0)
    assert result['market_findings'] == result['market_evidence']['findings'] == []
    assert result['narration_note'] == ''
