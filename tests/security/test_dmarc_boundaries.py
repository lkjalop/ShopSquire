import io
import zipfile
import pytest
from sqlalchemy import create_engine
from src.app.services import dmarc_ingest as service


def xml(domain, end=100000, spf='fail', dkim='fail', count=3):
    return (f'<feedback><report_metadata><date_range><begin>{end-60}</begin>'
        f'<end>{end}</end></date_range></report_metadata><policy_published>'
        f'<domain>{domain}</domain></policy_published><record><row><source_ip>192.0.2.1</source_ip>'
        f'<count>{count}</count><policy_evaluated><spf>{spf}</spf><dkim>{dkim}</dkim>'
        '</policy_evaluated></row></record></feedback>').encode()


def test_summary_is_tenant_window_and_message_weighted(monkeypatch):
    engine = create_engine('sqlite://')
    monkeypatch.setattr(service, 'get_engine', lambda: engine)
    service.ingest_aggregate(xml('a.example'), tenant_id='a')
    service.ingest_aggregate(xml('a.example', spf='pass', count=7), tenant_id='a')
    service.ingest_aggregate(xml('b.example', count=900), tenant_id='b')
    service.ingest_aggregate(xml('old.example', end=1, count=900), tenant_id='a')
    result = service.get_summary(1, tenant_id='a', now=100001)
    assert result['fail_rate'] == .3
    assert [row[0] for row in result['top_domains']] == ['a.example']
    assert service.get_summary(1, tenant_id='other', now=100001)['fail_rate'] is None


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-16'])
def test_dtd_is_rejected_before_entity_expansion(encoding):
    with pytest.raises(ValueError, match='dtd_forbidden'):
        service._parse_aggregate_xml(
            '<!DOCTYPE feedback [<!ENTITY a "expanded">]><feedback>&a;</feedback>'.encode(encoding))


def test_zip_uncompressed_limit_precedes_database_access(monkeypatch):
    monkeypatch.setattr(service, '_MAX_BYTES', 2048)
    def forbidden():
        raise AssertionError('database accessed')
    monkeypatch.setattr(service, 'get_engine', forbidden)
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('report.xml', b' ' * 4096)
    with pytest.raises(ValueError, match='uncompressed_limit'):
        service.ingest_aggregate(payload.getvalue())
