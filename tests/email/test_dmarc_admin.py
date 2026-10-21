import io
import zipfile
import json
import time
import pytest

from tests.legacy_endpoint_runtime import endpoint_runtime

@pytest.fixture
def client(endpoint_runtime):
    return endpoint_runtime[1]


def _sample_dmarc_xml(*, report_end=None, domain='example.com'):
    report_end = int(time.time()) if report_end is None else int(report_end)
    return b"""
<feedback>
  <report_metadata>
    <org_name>ExampleCorp</org_name>
    <email>postmaster@example.com</email>
    <report_id>12345</report_id>
    <date_range>
      <begin>1700000000</begin>
      <end>1700003600</end>
    </date_range>
  </report_metadata>
  <policy_published>
    <domain>example.com</domain>
    <adkim>r</adkim>
    <aspf>r</aspf>
    <p>none</p>
    <sp>none</sp>
    <pct>100</pct>
  </policy_published>
  <record>
    <row>
      <source_ip>203.0.113.5</source_ip>
      <count>7</count>
    </row>
    <policy_evaluated>
      <disposition>none</disposition>
      <dkim>fail</dkim>
      <spf>pass</spf>
    </policy_evaluated>
  </record>
  <record>
    <row>
      <source_ip>198.51.100.9</source_ip>
      <count>3</count>
    </row>
    <policy_evaluated>
      <disposition>none</disposition>
      <dkim>fail</dkim>
      <spf>fail</spf>
    </policy_evaluated>
  </record>
</feedback>
""".replace(b'1700000000', str(report_end - 3600).encode()).replace(
        b'1700003600', str(report_end).encode()).replace(b'example.com', domain.encode())


_OWNER_HEADERS = {"x-api-key": "local-owner-key"}


def test_dmarc_ingest_and_summary_xml(client):
    c = client
    xml = _sample_dmarc_xml()
    files = {"file": ("dmarc.xml", xml, "application/xml")}
    r = c.post("/api/v1/security/dmarc/ingest", files=files, headers=_OWNER_HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert int(data.get("reports") or 0) >= 1
    assert int(data.get("records") or 0) >= 1

    s = c.get("/api/v1/security/dmarc/summary", params={"days": 30}, headers=_OWNER_HEADERS)
    assert s.status_code == 200
    summary = s.json()
    ips = summary.get("top_ips") or []
    domains = summary.get("top_domains") or []
    assert any(ip[0] in {"203.0.113.5", "198.51.100.9"} for ip in ips)
    assert any(d[0] == "example.com" for d in domains)


def test_dmarc_ingest_zip_and_summary(client):
    c = client
    # Build a zip containing one XML
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("report1.xml", _sample_dmarc_xml())
    buf.seek(0)
    files = {"file": ("reports.zip", buf.read(), "application/zip")}
    r = c.post("/api/v1/security/dmarc/ingest", files=files, headers=_OWNER_HEADERS)
    assert r.status_code == 200
    assert int(r.json().get("reports") or 0) >= 1


def test_dmarc_summary_keeps_recent_and_historical_windows_distinct(client):
    now = int(time.time())
    for stamp, domain in ((now, 'recent.example'), (now - 60 * 86400, 'historical.example')):
        response = client.post('/api/v1/security/dmarc/ingest',
            files={'file': ('window.xml', _sample_dmarc_xml(report_end=stamp, domain=domain), 'application/xml')},
            headers=_OWNER_HEADERS)
        assert response.status_code == 200
        assert response.json() == {'reports': 1, 'records': 2}
    recent = client.get('/api/v1/security/dmarc/summary', params={'days': 30}, headers=_OWNER_HEADERS)
    assert recent.status_code == 200
    assert recent.json()['total_messages'] == 10
    assert recent.json()['failed_messages'] == 3
    assert recent.json()['fail_rate'] == pytest.approx(0.3)
    assert {row[0] for row in recent.json()['top_domains']} == {'recent.example'}
    historical = client.get('/api/v1/security/dmarc/summary', params={'days': 90}, headers=_OWNER_HEADERS)
    assert historical.status_code == 200
    assert historical.json()['total_messages'] == 20
    assert historical.json()['failed_messages'] == 6
    assert {row[0] for row in historical.json()['top_domains']} == {'recent.example', 'historical.example'}
