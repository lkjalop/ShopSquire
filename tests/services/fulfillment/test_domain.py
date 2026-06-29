"""Step 1 — the bounded-autonomy safety contract, proven as invariants.

If any of these fail, an agent could contact a supplier on a mere query, send without a human, or push
the case into an unsafe state. They are the foundation every downstream layer inherits.
"""
from __future__ import annotations

from src.app.services.fulfillment import domain as d
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


def _agent(): return Actor(A.AGENT, "Procurement_Agent")
def _buyer(): return Actor(A.BUYER, "u1")
def _human(): return Actor(A.HUMAN_OPERATOR, "owner-01")
def _external(): return Actor(A.EXTERNAL, "supplier-sys")
def _system(): return Actor(A.SYSTEM, "batch")


# ── GATE 2: external send is HUMAN-only ──────────────────────────────────────
def test_external_send_is_human_only():
    assert "external_message_sent" in d.HUMAN_ONLY_EVENTS
    ok, _ = d.can_fire(S.APPROVED_TO_SEND, "external_message_sent", _human())
    assert ok is True
    for actor in (_agent(), _buyer(), _system(), _external()):
        ok, reason = d.can_fire(S.APPROVED_TO_SEND, "external_message_sent", actor)
        assert ok is False and reason == "actor_not_permitted", f"{actor.type} could fire the send!"


def test_quote_validation_and_po_are_human_only():
    assert {"supplier_quote_validated", "approval_granted", "purchase_order_approved"} <= d.HUMAN_ONLY_EVENTS
    # an agent cannot self-validate the inbound quote
    ok, reason = d.can_fire(S.QUOTE_RECEIVED, "supplier_quote_validated", _agent())
    assert ok is False and reason == "actor_not_permitted"


# ── AMENDMENT: supersede is pre-send only (never retires a case a supplier was emailed about) ──
def test_case_superseded_is_pre_send_only():
    # the buyer may supersede a case before any supplier contact (GATE 1 / draft / approval states)…
    for src in (S.AWAITING_BUYER_COMMITMENT, S.COMMITTED, S.QUOTE_DRAFTED, S.AWAITING_APPROVAL):
        assert d.next_state(src, "case_superseded", _buyer()) == S.SUPERSEDED, f"{src} should supersede"
    # …but NOT once it is approved-to-send or already sent (that is the operator post-send protocol)
    assert d.next_state(S.APPROVED_TO_SEND, "case_superseded", _buyer()) is None
    assert d.next_state(S.QUOTE_SENT, "case_superseded", _buyer()) is None
    # SUPERSEDED is terminal — nothing fires from it
    ok, reason = d.can_fire(S.SUPERSEDED, "case_superseded", _buyer())
    assert ok is False and reason == "terminal_state"


# ── GATE 1: buyer commitment is unbypassable ─────────────────────────────────
def test_agent_cannot_engage_supplier_without_buyer_commitment():
    # from AVAILABILITY_ASSESSED the ONLY way forward is request_buyer_commitment → AWAITING → buyer_committed
    assert d.next_state(S.AVAILABILITY_ASSESSED, "request_buyer_commitment", _agent()) == S.AWAITING_BUYER_COMMITMENT
    # there is NO agent transition that drafts/engages directly from assessment (no speculation)
    assert d.can_fire(S.AVAILABILITY_ASSESSED, "external_message_drafted", _agent())[0] is False
    # and the commitment itself can only be fired by the BUYER, not the agent
    assert d.can_fire(S.AWAITING_BUYER_COMMITMENT, "buyer_committed", _agent())[0] is False
    assert d.can_fire(S.AWAITING_BUYER_COMMITMENT, "buyer_committed", _buyer())[0] is True
    # drafting becomes possible ONLY post-commitment
    assert d.next_state(S.COMMITTED, "external_message_drafted", _agent()) == S.QUOTE_DRAFTED
    assert d.is_past_commitment_gate(S.AVAILABILITY_ASSESSED) is False
    assert d.is_past_commitment_gate(S.COMMITTED) is True


# ── illegal / disallowed / terminal ──────────────────────────────────────────
def test_illegal_transition_rejected():
    ok, reason = d.can_fire(S.NEW, "external_message_sent", _human())  # can't send from NEW
    assert ok is False and reason == "illegal_transition"


def test_terminal_state_is_frozen():
    ok, reason = d.can_fire(S.COMPLETED, "completed", _system())
    assert ok is False and reason == "terminal_state"
    ok, reason = d.can_fire(S.BUYER_DECLINED, "buyer_committed", _buyer())
    assert ok is False and reason == "terminal_state"


