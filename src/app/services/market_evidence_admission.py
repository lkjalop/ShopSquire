"""Consumer-time validity checks: ingestion freshness does not survive indefinitely."""
from datetime import datetime, timezone


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def market_evidence_admission(finding, *, now=None):
    stamp = now or datetime.now(timezone.utc)
    if finding.get('status') != 'observed':
        return 'not_observed'
    if not all(finding.get(key) for key in ('source_system', 'source_record_id',
            'lineage_root', 'provenance_chain', 'observed_at')):
        return 'provenance_incomplete'
    observed = _time(finding.get('observed_at'))
    explicit_start = finding.get('effective_from')
    start = _time(explicit_start) if explicit_start is not None else observed
    if explicit_start is not None and start is None:
        return 'validity_invalid'
    end = _time(finding.get('effective_to'))
    if observed is None or end is None or start is None:
        return 'validity_missing'
    for field in ('published_at', 'available_at'):
        explicit = finding.get(field)
        if explicit is None:
            continue
        source_time = _time(explicit)
        if source_time is None:
            return 'source_time_invalid'
        if source_time > stamp:
            return 'evidence_not_current'
    if observed > stamp or start > stamp or end <= start or end <= stamp:
        return 'evidence_not_current'
    return None
