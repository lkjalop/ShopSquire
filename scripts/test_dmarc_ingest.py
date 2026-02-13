"""Minimal local test for DMARC ingest service.

Creates a tiny DMARC aggregate XML string, ingests it, and prints summary.
"""
from src.app.services.dmarc_ingest import ingest_aggregate, get_summary

SAMPLE_XML = b"""
<feedback>
  <report_metadata>
    <org_name>ExampleISP</org_name>
    <email>postmaster@example.com</email>
    <report_id>ABC123</report_id>
    <date_range>
      <begin>1736200000</begin>
      <end>1736286400</end>
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
      <source_ip>192.0.2.10</source_ip>
      <count>5</count>
    </row>
    <policy_evaluated>
      <disposition>none</disposition>
      <dkim>fail</dkim>
      <spf>pass</spf>
    </policy_evaluated>
  </record>
  <record>
    <row>
      <source_ip>198.51.100.20</source_ip>
      <count>3</count>
    </row>
    <policy_evaluated>
      <disposition>none</disposition>
      <dkim>pass</dkim>
      <spf>fail</spf>
    </policy_evaluated>
  </record>
</feedback>
"""


def main():
    reports, records = ingest_aggregate(SAMPLE_XML)
    print({"reports": reports, "records": records})
    print(get_summary(days=30))


if __name__ == "__main__":
    main()
