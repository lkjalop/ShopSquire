from src.app.services.security_playbooks import select_playbook, select_cv_playbook
from src.app.services import security_playbooks


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


def test_select_playbook_prefers_enabled_higher_priority_match(monkeypatch):
    monkeypatch.setattr(
        security_playbooks,
        "load_playbook_config",
        lambda: {
            "playbooks": [
                {"id": "PB-SEC-001", "enabled": True, "priority": 9, "risk_band_min": "low", "severity": "high"},
                {"id": "PB-SEC-002", "enabled": True, "priority": 5, "risk_band_min": "medium", "severity": "high"},
            ],
            "signal_map": {"prompt_injection": ["PB-SEC-001", "PB-SEC-002"]},
        },
    )
    pb = select_playbook({"prompt_injection": True}, severity="high")
    assert pb is not None
    assert pb.get("id") == "PB-SEC-002"


def test_select_playbook_skips_disabled_candidates(monkeypatch):
    monkeypatch.setattr(
        security_playbooks,
        "load_playbook_config",
        lambda: {
            "playbooks": [
                {"id": "PB-SEC-001", "enabled": False, "priority": 1, "risk_band_min": "low", "severity": "high"},
                {"id": "PB-SEC-002", "enabled": True, "priority": 9, "risk_band_min": "low", "severity": "high"},
            ],
            "signal_map": {"prompt_injection": ["PB-SEC-001", "PB-SEC-002"]},
        },
    )
    pb = select_playbook({"prompt_injection": True}, severity="high")
    assert pb is not None
    assert pb.get("id") == "PB-SEC-002"
