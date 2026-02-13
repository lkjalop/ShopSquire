import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.services.security_playbooks import select_cv_playbook


def test_select_playbook_for_reply_to_mismatch():
    tags = ["reply_to_mismatch", "brand_impersonation", "email_security"]
    sel = select_cv_playbook(tags, risk_band="medium")
    assert sel and sel.get("playbook") and sel["playbook"]["id"].startswith("PB-EMAIL-002")


def test_select_playbook_for_dmarc_anomaly():
    tags = ["dmarc", "email_security"]
    sel = select_cv_playbook(tags, risk_band="high")
    assert sel and sel.get("playbook") and sel["playbook"]["id"] == "PB-EMAIL-005"
