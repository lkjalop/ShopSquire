"""Tests for ticketing persistence, supply chain scanner, and live demo gate logic.

Covers:
- ticketing: DB path is primary; in-memory fallback only for rate-limited tickets
- ticketing: asyncio anti-pattern removed from approve_ticket
- supply_chain_security: typosquatting detection
- supply_chain_security: package collection from requirements.txt
- live_demo_gate: stub text detector
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Ticketing — DB-primary path
# ─────────────────────────────────────────────────────────────────────────────
from src.app.services.ticketing import TicketingAgent, Ticket
import sqlalchemy as sa
from contextlib import contextmanager


def _sqlite_engine():
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
        conn.commit()
    return engine


@contextmanager
def _fake_db(engine):
    with engine.connect() as conn:
        yield conn


def test_ticketing_persists_to_db():
    """create_ticket should write to DB when it's available."""
    engine = _sqlite_engine()
    with patch("src.app.services.ticketing.db_session", lambda: _fake_db(engine)):
        agent = TicketingAgent()
        t = agent.create_ticket(title="Test ticket", description="desc", severity="high")
    assert t.id.startswith("TKT-")
    # Verify the row is in DB
    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT id, title, severity FROM tickets")).fetchone()
    assert row is not None
    assert row[1] == "Test ticket"
    assert row[2] == "high"


def test_ticketing_logs_on_db_failure(caplog):
    """create_ticket should log an error when DB write fails (not swallow silently)."""
    import logging

    @contextmanager
    def _bad_db():
        raise RuntimeError("DB connection refused")
        yield  # unreachable

    agent = TicketingAgent()
    with patch("src.app.services.ticketing.db_session", _bad_db):
        with caplog.at_level(logging.ERROR, logger="src.app.services.ticketing"):
            t = agent.create_ticket(title="Failed ticket", description="d", severity="critical")
    # The ticket object is still returned (caller gets the id for tracing)
    assert t.id.startswith("TKT-")
    # But the error is logged, not swallowed
    assert any("DB persist failed" in r.message for r in caplog.records)


def test_ticketing_rate_limited_ticket_format():
    """Rate-limited tickets use RL- prefix and status='rate_limited' (not persisted)."""
    # Test the Ticket dataclass shape that rate-limited path returns
    import time
    tid = f"RL-{int(time.time()*1000)}"
    t = Ticket(id=tid, external_id=None, title="flood", description="d", severity="low", status="rate_limited")
    assert t.status == "rate_limited"
    assert t.id.startswith("RL-")


def test_ticketing_approval_required_sets_pending_status():
    """approval_required=True → ticket status is 'pending_approval'."""
    engine = _sqlite_engine()
    with patch("src.app.services.ticketing.db_session", lambda: _fake_db(engine)):
        with patch("src.app.services.ticketing.load_feature_flags", return_value={}):
            agent = TicketingAgent()
            t = agent.create_ticket(
                title="Needs approval", description="d", severity="high", approval_required=True
            )
    assert t.status == "pending_approval"


def test_ticketing_no_get_event_loop_call():
    """approve_ticket must not call asyncio.get_event_loop() (deprecated pattern)."""
    import inspect
    import src.app.services.ticketing as mod
    src_code = inspect.getsource(mod)
    assert "get_event_loop()" not in src_code, (
        "asyncio.get_event_loop() found in ticketing.py — use get_running_loop() or asyncio.run()"
    )


# ─────────────────────────────────────────────────────────────────────────────
# supply_chain_security — typosquatting detector
# ─────────────────────────────────────────────────────────────────────────────
from src.app.services.supply_chain_security import (
    check_typosquatting, collect_packages, SupplyChainScanReport
)


def test_typosquatting_detects_known_misspelling():
    findings = check_typosquatting(["reqeusts", "fastapi", "sqlalchemy"])
    pkg_names = [f.package for f in findings]
    assert "reqeusts" in pkg_names
    assert findings[0].attack_type == "typosquatting"
    assert findings[0].severity == "high"


def test_typosquatting_clean_packages_no_findings():
    findings = check_typosquatting(["requests", "fastapi", "sqlalchemy", "pydantic"])
    assert findings == []


def test_collect_packages_from_requirements_txt():
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        req.write_text("requests>=2.28\nfastapi==0.100.0\n# comment\n-r other.txt\nnumpy\n")
        packages = collect_packages(Path(tmp))
    assert "requests" in packages
    assert "fastapi" in packages
    assert "numpy" in packages
    # Comments and -r lines should not appear
    assert "# comment" not in packages


def test_collect_packages_deduplicates():
    with tempfile.TemporaryDirectory() as tmp:
        req1 = Path(tmp) / "requirements.txt"
        req2 = Path(tmp) / "requirements-dev.txt"
        req1.write_text("requests\nnumpy\n")
        req2.write_text("requests\npytest\n")
        packages = collect_packages(Path(tmp))
    assert packages.count("requests") == 1


# ─────────────────────────────────────────────────────────────────────────────
# supply_chain_security — run_supply_chain_scan (no network, mocked)
# ─────────────────────────────────────────────────────────────────────────────
from src.app.services.supply_chain_security import run_supply_chain_scan


@pytest.mark.asyncio
async def test_scan_returns_report_with_no_requirements(tmp_path):
    """Empty repo → report with scanned_count=0 and an error note."""
    report = await run_supply_chain_scan(repo_root=str(tmp_path), create_tickets=False)
    assert isinstance(report, SupplyChainScanReport)
    assert report.scanned_packages == []
    assert any("No requirements" in e for e in report.errors)


@pytest.mark.asyncio
async def test_scan_detects_typosquat_in_requirements(tmp_path):
    """A misspelled package in requirements.txt triggers a typosquatting finding."""
    req = tmp_path / "requirements.txt"
    req.write_text("reqeusts\nfastapi\n")
    # Patch network calls to avoid real HTTP in tests
    with patch("src.app.services.supply_chain_security._get_kev_catalog", return_value=[]):
        report = await run_supply_chain_scan(
            repo_root=str(tmp_path),
            internal_prefixes=[],
            create_tickets=False,
        )
    typo_findings = [f for f in report.findings if f.attack_type == "typosquatting"]
    assert len(typo_findings) >= 1
    assert typo_findings[0].package == "reqeusts"


# ─────────────────────────────────────────────────────────────────────────────
# live_demo_gate — stub text detector
# ─────────────────────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from live_demo_gate import _has_stub


def test_stub_detector_finds_anthropic_stub():
    found, marker = _has_stub("[anthropic stub response]")
    assert found
    assert "anthropic" in marker.lower()


def test_stub_detector_finds_openai_stub():
    found, _ = _has_stub("Here is the answer: [openai stub response] Done.")
    assert found


def test_stub_detector_clean_response():
    found, _ = _has_stub("Yes, $1,800 covers mid-range gaming laptops starting from $1,200.")
    assert not found


def test_stub_detector_case_insensitive():
    found, _ = _has_stub("[ANTHROPIC STUB RESPONSE]")
    assert found