# ── confidence-gated transitions are flagged for the workflow ────────────────
def test_engage_and_options_are_confidence_gated():
    assert d.CONFIDENCE_GATED_EVENTS == frozenset(
        {"external_message_drafted", "fulfillment_options_generated", "approval_granted_autonomous"})
    assert d.requires_confidence_gate(S.COMMITTED, "external_message_drafted") is True
    assert d.requires_confidence_gate(S.QUOTE_VALIDATED, "fulfillment_options_generated") is True
    assert d.requires_confidence_gate(S.AWAITING_APPROVAL, "approval_granted_autonomous") is True  # WS-C
    assert d.requires_confidence_gate(S.QUOTE_DRAFTED, "approval_requested") is False


def test_editing_a_pending_draft_returns_to_drafted():
    # an edit while AWAITING_APPROVAL re-drafts (workflow then voids the prior approval hash)
    assert d.next_state(S.AWAITING_APPROVAL, "external_message_drafted", _human()) == S.QUOTE_DRAFTED
    assert d.next_state(S.AWAITING_APPROVAL, "external_message_drafted", _agent()) == S.QUOTE_DRAFTED


def test_happy_path_walks_end_to_end_with_correct_actors():
    walk = [
        (S.NEW, "availability_assessed", _agent(), S.AVAILABILITY_ASSESSED),
        (S.AVAILABILITY_ASSESSED, "request_buyer_commitment", _agent(), S.AWAITING_BUYER_COMMITMENT),
        (S.AWAITING_BUYER_COMMITMENT, "buyer_committed", _buyer(), S.COMMITTED),
        (S.COMMITTED, "external_message_drafted", _agent(), S.QUOTE_DRAFTED),
        (S.QUOTE_DRAFTED, "approval_requested", _agent(), S.AWAITING_APPROVAL),
        (S.AWAITING_APPROVAL, "approval_granted", _human(), S.APPROVED_TO_SEND),
        (S.APPROVED_TO_SEND, "external_message_sent", _human(), S.QUOTE_SENT),
        (S.QUOTE_SENT, "external_message_received", _external(), S.QUOTE_RECEIVED),
        (S.QUOTE_RECEIVED, "supplier_quote_validated", _human(), S.QUOTE_VALIDATED),
        (S.QUOTE_VALIDATED, "fulfillment_options_generated", _agent(), S.OPTIONS_READY),
        (S.OPTIONS_READY, "buyer_fulfillment_selected", _buyer(), S.SELECTED),
        (S.SELECTED, "purchase_order_proposed", _agent(), S.PROCUREMENT_APPROVAL_REQUIRED),
        (S.PROCUREMENT_APPROVAL_REQUIRED, "purchase_order_approved", _human(), S.PROCUREMENT_IN_PROGRESS),
        (S.PROCUREMENT_IN_PROGRESS, "purchase_order_created", _human(), S.READY_TO_SHIP),
        (S.READY_TO_SHIP, "completed", _system(), S.COMPLETED),
    ]
    state = S.NEW
    for src, event, actor, dst in walk:
        assert state == src, f"walk desync at {event}: {state} != {src}"
        ok, reason = d.can_fire(src, event, actor)
        assert ok, f"{event} should be fireable by {actor.type} from {src}: {reason}"
        state = d.next_state(src, event, actor)
        assert state == dst
    assert state == S.COMPLETED


def test_quarantine_path_on_untrusted_inbound():
    assert d.next_state(S.QUOTE_SENT, "supplier_response_quarantined", _system()) == S.SUPPLIER_RESPONSE_QUARANTINED


# ── MAESTRO: the two agents are registered (fail-open gap closed) ────────────
def test_procurement_agents_registered_with_zero_autonomous_value():
    from src.app.security.maestro_boundaries import AGENT_BOUNDARIES, check_autonomous_value
    assert "Procurement_Agent" in AGENT_BOUNDARIES
    assert "Supplier_Communication_Agent" in AGENT_BOUNDARIES
    assert AGENT_BOUNDARIES["Supplier_Communication_Agent"].max_autonomous_value_usd == 0.0
    # before registration this returned None (fail-open); now a $6,690 autonomous send is a CRITICAL violation
    v = check_autonomous_value("Supplier_Communication_Agent", 6690.0)
    assert v is not None and v.severity == "critical" and v.violation_type == "value_exceeded"


def test_supplier_contact_draft_is_a_gated_action_type():
    from src.app.services.adaptive_action_gate import ALLOWED_ACTION_TYPES, authorize
    assert "supplier_contact_draft" in ALLOWED_ACTION_TYPES
    # unknown procurement action still denied
    assert authorize(None, action_type="auto_send_supplier", confidence=1.0).allowed is False
