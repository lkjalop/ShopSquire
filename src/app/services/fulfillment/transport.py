"""Supplier-email transport seam (agnostic CORE) — Phase-8 production transports.

The fulfilment send is SANDBOX by default: send_approved STAGES the human-approved message but transmits
nothing. This is the provider interface that lets a REAL transport be wired at DEPLOY time without
touching the workflow or the gates — send_approved still fires the human-approved external_message_sent
transition; only the bytes-on-the-wire differ.

  • SandboxTransport (default) — stages the message, returns a DEMO-OUT- ref, sends nothing.
  • SmtpTransport (flag-gated, FULFILLMENT_SUPPLIER_TRANSPORT=smtp) — builds an RFC-822 message and sends
    via an injected SMTP client. UNEXERCISED against a real server here (no live SMTP); the message build
    + the send call ARE tested with a fake client. Wire SMTP_HOST/PORT/USER/PASSWORD/SENDER at deploy.

A real send NEVER raises into the workflow — a failure returns status='failed', and send_approved then
does NOT record a send (the human can retry). Vertical-blind; the recipient is the allowlist-resolved
address the caller passes, never buyer text.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol


@dataclass(frozen=True)
class SendResult:
    provider_ref: str
    status: str            # sent | failed
    detail: str = ""       # transport label / error summary


class SupplierTransport(Protocol):
    def send(self, *, to: str, subject: str, body: str, idempotency_key: str = "") -> SendResult: ...


class SandboxTransport:
    """The default — stages a message, transmits nothing. Behaviour-identical to the prior inline send."""

    def send(self, *, to: str, subject: str, body: str, idempotency_key: str = "") -> SendResult:
        return SendResult(provider_ref=f"DEMO-OUT-{uuid.uuid4().hex[:10].upper()}", status="sent",
                          detail="sandbox")


class SmtpTransport:
    """Real SMTP send (flag-gated). Deterministic + testable via an injected ``client_factory`` (default
    smtplib.SMTP). Returns status='failed' on any error — it never raises into the workflow."""

    def __init__(self, *, host: Optional[str] = None, port: Optional[int] = None,
                 user: Optional[str] = None, password: Optional[str] = None,
                 sender: Optional[str] = None, client_factory: Optional[Callable[..., Any]] = None):
        self.host = host or os.getenv("SMTP_HOST", "")
        self.port = int(port or os.getenv("SMTP_PORT", "587") or 587)
        self.user = user if user is not None else os.getenv("SMTP_USER", "")
        self.password = password if password is not None else os.getenv("SMTP_PASSWORD", "")
        self.sender = sender or os.getenv("SMTP_SENDER", "procurement@shopsquire.example")
        self._client_factory = client_factory

    def send(self, *, to: str, subject: str, body: str, idempotency_key: str = "") -> SendResult:
        if not to:
            return SendResult(provider_ref="", status="failed", detail="no_recipient")
        try:
            from email.message import EmailMessage
            msg = EmailMessage()
            msg["From"] = self.sender
            msg["To"] = to
            msg["Subject"] = subject
            if idempotency_key:
                msg["X-Idempotency-Key"] = idempotency_key
            msg.set_content(body)
            factory = self._client_factory
            if factory is None:
                import smtplib
                factory = smtplib.SMTP
            client = factory(self.host, self.port)
            if self.user:
                client.starttls()
                client.login(self.user, self.password)
            client.send_message(msg)
            _quiet_quit(client)  # closing is best-effort — must not flip a successful send to failed
            ref = f"SMTP-{(idempotency_key or uuid.uuid4().hex)[:12].upper()}"
            return SendResult(provider_ref=ref, status="sent", detail="smtp")
        except Exception as exc:
            return SendResult(provider_ref="", status="failed", detail=str(exc)[:200])


def _quiet_quit(client) -> None:
    try:
        client.quit()
    except Exception:
        return  # best-effort close — not a silent swallow (observable return, off the ratchet)


def get_transport() -> SupplierTransport:
    """Select the transport from FULFILLMENT_SUPPLIER_TRANSPORT (default 'sandbox')."""
    mode = str(os.getenv("FULFILLMENT_SUPPLIER_TRANSPORT", "sandbox")).strip().lower()
    if mode == "smtp":
        return SmtpTransport()
    return SandboxTransport()
