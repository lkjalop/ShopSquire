"""Tier-2 email: AI-authored-text stylometry (shadow-mode) + outbound content DLP (enforced)."""
from __future__ import annotations

import pytest

from src.app.security.email_ai_authorship import score_ai_authorship
from src.app.services.outbound_email_monitor import scan_outbound_content_dlp


# ── AI authorship ────────────────────────────────────────────────────────────
_AI_TEXT = ("Thank you for your continued partnership. Furthermore, we would like to inform you that "
            "our billing systems have been updated. Additionally, please be advised that all future "
            "remittances should be directed to the account specified below. Consequently, we kindly "
            "request that you update your records accordingly. In conclusion, we appreciate your prompt "
            "attention to this matter and remain committed to serving your organization.")
_HUMAN_TEXT = ("Hey mate, quick one about the order. We've had a shocker this week, the warehouse flooded "
               "and half the stock's soaked. I've salvaged what I can but the blue ones are gone. Can you "
               "let me know if you still want the rest? I'll do you a deal on shipping since it's late. "
               "Also we've switched banks so the new details are on the invoice, same account name though. "
               "Give us a bell if anything looks off. Cheers, Dave.")


def test_ai_text_scores_high_human_scores_low():
    ai = score_ai_authorship(_AI_TEXT)
    hu = score_ai_authorship(_HUMAN_TEXT)
    assert ai["detected"] is True and ai["score"] >= 0.6
    assert hu["detected"] is False and hu["score"] < 0.6, f"human FP: {hu}"


def test_ai_text_too_short_does_not_guess():
    r = score_ai_authorship("Pay the invoice now.")
    assert r["detected"] is False and r["reasons"] == ["insufficient_length"]


def test_ai_signal_is_shadow_by_default(monkeypatch):
    # default (EMAIL_AI_TEXT_ENFORCED unset): computed in meta but NOT a scoring indicator
    monkeypatch.delenv("EMAIL_AI_TEXT_ENFORCED", raising=False)
    from src.app.security.email_security import evaluate_email_security
    r = evaluate_email_security({"from_addr": "billing@vendor.com", "subject": "Account update",
                                 "body": _AI_TEXT, "attachments": []})
    assert "ai_authorship" in r  # computed + logged (lifted to top-level result)
    inds = {str((i or {}).get("type") or "") for i in
            (r.get("indicators") or (r.get("extracted") or {}).get("indicators") or [])}
    assert "ai_generated_text_signal" not in inds  # shadow: not scored


# ── outbound content DLP ─────────────────────────────────────────────────────
def test_dlp_blocks_secret_flags_pii_allows_clean():
    assert scan_outbound_content_dlp("k", "key sk_live_abcdef0123456789ABCDEF")["action"] == "block"
    assert scan_outbound_content_dlp("o", "card 4111 1111 1111 1111")["action"] == "review"
    assert scan_outbound_content_dlp("h", "ships tomorrow")["action"] == "allow"


def test_outbound_send_blocks_secret_before_send():
    from src.app.services.email_providers import SendGridProvider
    p = SendGridProvider()
    r = p.send(to="v@vendor.com", subject="creds",
               body="here is the AWS key AKIAIOSFODNN7EXAMPLE", agent_id="Email_Send_Agent")
    assert r["ok"] is False and r["blocked"] is True and r["error"] == "dlp_content_block"


def test_outbound_send_allows_clean(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "dump").mkdir(exist_ok=True)
    from src.app.services.email_providers import SendGridProvider
    p = SendGridProvider()
    r = p.send(to="v@vendor.com", subject="hi", body="Thanks, shipping tomorrow.",
               agent_id="Email_Send_Agent")
    assert r["ok"] is True and not r.get("blocked")


def test_outbound_pii_not_blocked_by_default_but_flag_hardens(monkeypatch):
    from src.app.services import email_providers as ep
    p = ep.SendGridProvider()
    body = "Ship to Dr. Jane Smith, phone +61 412345678"
    # default: PII review, NOT blocked (send proceeds to dev fallback)
    monkeypatch.delenv("OUTBOUND_DLP_BLOCK_PII", raising=False)
    r = p.send(to="v@vendor.com", subject="order", body=body, agent_id="Email_Send_Agent")
    assert not r.get("blocked")
    # hardened: PII blocks too
    monkeypatch.setenv("OUTBOUND_DLP_BLOCK_PII", "1")
    r2 = p.send(to="v@vendor.com", subject="order", body=body, agent_id="Email_Send_Agent")
    assert r2.get("blocked") is True and r2["error"] == "dlp_content_block"
