"""Fulfilment bounded-autonomy domain model (agnostic CORE) — the SAFETY CONTRACT as code.

This is the first artifact of the procurement workflow, and it is deliberately PURE (no I/O, no
persistence, no network): it encodes WHO may do WHAT and WHEN, so every downstream layer (durable
case, draft, send, options, UI) inherits the boundaries instead of bolting them on.

Two gates are first-class here, not afterthoughts:

  GATE 1 · BUYER COMMITMENT — a buyer QUERY is a prospect, not a purchase. There is NO path from
    AVAILABILITY_ASSESSED toward engaging an external party except through AWAITING_BUYER_COMMITMENT via
    a BUYER ``buyer_committed`` event. An agent therefore CANNOT contact a supplier on a mere query —
    the anti-speculation / anti-recon / anti-abuse boundary.

  GATE 2 · HUMAN EXTERNAL-SEND — the ``external_message_sent`` event is HUMAN_OPERATOR-only. No agent,
    system, or buyer can fire it. Likewise quote validation and PO approval/creation are human-only.

Confidence-gated transitions (engaging an external party, generating options) are flagged so the
workflow layer authorizes them through the adaptive-action gate before firing.

VERTICAL-BLIND: states/events/actors are opaque commerce concepts — no product vocabulary, no channel
(email/SMS) detail. Those live in the ecommerce adapter + StoreProfile, never here.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, FrozenSet, List, Optional, Tuple


class ActorType(str, Enum):
    """Who is firing a transition. The actor guard is the core safety invariant."""
    AGENT = "agent"                 # autonomous AI — may prepare/draft, NEVER sends or commits value
    BUYER = "buyer"                 # the prospect/customer — commits, selects, declines
    HUMAN_OPERATOR = "human_operator"  # staff — approves sends, validates quotes, approves POs
    EXTERNAL = "external"           # an inbound external-party system (a supplier reply)
    SYSTEM = "system"               # automated batch/timeout/quarantine


@dataclass(frozen=True)
class Actor:
    type: ActorType
    id: str = ""


class FulfillmentState(str, Enum):
    NEW = "NEW"
    AVAILABILITY_ASSESSED = "AVAILABILITY_ASSESSED"
    AWAITING_BUYER_COMMITMENT = "AWAITING_BUYER_COMMITMENT"   # GATE 1
    COMMITTED = "COMMITTED"
    QUOTE_DRAFTED = "QUOTE_DRAFTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AWAITING_SUPPLIER_INFO = "AWAITING_SUPPLIER_INFO"   # RFI: human asked the supplier a clarification
    APPROVED_TO_SEND = "APPROVED_TO_SEND"
    QUOTE_SENT = "QUOTE_SENT"
    QUOTE_RECEIVED = "QUOTE_RECEIVED"
    QUOTE_VALIDATED = "QUOTE_VALIDATED"
    OPTIONS_READY = "OPTIONS_READY"
    SELECTED = "SELECTED"
    PROCUREMENT_APPROVAL_REQUIRED = "PROCUREMENT_APPROVAL_REQUIRED"
    PROCUREMENT_IN_PROGRESS = "PROCUREMENT_IN_PROGRESS"
    PARTIALLY_READY = "PARTIALLY_READY"
    READY_TO_SHIP = "READY_TO_SHIP"
    COMPLETED = "COMPLETED"
    # failure / terminal-bad
    NO_APPROVED_SUPPLIER = "NO_APPROVED_SUPPLIER"
    RECIPIENT_BLOCKED = "RECIPIENT_BLOCKED"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    QUOTE_PARSE_FAILED = "QUOTE_PARSE_FAILED"
    SUPPLIER_RESPONSE_QUARANTINED = "SUPPLIER_RESPONSE_QUARANTINED"
    DELIVERY_CONSTRAINT_UNMET = "DELIVERY_CONSTRAINT_UNMET"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    BUYER_DECLINED = "BUYER_DECLINED"


FAILURE_STATES: FrozenSet[FulfillmentState] = frozenset({
    FulfillmentState.NO_APPROVED_SUPPLIER, FulfillmentState.RECIPIENT_BLOCKED,
    FulfillmentState.QUOTE_EXPIRED, FulfillmentState.QUOTE_PARSE_FAILED,
    FulfillmentState.SUPPLIER_RESPONSE_QUARANTINED, FulfillmentState.DELIVERY_CONSTRAINT_UNMET,
    FulfillmentState.POLICY_BLOCKED, FulfillmentState.BUYER_DECLINED,
})
TERMINAL_STATES: FrozenSet[FulfillmentState] = FAILURE_STATES | {FulfillmentState.COMPLETED}

# The CONSEQUENTIAL external action — sending to an external party. HUMAN-only by construction.
EXTERNAL_SEND_EVENTS: FrozenSet[str] = frozenset({"external_message_sent"})


@dataclass(frozen=True)
class Transition:
    event: str
    src: FulfillmentState
    dst: FulfillmentState
    allowed_actors: FrozenSet[ActorType]
    requires_confidence_gate: bool = False  # workflow must authorize() before firing
    requires_evidence: bool = False         # the transition must carry input/output evidence ids
    note: str = ""


_S = FulfillmentState
_A = ActorType

# The full transition table. Each row is the ONLY way to fire that (state, event); the actor guard is
# the enforcement. Read top-to-bottom as the happy path with failure exits interleaved.
TRANSITIONS: Tuple[Transition, ...] = (
    Transition("availability_assessed", _S.NEW, _S.AVAILABILITY_ASSESSED, frozenset({_A.AGENT}),
               requires_evidence=True, note="agent reads inventory truth + computes shortfall"),

    # ── GATE 1: buyer commitment — the ONLY way forward from assessment ──────────
    Transition("request_buyer_commitment", _S.AVAILABILITY_ASSESSED, _S.AWAITING_BUYER_COMMITMENT,
               frozenset({_A.AGENT, _A.SYSTEM}), note="ask the buyer to commit before any supplier contact"),
    Transition("buyer_committed", _S.AWAITING_BUYER_COMMITMENT, _S.COMMITTED, frozenset({_A.BUYER}),
               note="GATE 1: a real commitment (order/reserve/deposit) — not a query"),
    Transition("buyer_declined", _S.AWAITING_BUYER_COMMITMENT, _S.BUYER_DECLINED, frozenset({_A.BUYER})),

    # ── agent prepares + drafts (internal only) — confidence-gated, post-commitment ──
    Transition("supplier_candidates_ranked", _S.COMMITTED, _S.COMMITTED, frozenset({_A.AGENT}),
               requires_evidence=True, note="internal supplier ranking — no external contact"),
    Transition("external_message_drafted", _S.COMMITTED, _S.QUOTE_DRAFTED, frozenset({_A.AGENT}),
               requires_confidence_gate=True, requires_evidence=True,
               note="DRAFT only (no send); recipient resolved from allowlist, never buyer text"),
    Transition("no_approved_supplier", _S.COMMITTED, _S.NO_APPROVED_SUPPLIER, frozenset({_A.AGENT, _A.SYSTEM})),

    Transition("approval_requested", _S.QUOTE_DRAFTED, _S.AWAITING_APPROVAL, frozenset({_A.AGENT}),
               requires_evidence=True, note="queue the exact message + content hash for human review"),

    # ── editing a pending draft voids the prior approval (back to DRAFTED) ──
    Transition("external_message_drafted", _S.AWAITING_APPROVAL, _S.QUOTE_DRAFTED, frozenset({_A.AGENT, _A.HUMAN_OPERATOR}),
               requires_evidence=True, note="edit → new version + new hash → prior approval void"),

    # ── RFI: the human asks the supplier a scoped clarification BEFORE approving the RFQ. HUMAN-fired
    #    (an external contact), claim-safe + content-hashed like the RFQ. Returns to the approval gate. ──
    Transition("supplier_info_requested", _S.AWAITING_APPROVAL, _S.AWAITING_SUPPLIER_INFO,
               frozenset({_A.HUMAN_OPERATOR}), requires_evidence=True,
               note="HUMAN sends a scoped RFI to the resolved supplier (consumes a needs_info send-gate)"),
    Transition("supplier_info_received", _S.AWAITING_SUPPLIER_INFO, _S.AWAITING_APPROVAL,
               frozenset({_A.EXTERNAL, _A.SYSTEM, _A.HUMAN_OPERATOR}), requires_evidence=True,
               note="supplier clarification recorded → back to the approval gate with the answer on file"),

    # ── GATE 2a: human approval, then human-fired send ──
    Transition("approval_granted", _S.AWAITING_APPROVAL, _S.APPROVED_TO_SEND, frozenset({_A.HUMAN_OPERATOR}),
               requires_evidence=True),
    Transition("approval_rejected", _S.AWAITING_APPROVAL, _S.QUOTE_DRAFTED, frozenset({_A.HUMAN_OPERATOR})),
    Transition("policy_blocked", _S.AWAITING_APPROVAL, _S.POLICY_BLOCKED, frozenset({_A.SYSTEM})),
    Transition("external_message_sent", _S.APPROVED_TO_SEND, _S.QUOTE_SENT, frozenset({_A.HUMAN_OPERATOR}),
               requires_evidence=True, note="GATE 2: HUMAN-only external send — no agent may fire this"),
    Transition("recipient_blocked", _S.APPROVED_TO_SEND, _S.RECIPIENT_BLOCKED, frozenset({_A.SYSTEM})),

    # ── inbound external response (a supplier system / poller) ──
    Transition("external_message_received", _S.QUOTE_SENT, _S.QUOTE_RECEIVED, frozenset({_A.EXTERNAL, _A.SYSTEM}),
               requires_evidence=True, note="correlated + domain-verified inbound reply"),
    Transition("supplier_response_quarantined", _S.QUOTE_SENT, _S.SUPPLIER_RESPONSE_QUARANTINED,
               frozenset({_A.SYSTEM, _A.EXTERNAL}), note="identity mismatch / unsafe → quarantine"),
    Transition("supplier_response_parsed", _S.QUOTE_RECEIVED, _S.QUOTE_RECEIVED, frozenset({_A.AGENT}),
               requires_evidence=True, note="strict-schema parse with evidence spans — never auto-PO"),

    # ── GATE 2b: human validates the inbound quote ──
    Transition("supplier_quote_validated", _S.QUOTE_RECEIVED, _S.QUOTE_VALIDATED, frozenset({_A.HUMAN_OPERATOR}),
               requires_evidence=True, note="HUMAN validates real/in-scope/not-expired before options"),
    Transition("quote_parse_failed", _S.QUOTE_RECEIVED, _S.QUOTE_PARSE_FAILED, frozenset({_A.AGENT, _A.SYSTEM})),
    Transition("quote_expired", _S.QUOTE_RECEIVED, _S.QUOTE_EXPIRED, frozenset({_A.SYSTEM})),

    Transition("fulfillment_options_generated", _S.QUOTE_VALIDATED, _S.OPTIONS_READY, frozenset({_A.AGENT}),
               requires_confidence_gate=True, requires_evidence=True,
               note="together/split/substitute with explicit tradeoffs"),

    # ── buyer chooses ──
    Transition("buyer_fulfillment_selected", _S.OPTIONS_READY, _S.SELECTED, frozenset({_A.BUYER}),
               requires_evidence=True),
    Transition("buyer_declined", _S.OPTIONS_READY, _S.BUYER_DECLINED, frozenset({_A.BUYER})),

    # ── PO: human-approved, never agent ──
    Transition("purchase_order_proposed", _S.SELECTED, _S.PROCUREMENT_APPROVAL_REQUIRED, frozenset({_A.AGENT}),
               requires_evidence=True),
    Transition("purchase_order_approved", _S.PROCUREMENT_APPROVAL_REQUIRED, _S.PROCUREMENT_IN_PROGRESS,
               frozenset({_A.HUMAN_OPERATOR}), requires_evidence=True, note="HUMAN approves the PO"),
    Transition("approval_rejected", _S.PROCUREMENT_APPROVAL_REQUIRED, _S.SELECTED, frozenset({_A.HUMAN_OPERATOR})),
    Transition("purchase_order_created", _S.PROCUREMENT_IN_PROGRESS, _S.READY_TO_SHIP,
               frozenset({_A.HUMAN_OPERATOR, _A.SYSTEM}), requires_evidence=True),
    Transition("shipment_plan_created", _S.PROCUREMENT_IN_PROGRESS, _S.PARTIALLY_READY, frozenset({_A.SYSTEM})),
    Transition("completed", _S.READY_TO_SHIP, _S.COMPLETED, frozenset({_A.SYSTEM, _A.HUMAN_OPERATOR})),
    Transition("completed", _S.PARTIALLY_READY, _S.COMPLETED, frozenset({_A.SYSTEM, _A.HUMAN_OPERATOR})),
)

# Index: (state, event) → list of matching transitions (usually one).
_INDEX: Dict[Tuple[FulfillmentState, str], List[Transition]] = {}
for _t in TRANSITIONS:
    _INDEX.setdefault((_t.src, _t.event), []).append(_t)

# Events whose EVERY transition is HUMAN_OPERATOR-only (derived, not hand-listed → always correct).
_by_event: Dict[str, List[Transition]] = {}
for _t in TRANSITIONS:
    _by_event.setdefault(_t.event, []).append(_t)
HUMAN_ONLY_EVENTS: FrozenSet[str] = frozenset(
    e for e, ts in _by_event.items() if all(ts_.allowed_actors == frozenset({ActorType.HUMAN_OPERATOR}) for ts_ in ts)
)
CONFIDENCE_GATED_EVENTS: FrozenSet[str] = frozenset(t.event for t in TRANSITIONS if t.requires_confidence_gate)


def find_transition(state: FulfillmentState, event: str, actor_type: ActorType) -> Optional[Transition]:
    """The transition for (state, event) that this actor_type may fire, or None."""
    for t in _INDEX.get((state, event), ()):  # type: ignore[arg-type]
        if actor_type in t.allowed_actors:
            return t
    return None


def can_fire(state: FulfillmentState, event: str, actor: Actor) -> Tuple[bool, str]:
    """Whether ``actor`` may fire ``event`` from ``state``. Returns (ok, reason). The single chokepoint
    every transition passes — an illegal (state,event) or a disallowed actor is REJECTED, so a button
    or an agent can never push the case into an unsafe state."""
    if state in TERMINAL_STATES:
        return False, "terminal_state"
    matches = _INDEX.get((state, event), [])
    if not matches:
        return False, "illegal_transition"
    if actor.type not in {a for t in matches for a in t.allowed_actors}:
        return False, "actor_not_permitted"
    return True, "ok"


def next_state(state: FulfillmentState, event: str, actor: Actor) -> Optional[FulfillmentState]:
    """The destination if this actor may fire (state, event), else None."""
    t = find_transition(state, event, actor.type)
    return t.dst if t else None


def requires_confidence_gate(state: FulfillmentState, event: str) -> bool:
    return any(t.requires_confidence_gate for t in _INDEX.get((state, event), ()))  # type: ignore[arg-type]


def is_past_commitment_gate(state: FulfillmentState) -> bool:
    """True once the buyer has committed — i.e. supplier engagement is permitted. Everything from
    COMMITTED onward (excluding the pre-commitment + failure states)."""
    pre = {FulfillmentState.NEW, FulfillmentState.AVAILABILITY_ASSESSED,
           FulfillmentState.AWAITING_BUYER_COMMITMENT}
    return state not in pre and state not in FAILURE_STATES
