"""Supplier communication-channel router (agnostic CORE).

Real B2B procurement does NOT "just send an email". Suppliers differ by how they accept an order/RFQ, and
the channel decides WHO acts — an agent, a human, or a system-to-system integration:

  - email  → an RFQ/PO email (the SMB default). An agent may DRAFT it; a HUMAN sends it (GATE 2).
  - phone  → a HUMAN must call. An automated / LLM voice call reads as a scam and erodes the relationship,
             so the platform NEVER voice-calls — it creates a human call task for the operator.
  - portal → a supplier web portal; a human logs in and submits (the supplier accepts no inbound email).
  - edi    → EDI (X12 850 PO / EDIFACT) over AS2 / VAN / SFTP — routed to the EDI connector, not email.
  - cxml   → an Ariba / Coupa punchout-network PO (cXML) — routed to the network connector.
  - api    → the supplier's REST API — the PO is posted programmatically.

Vertical-blind: the channel is an opaque enum; this maps it to {agent_may_draft, requires_human,
integration_kind} + a plain-English rationale, and records it on the procurement journey so the operator
sees exactly how each supplier will be reached. Enforcement (blocking an email to a phone supplier, routing
to the EDI/cXML/API connector) is layered on top once those connectors exist; this is the decision + record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import text

CHANNEL_EMAIL = "email"
CHANNEL_PHONE = "phone"
CHANNEL_PORTAL = "portal"
CHANNEL_EDI = "edi"
CHANNEL_CXML = "cxml"
CHANNEL_API = "api"

_INTEGRATION_CHANNELS = {CHANNEL_EDI, CHANNEL_CXML, CHANNEL_API}
_INTEGRATION_LABEL = {CHANNEL_EDI: "EDI (X12 850 PO)", CHANNEL_CXML: "cXML (Ariba/Coupa network)",
                      CHANNEL_API: "supplier REST API"}


@dataclass(frozen=True)
class ChannelPlan:
    channel: str
    agent_may_draft: bool            # an agent may DRAFT the outreach (email); a human still sends it (GATE 2)
    requires_human: bool             # a HUMAN must perform the outreach (phone/portal) — no automation at all
    integration_kind: Optional[str]  # 'edi' | 'cxml' | 'api' for a system-to-system handoff, else None
    rationale: str

    def as_dict(self) -> Dict[str, Any]:
        return {"channel": self.channel, "agent_may_draft": self.agent_may_draft,
                "requires_human": self.requires_human, "integration_kind": self.integration_kind,
                "rationale": self.rationale}


def resolve_channel(preferred_channel: Optional[str], *, tags: Optional[List[str]] = None) -> ChannelPlan:
    """Map a supplier's preferred channel to who-acts + why. Unknown/empty → email (the safe default)."""
    ch = str(preferred_channel or CHANNEL_EMAIL).strip().lower()
    if ch == CHANNEL_PHONE:
        return ChannelPlan(CHANNEL_PHONE, agent_may_draft=False, requires_human=True, integration_kind=None,
                           rationale=("Phone-preference supplier — a HUMAN must call. An automated/LLM voice "
                                      "call reads as a scam and erodes the relationship, so a call task is "
                                      "created for the operator; the platform never voice-calls a supplier."))
    if ch == CHANNEL_PORTAL:
        return ChannelPlan(CHANNEL_PORTAL, agent_may_draft=False, requires_human=True, integration_kind=None,
                           rationale=("Supplier portal — a human logs in and submits the RFQ; the supplier "
                                      "accepts no inbound email, so no email is drafted."))
    if ch in _INTEGRATION_CHANNELS:
        return ChannelPlan(ch, agent_may_draft=False, requires_human=False, integration_kind=ch,
                           rationale=(f"System-to-system supplier — the PO is routed to the "
                                      f"{_INTEGRATION_LABEL[ch]} connector, not email."))
    return ChannelPlan(CHANNEL_EMAIL, agent_may_draft=True, requires_human=False, integration_kind=None,
                       rationale=("Email supplier — an RFQ/PO is drafted for human approval, then a human "
                                  "sends it (GATE 2). The agent drafts; it never sends."))


def channel_plan_for_supplier(db, supplier_id: Optional[str]) -> ChannelPlan:
    """Resolve the channel plan for a supplier id by reading suppliers.preferred_channel. Best-effort: an
    unreadable/absent column defaults to email so the draft path is never blocked by a missing channel."""
    pref: Optional[str] = None
    if db is not None and supplier_id:
        try:
            row = db.execute(text("SELECT preferred_channel FROM suppliers WHERE id = :i"),
                             {"i": str(supplier_id)}).fetchone()
            pref = row[0] if row else None
        except Exception:
            pref = None
    return resolve_channel(pref)
