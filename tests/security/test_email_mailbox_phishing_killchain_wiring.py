import os

os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

from src.app.security.email_security import evaluate_email_security


def test_mailbox_compromise_phishing_stage_and_bec_kill_chain_wired():
    out = evaluate_email_security(
        {
            "message_id": "<mbx-phish-1@shopsquire.local>",
            "from_addr": "finance@supplier.example",
            "reply_to": "finance@supplier.example",
            "subject": "Urgent payment update",
            "body": "Please login now and confirm wire transfer: https://secure-login.ngrok.app/verify",
            "attachments": [],
            "mailbox_events": [
                {"type": "oauth_consent", "scopes": ["Mail.ReadWrite", "offline_access"]},
                {"type": "delegate_added", "action": "granted", "target_email": "ops@external.example"},
            ],
        },
        tenant_id="t-email-stage",
    )
    ev = out.get("evidence_snapshot") or {}
    assert isinstance(ev.get("mailbox_compromise"), dict)
    assert isinstance(ev.get("phishing_page_stage"), dict)
    assert isinstance(ev.get("bec_kill_chain"), dict)
    assert str((ev.get("bec_kill_chain") or {}).get("stage") or "").strip() != ""
    ind_types = {str((x or {}).get("type") or "") for x in (out.get("indicators") or [])}
    assert "mailbox_oauth_high_privilege_consent" in ind_types
    assert "mailbox_delegate_added" in ind_types

