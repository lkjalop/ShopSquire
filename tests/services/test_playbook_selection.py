from src.app.services.security_playbooks import select_playbook, select_cv_playbook


def test_select_playbook_prompt_injection():
    pb = select_playbook({"prompt_injection": True, "jailbreak": False}, severity="high")
    assert pb is not None
    assert pb.get("id") == "PB-SEC-001"


def test_select_playbook_data_exfiltration():
    pb = select_playbook({"data_exfiltration": True}, severity="critical")
    assert pb is not None
    assert pb.get("id") == "PB-SEC-002"


def test_select_cv_playbook_from_tags():
    pb = select_cv_playbook(["serial_mismatch"], risk_band="medium")
    assert pb is not None
    assert pb.get("playbook", {}).get("id") in ("PB-FRAUD-001", "PB-CV-SERIAL-001")


def test_select_cv_playbook_data_readiness():
    pb = select_cv_playbook(["data_not_ready"], risk_band="low")
    assert pb is not None
    assert pb.get("playbook", {}).get("id") == "PB-DATA-001"
