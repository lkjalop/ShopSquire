from datetime import datetime, timedelta, timezone

from src.app.services.market_evidence_admission import market_evidence_admission
from src.app.services.market_intelligence_agent import format_evidence_for_narration


def observation():
    now = datetime.now(timezone.utc)
    return dict(status='observed', source_system='supplier_feed', source_record_id='quote-1',
        lineage_root='supplier_feed', provenance_chain=['quote-1'], observed_at=now.isoformat(),
        effective_to=(now + timedelta(minutes=10)).isoformat(), summary='Quoted stock: 3')


def test_current_observation_is_narratable_but_expired_one_is_not():
    item = observation()
    assert market_evidence_admission(item) is None
    assert 'Quoted stock' in format_evidence_for_narration([item])
    item['effective_to'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    assert market_evidence_admission(item) == 'evidence_not_current'
    assert format_evidence_for_narration([item]) == ''


def test_no_expiry_or_missing_provenance_cannot_be_narrated():
    item = observation()
    item.pop('effective_to')
    assert market_evidence_admission(item) == 'validity_missing'
    item = observation()
    item.pop('source_record_id')
    assert market_evidence_admission(item) == 'provenance_incomplete'
