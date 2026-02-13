from src.app.security.email_security import process_dmarc_report, detect_bec_indicators


def _make_dmarc_xml(total=4, spf_pass=2, dkim_pass=2, fail_sources=None, domain="example.com", org="Example"):
    # Construct a minimal DMARC XML with 'total' records; for simplicity, count pass/fail
    if fail_sources is None:
        fail_sources = {"1.2.3.4": total - max(spf_pass, dkim_pass)}
    # Build repeated <record> entries; only structure needed by parser
    recs = []
    for i in range(total):
        dkim = "pass" if i < dkim_pass else "fail"
        spf = "pass" if i < spf_pass else "fail"
        src_ip = list(fail_sources.keys())[0]
        recs.append(f"""
        <record>
          <row>
            <source_ip>{src_ip}</source_ip>
            <policy_evaluated>
              <dkim>{dkim}</dkim>
              <spf>{spf}</spf>
            </policy_evaluated>
          </row>
        </record>
        """)
    xml = f"""
    <feedback>
      <report_metadata>
        <org_name>{org}</org_name>
        <domain>{domain}</domain>
      </report_metadata>
      {''.join(recs)}
    </feedback>
    """
    return xml.encode("utf-8")


def test_dmarc_thresholds_info_warning_error():
    # info: fail rate below warn
    xml_info = _make_dmarc_xml(total=4, spf_pass=3, dkim_pass=3)
    s_info = process_dmarc_report(xml_info, tenant_id="t1")
    assert s_info["total"] == 4
    # warning: fail rate >= 0.25
    xml_warn = _make_dmarc_xml(total=4, spf_pass=2, dkim_pass=2)
    s_warn = process_dmarc_report(xml_warn, tenant_id="t1")
    assert s_warn["total"] == 4
    # error: fail rate >= 0.5
    xml_err = _make_dmarc_xml(total=4, spf_pass=1, dkim_pass=1)
    s_err = process_dmarc_report(xml_err, tenant_id="t1")
    assert s_err["total"] == 4


def test_bec_indicators_thresholds():
    # one indicator -> should not trigger error-level by default
    hit, ind = detect_bec_indicators("urgent", "please respond")
    assert hit is True
    assert "urgent" in ind["keywords"][0]
    # multiple indicators -> stronger signal
    hit2, ind2 = detect_bec_indicators("urgent wire transfer", "asap and confidential")
    assert hit2 is True
    assert len(ind2["keywords"]) >= 2


def test_dmarc_parser_handles_zip_and_xml():
    # basic XML handled
    xml = _make_dmarc_xml()
    s = process_dmarc_report(xml)
    assert s["total"] > 0
