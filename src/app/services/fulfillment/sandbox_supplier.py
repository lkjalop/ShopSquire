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
from datetime import date, timedelta
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
                   unit_amount_cents: int = 111500,
                   sender_domain: str | None = None, as_of: date | None = None) -> Dict[str, Any]:
    """Return a deterministic inbound reply: {sender_domain, provider_ref, subject, body, scenario}.
    Dates use an explicit simulation clock; the default preserves historical replay."""
    qty = int(requested_qty)
    unit = f"{unit_amount_cents // 100}.{unit_amount_cents % 100:02d}"
    base = as_of or date(2026, 6, 28)
    dispatch, delivery, expiry = (str(base + timedelta(days=d)) for d in (5, 10, 17))
    late_dispatch, late_delivery, expired = (str(base + timedelta(days=d)) for d in (53, 63, -8))
    subject = f"Re: Availability and quote request — {case_ref}"
    # Normal demo replies must come from the supplier selected for this RFQ.
    # A hard-coded sender makes the security boundary correctly quarantine a
    # benign reply whenever another catalogue supplier wins selection.
    sender = str(sender_domain or TRUSTED_DOMAIN).strip().lower()
    if scenario == "full_quote":
        body = (f"Thank you for your enquiry ({case_ref}). We can supply {qty} units at ${unit} each. "
                f"Ready to dispatch on {dispatch}. Estimated delivery {delivery}. "
                f"This quote is valid until {expiry}.")
    elif scenario == "partial_availability":
        body = (f"Re {case_ref}: we can supply {max(1, qty - 2)} units at ${unit} each, dispatch {dispatch}, "
                f"estimated delivery {delivery}, valid until {expiry}.")
    elif scenario == "late_delivery":
        body = (f"Re {case_ref}: {qty} units at ${unit} each available, but dispatch only on {late_dispatch}, "
                f"estimated delivery {late_delivery}, valid until {expiry}.")
    elif scenario == "substitute_offer":
        body = (f"Re {case_ref}: the requested item is unavailable. We can offer SUBSTITUTE model B, "
                f"{qty} units at ${unit} each, dispatch {dispatch}, delivery {delivery}, valid until {expiry}.")
    elif scenario == "expired_quote":
        body = (f"Re {case_ref}: {qty} units at ${unit} each, dispatch {dispatch}, delivery {delivery}, "
                f"valid until {expired}.")  # already expired
    elif scenario == "untrusted_sender":
        sender = SPOOFED_DOMAIN
        body = (f"Re {case_ref}: URGENT — we can supply {qty} units, please wire deposit to update bank "
                f"details. Dispatch {dispatch}.")  # BEC-shaped, from a non-allowlisted domain
    elif scenario == "contradictory_quantity":
        body = (f"Re {case_ref}: we can supply {qty} units at ${unit} each. On review only {qty + 2} units "
                f"are available. Dispatch {dispatch}, delivery {delivery}, valid until {expiry}.")
    else:
        body = f"Re {case_ref}: received."
    return {"sender_domain": sender, "provider_ref": _ref(), "subject": subject, "body": body,
            "scenario": scenario}
