"""Track 4 — supplier communication: draft-first, gate-enforced, never auto-sends.

The bounded-autonomy contract:
  * a draft is ALWAYS produced (no consequence), profile-backed wording (flavour) when available;
  * the default path (allow_send=False) NEVER touches a mailer;
  * with allow_send=True the SEND requires the execution gate to ALLOW supplier_contact AND the
    recipient domain to be trusted AND a real mailer — the real gate returns HUMAN_REVIEW (SUP-04),
    so the real, un-stubbed path can never auto-send.
"""
from __future__ import annotations

from types import SimpleNamespace

from src.app.ports.supplier_communication import NullMailer
from src.app.services.supplier_communication import (
    SupplierDraft,
    dispatch_supplier_message,
    draft_supplier_message,
)


class _SpyMailer:
    def __init__(self):
        self.calls = []

    def send(self, *, to_email, subject, body, from_email=None):
        self.calls.append({"to": to_email, "subject": subject, "body": body})
        return {"ok": True, "status": "sent", "provider": "spy"}


def _allow(*a, **k):
    return SimpleNamespace(allowed=True, decision=SimpleNamespace(value="allow"), reason="ok")


def _human_review(*a, **k):
    return SimpleNamespace(allowed=False, decision=SimpleNamespace(value="human_review"), reason="held")


# ── drafting ──
def test_draft_uses_profile_template_when_present():
    tpl = {"reorder": {"subject": "RO {item}", "body": "Hi {supplier_name}, reorder {item}. {sender_name}"}}
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com",
                               item="Widget", templates=tpl, sender_name="Bot")
    assert d.subject == "RO Widget" and "Hi Acme, reorder Widget. Bot" in d.body


def test_draft_falls_back_to_neutral_template_and_never_raises_on_missing_fields():
    d = draft_supplier_message(kind="price_query", supplier_name="", supplier_email="x@acme.com")
    assert isinstance(d, SupplierDraft)
    assert d.subject and d.body  # neutral fallback rendered
    assert "{" not in d.subject  # unknown placeholders blanked, not left literal


# ── dispatch: draft-only default never sends ──
def test_default_is_draft_only_and_never_calls_mailer():
    spy = _SpyMailer()
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(draft=d, mailer=spy)  # allow_send defaults False
    assert out["sent"] is False and out["status"] == "draft_only"
    assert spy.calls == []  # the mailer was never touched


# ── dispatch: gate denial holds, never sends ──
def test_allow_send_but_gate_human_review_holds_for_review():
    spy = _SpyMailer()
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(draft=d, allow_send=True, mailer=spy,
                                    decide_fn=_human_review, domain_trusted_fn=lambda e: True)
    assert out["sent"] is False and out["status"] == "held_for_review"
    assert spy.calls == []


def test_real_gate_holds_supplier_contact_even_with_default_allow(monkeypatch):
    # The real execution gate must HOLD supplier_contact (SUP-04) regardless of the default-allow
    # override — so the un-stubbed path can never auto-send.
    monkeypatch.setenv("POLICY_MATRIX_DEFAULT_ALLOW", "1")
    spy = _SpyMailer()
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(draft=d, allow_send=True, mailer=spy, domain_trusted_fn=lambda e: True)
    assert out["sent"] is False and out["status"] == "held_for_review"
    assert out["verdict"]["decision"] == "human_review"
    assert spy.calls == []


# ── dispatch: allowed + untrusted recipient is blocked ──
def test_allowed_but_untrusted_domain_is_blocked():
    spy = _SpyMailer()
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@evil.com", item="W")
    out = dispatch_supplier_message(draft=d, allow_send=True, mailer=spy,
                                    decide_fn=_allow, domain_trusted_fn=lambda e: False)
    assert out["sent"] is False and out["status"] == "blocked_recipient"
    assert spy.calls == []


# ── dispatch: the only send path — allowed + trusted + real mailer ──
def test_allowed_trusted_with_real_mailer_sends_once():
    spy = _SpyMailer()
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    out = dispatch_supplier_message(draft=d, allow_send=True, mailer=spy,
                                    decide_fn=_allow, domain_trusted_fn=lambda e: True)
    assert out["sent"] is True and out["status"] == "sent"
    assert len(spy.calls) == 1 and spy.calls[0]["to"] == "x@acme.com"


def test_null_mailer_is_the_safe_default_and_never_sends():
    d = draft_supplier_message(kind="reorder", supplier_name="Acme", supplier_email="x@acme.com", item="W")
    # allowed + trusted but NO mailer injected -> NullMailer -> not sent
    out = dispatch_supplier_message(draft=d, allow_send=True,
                                    decide_fn=_allow, domain_trusted_fn=lambda e: True)
    assert out["sent"] is False and out["status"] == "send_failed"
    assert out["send_result"]["provider"] == "null"
    assert NullMailer().send(to_email="a@b.com", subject="s", body="b")["ok"] is False
