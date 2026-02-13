import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.services.playbook_engine import (
    dry_run_playbook_selection,
    get_playbook_by_id,
    validate_playbook_config,
)


def test_wave1_playbook_exists_and_has_versioned_fields():
    pb = get_playbook_by_id("PB-PAYMENT-FRAUD")
    assert pb is not None
    assert pb.get("domain") == "security"
    assert pb.get("version")
    assert pb.get("trigger_logic") in ("any", "all")
    assert isinstance(pb.get("entry_conditions"), dict)


def test_dry_run_selects_wave1_playbook():
    res = dry_run_playbook_selection(tags=["payment_fraud"], risk_band="high", context={"channel": "payments", "score": 0.9})
    assert res.get("matched") is True
    sel = res.get("selection") or {}
    pb = sel.get("playbook") or {}
    assert pb.get("id") == "PB-PAYMENT-FRAUD"


def test_current_playbook_config_validates():
    from src.app.services.playbook_engine import load_playbook_config

    cfg = load_playbook_config(force_reload=True)
    ok, errs = validate_playbook_config(cfg)
    assert ok is True, f"validation errors: {errs}"
