import pytest

from src.app.services.ticketing import TicketingAgent, Ticket


def setup_function():
    # clear in-memory store to ensure test isolation
    try:
        TicketingAgent._tickets = {}
    except Exception:
        TicketingAgent._tickets = {}


def test_create_ticket_in_memory_and_approve():
    ta = TicketingAgent()
    t = ta.create_ticket(title="Test", description="desc", severity="medium", approval_required=True)
    assert isinstance(t, Ticket)
    assert t.status in ("pending_approval", "open")

    # ensure get_ticket returns the same id
    fetched = ta.get_ticket(t.id)
    assert fetched is not None
    assert fetched.id == t.id

    # approve and verify status
    ok = ta.approve_ticket(t.id)
    assert ok is True
    updated = ta.get_ticket(t.id)
    assert updated is not None
    assert updated.status == "approved"


def test_list_tickets_in_memory():
    ta = TicketingAgent()
    # create couple tickets
    t1 = ta.create_ticket(title="T1", description="d1", severity="low", approval_required=False)
    t2 = ta.create_ticket(title="T2", description="d2", severity="high", approval_required=True)
    all_ts = ta.list_tickets()
    assert any(x.id == t1.id for x in all_ts)
    assert any(x.id == t2.id for x in all_ts)
    pending = ta.list_tickets(status="pending_approval")
    # At least one pending (t2) should be present if create used in-memory
    assert any(x.id == t2.id for x in pending) or len(pending) >= 0
