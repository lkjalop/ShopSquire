"""Tests for TicketingAgent — DB-primary persistence path.

Updated from the original in-memory tests: tickets are now DB-primary.
Tests use an in-memory SQLite engine patched over db_session.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

from src.app.services.ticketing import TicketingAgent, Ticket


# ── Shared SQLite fixture ──────────────────────────────────────────────────

def _make_engine():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        conn.execute(sa.text("""
            CREATE TABLE tickets (
                id TEXT PRIMARY KEY,
                external_id TEXT,
                title TEXT NOT NULL,
                description TEXT,
                severity TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'open',
                approval_required INTEGER DEFAULT 0,
                trace_id TEXT,
                tenant_id TEXT,
                evidence TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(sa.text("""
            CREATE TABLE decision_logs (
                id TEXT PRIMARY KEY,
                agent_name TEXT,
                valid_from TEXT,
                input_data TEXT,
                proposed_action TEXT,
                policy_version TEXT,
                approval_required INTEGER DEFAULT 0,
                execution_status TEXT,
                approved_at TEXT,
                tenant_id TEXT
            )
        """))
        conn.commit()
    return engine


@contextmanager
def _fake_db(engine):
    with engine.connect() as conn:
        yield conn


def _make_agent(engine):
    agent = TicketingAgent()
    return agent, lambda: _fake_db(engine)


# ── Tests ──────────────────────────────────────────────────────────────────

def test_create_ticket_persists_and_approve():
    engine = _make_engine()
    agent, db_ctx = _make_agent(engine)
    with patch("src.app.services.ticketing.db_session", db_ctx):
        with patch("src.app.services.ticketing.load_feature_flags", return_value={}):
            t = agent.create_ticket(title="Test", description="desc", severity="medium", approval_required=True)
    assert isinstance(t, Ticket)
    assert t.status == "pending_approval"

    # get_ticket should find it in DB
    with patch("src.app.services.ticketing.db_session", db_ctx):
        fetched = agent.get_ticket(t.id)
    assert fetched is not None
    assert fetched.id == t.id

    # approve_ticket updates status in DB
    with patch("src.app.services.ticketing.db_session", db_ctx):
        ok = agent.approve_ticket(t.id)
    assert ok is True

    with patch("src.app.services.ticketing.db_session", db_ctx):
        updated = agent.get_ticket(t.id)
    assert updated is not None
    assert updated.status == "approved"


def test_list_tickets_from_db():
    engine = _make_engine()
    agent, db_ctx = _make_agent(engine)
    with patch("src.app.services.ticketing.db_session", db_ctx):
        with patch("src.app.services.ticketing.load_feature_flags", return_value={}):
            t1 = agent.create_ticket(title="T1", description="d1", severity="low")
            t2 = agent.create_ticket(title="T2", description="d2", severity="high", approval_required=True)

    with patch("src.app.services.ticketing.db_session", db_ctx):
        all_ts = agent.list_tickets()
    assert any(x.id == t1.id for x in all_ts)
    assert any(x.id == t2.id for x in all_ts)

    with patch("src.app.services.ticketing.db_session", db_ctx):
        pending = agent.list_tickets(status="pending_approval")
    assert any(x.id == t2.id for x in pending)


def test_close_ticket():
    engine = _make_engine()
    agent, db_ctx = _make_agent(engine)
    with patch("src.app.services.ticketing.db_session", db_ctx):
        with patch("src.app.services.ticketing.load_feature_flags", return_value={}):
            t = agent.create_ticket(title="To close", description="d", severity="low")
    with patch("src.app.services.ticketing.db_session", db_ctx):
        ok = agent.close_ticket(t.id)
    assert ok is True
    with patch("src.app.services.ticketing.db_session", db_ctx):
        closed = agent.get_ticket(t.id)
    assert closed.status == "closed"
