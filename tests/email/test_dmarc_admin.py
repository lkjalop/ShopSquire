import io
import zipfile
import json

from fastapi.testclient import TestClient

from src.app.main import create_app


def _client():
    return TestClient(create_app())


def _sample_dmarc_xml():
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
"""


def test_dmarc_ingest_and_summary_xml():
    c = _client()
    xml = _sample_dmarc_xml()
    files = {"file": ("dmarc.xml", xml, "application/xml")}
    r = c.post("/api/v1/security/dmarc/ingest", files=files)
    assert r.status_code == 200
    data = r.json()
    assert int(data.get("reports") or 0) >= 1
    assert int(data.get("records") or 0) >= 1

    s = c.get("/api/v1/security/dmarc/summary", params={"days": 30})
    assert s.status_code == 200
    summary = s.json()
    ips = summary.get("top_ips") or []
    domains = summary.get("top_domains") or []
    assert any(ip[0] in {"203.0.113.5", "198.51.100.9"} for ip in ips)
    assert any(d[0] == "example.com" for d in domains)


def test_dmarc_ingest_zip_and_summary():
    c = _client()
    # Build a zip containing one XML
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("report1.xml", _sample_dmarc_xml())
    buf.seek(0)
    files = {"file": ("reports.zip", buf.read(), "application/zip")}
    r = c.post("/api/v1/security/dmarc/ingest", files=files)
    assert r.status_code == 200
    assert int(r.json().get("reports") or 0) >= 1
