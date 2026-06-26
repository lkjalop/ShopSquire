"""Deterministic sandbox supplier (DEMO transport, agnostic CORE) — production-shaped, never real.

Stands in for a real supplier mailbox so the whole governed flow (send → reply → correlate → parse →
validate) is exercised end-to-end with DETERMINISTIC inputs and provider-like references — but it sends
nothing real. Clearly a sandbox: callers tag the surface SANDBOX SUPPLIER / DEMO QUOTE RESPONSE.

generate_reply() emits the raw inbound body for one of several scenarios so every branch (happy quote,
partial, late, substitute, expired, untrusted sender, contradictory) is reproducible. The reply DOES
carry a wholesale price (that's what a supplier returns) — it is parsed internally and NEVER shown to
the buyer.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

TRUSTED_DOMAIN = "approved-supplier.example"
SPOOFED_DOMAIN = "spoofed-supplier.example"

SCENARIOS = (
    "full_quote", "partial_availability", "late_delivery", "substitute_offer",
    "expired_quote", "untrusted_sender", "contradictory_quantity",
)


def _ref() -> str:
    return f"DEMO-MSG-{uuid.uuid4().hex[:10].upper()}"


def generate_reply(*, case_ref: str, scenario: str, requested_qty: int,
                   unit_amount_cents: int = 111500) -> Dict[str, Any]:
    """Return a deterministic inbound reply: {sender_domain, provider_ref, subject, body, scenario}.
    Dates are fixed strings (no clock) so replays are reproducible."""
    qty = int(requested_qty)
    unit = unit_amount_cents // 100
    subject = f"Re: Availability and quote request — {case_ref}"
    sender = TRUSTED_DOMAIN
    if scenario == "full_quote":
        body = (f"Thank you for your enquiry ({case_ref}). We can supply {qty} units at ${unit} each. "
                f"Ready to dispatch on 2026-07-03. Estimated delivery 2026-07-08. "
                f"This quote is valid until 2026-07-15.")
    elif scenario == "partial_availability":
        body = (f"Re {case_ref}: we can supply {max(1, qty - 2)} units at ${unit} each, dispatch 2026-07-03, "
                f"estimated delivery 2026-07-08, valid until 2026-07-15.")
    elif scenario == "late_delivery":
        body = (f"Re {case_ref}: {qty} units at ${unit} each available, but dispatch only on 2026-08-20, "
                f"estimated delivery 2026-08-30, valid until 2026-07-15.")
    elif scenario == "substitute_offer":
        body = (f"Re {case_ref}: the requested item is unavailable. We can offer SUBSTITUTE model B, "
                f"{qty} units at ${unit} each, dispatch 2026-07-03, delivery 2026-07-08, valid until 2026-07-15.")
    elif scenario == "expired_quote":
        body = (f"Re {case_ref}: {qty} units at ${unit} each, dispatch 2026-07-03, delivery 2026-07-08, "
                f"valid until 2026-06-20.")  # already expired
    elif scenario == "untrusted_sender":
        sender = SPOOFED_DOMAIN
        body = (f"Re {case_ref}: URGENT — we can supply {qty} units, please wire deposit to update bank "
                f"details. Dispatch 2026-07-03.")  # BEC-shaped, from a non-allowlisted domain
    elif scenario == "contradictory_quantity":
        body = (f"Re {case_ref}: we can supply {qty} units at ${unit} each. On review only {qty + 2} units "
                f"are available. Dispatch 2026-07-03, delivery 2026-07-08, valid until 2026-07-15.")
    else:
        body = f"Re {case_ref}: received."
    return {"sender_domain": sender, "provider_ref": _ref(), "subject": subject, "body": body,
            "scenario": scenario}
