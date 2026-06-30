"""Procurement fraud signals — amendment-churn cap + cancellation-abuse pattern + the agent-cannot-execute
governance invariant."""
from __future__ import annotations

from src.app.services.fulfillment import procurement_fraud_signals as fs
from src.app.services.fulfillment import domain as d
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S


def AG(): return Actor(A.AGENT, "agent")
def HU(): return Actor(A.HUMAN_OPERATOR, "op")


def test_amendment_cap_brakes_churn():
    assert fs.assess_amendments(amendment_count=3, cap=10)["over_cap"] is False
    hit = fs.assess_amendments(amendment_count=10, cap=10)
    assert hit["over_cap"] is True and hit["amendment_count"] == 10
    assert fs.assess_amendments(amendment_count=99, cap=10)["over_cap"] is True


def test_cancellation_pattern_flags_abuse():
    ok = fs.assess_cancellation_pattern(post_commit_cancellations=1, total_orders=10, cap=3)
    assert ok["flagged"] is False and ok["cancellation_rate"] == 0.1
    bad = fs.assess_cancellation_pattern(post_commit_cancellations=4, total_orders=6, cap=3)
    assert bad["flagged"] is True and bad["post_commit_cancellations"] == 4


def test_bad_input_is_safe():
    a = fs.assess_amendments(amendment_count=None, cap=10)
    assert a["amendment_count"] == 0 and a["over_cap"] is False
    c = fs.assess_cancellation_pattern(post_commit_cancellations="x", total_orders=0, cap=3)
    assert c["post_commit_cancellations"] == 0 and c["cancellation_rate"] == 0.0


# ── governance invariant: an AGENT can never fire a human-only money/send/cancel event ──
def test_agent_cannot_execute_any_human_only_consequential_event():
    human_only = {
        "external_message_sent": S.APPROVED_TO_SEND,        # GATE 2: the supplier send
        "supplier_quote_validated": S.QUOTE_RECEIVED,        # validating a quote
        "purchase_order_approved": S.PROCUREMENT_APPROVAL_REQUIRED,  # approving the PO (money)
        "order_cancelled": S.READY_TO_SHIP,                  # GATE 3: cancelling a committed order (money)
    }
    for event, state in human_only.items():
        assert d.can_fire(state, event, AG())[0] is False, f"agent must NOT fire {event}"
        assert d.can_fire(state, event, HU())[0] is True, f"human must be able to fire {event}"
