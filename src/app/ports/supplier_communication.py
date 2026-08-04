"""Port — outbound supplier mailer (Track 4, bounded autonomy).

CORE depends on this Protocol, never on a concrete SMTP/SendGrid client. The default binding is
NullMailer, which NEVER sends — so the safe default for any deployment is "draft only". A real
mailer is injected by the wiring layer ONLY for an approved, gated send. This keeps the "AI cannot
auto-contact a supplier" guarantee structural: with no real mailer bound, there is nothing to send.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class SupplierMailer(Protocol):
    """Minimal outbound mailer. Implementations must be side-effecting ONLY in send()."""

    def send(self, *, to_email: str, subject: str, body: str,
             from_email: Optional[str] = None) -> Dict[str, Any]:
        ...


class NullMailer:
    """The safe default: records intent, sends nothing. Returns a non-ok 'not_sent' result so a
    caller that forgets to inject a real mailer cannot silently believe a message went out."""

    def send(self, *, to_email: str, subject: str, body: str,
             from_email: Optional[str] = None) -> Dict[str, Any]:
        return {
            "ok": False,
            "status": "not_sent",
            "provider": "null",
            "reason": "no mailer configured — supplier message not sent",
            "to_email": to_email,
        }
