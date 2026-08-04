"""Formal Exception Model (1.4) + exception-resolver consumer (1.3) tests.

The terminality proof is the important one: it asserts no authorization path can
fall through to an un-handled outcome — every (action × condition × value ×
compromise) scenario yields a terminal the policy DECLARES and the resolver
HANDLES, and an unknown terminal fails closed to governance.
"""
from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.security.authorization_engine import authorize, AuthorizationContext, load_policy
from src.app.services.exception_resolver import (
    TERMINAL_RESOLUTIONS,
    DISP_GOVERNANCE,
    resolve_terminal,
    resolve_open_exceptions,
)


# ── 1.4 Formal Exception Model: terminality / no fall-through ─────────────────
def test_every_declared_terminal_has_a_resolution():
    policy = load_policy(force=True)
    for t in policy["terminal_outcomes"]:
        assert t in TERMINAL_RESOLUTIONS, f"declared terminal '{t}' has no resolver mapping"


def test_unknown_terminal_fails_closed_to_governance():
    r = resolve_terminal("totally_made_up_outcome")
    assert r.autonomous is False
    assert r.resolution_status == DISP_GOVERNANCE


def test_engine_never_emits_an_unhandled_terminal():
    policy = load_policy(force=True)
    declared = set(policy["terminal_outcomes"])

    scenarios = []
    for action, spec in policy["actions"].items():
        scenarios += [
            AuthorizationContext(action=action, requester="x", confidence=1.0),
            AuthorizationContext(action=action, requester="x", confidence=0.0),           # confidence floor
            AuthorizationContext(action=action, requester="x", value_usd=1e9),            # value band
            AuthorizationContext(action=action, requester="x",
                                 signals=frozenset({"prompt_injection_detected"})),       # compromise
            AuthorizationContext(action=action, requester="not_in_lane"),                 # out_of_lane
        ]
        for cond in (spec.get("prohibited_when") or []):
            scenarios.append(AuthorizationContext(action=action, requester="x",
                                                  conditions=frozenset({cond})))
    scenarios.append(AuthorizationContext(action="does_not_exist", requester="x"))        # unknown action

    for ctx in scenarios:
        d = authorize(ctx, policy)
        assert d.terminal_outcome, f"empty terminal for action={ctx.action}"
        assert d.terminal_outcome in declared, (
            f"action={ctx.action} emitted UNDECLARED terminal {d.terminal_outcome}"
        )
        assert d.terminal_outcome in TERMINAL_RESOLUTIONS, (
            f"terminal {d.terminal_outcome} has no resolver disposition"
        )


def test_only_governance_terminal_is_non_autonomous():
    # The doctrine: escalate_governance is the ONE allowed non-autonomous terminal.
    non_auto = {k for k, v in TERMINAL_RESOLUTIONS.items() if not v.autonomous}
    assert non_auto == {"escalate_governance"}


# ── 1.3 Resolver worker drives every open row to a terminal disposition ───────
@pytest.fixture
def sqlite_db(monkeypatch):
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(bind=eng)
    with eng.begin() as c:
        c.exec_driver_sql(
            """
            CREATE TABLE exception_queue (
                id TEXT PRIMARY KEY, trace_id TEXT, action TEXT, requester TEXT,
                terminal_outcome TEXT, reason TEXT, subject_id TEXT, value_usd REAL,
                residual TEXT, status TEXT DEFAULT 'open', resolved_outcome TEXT,
                created_at TEXT, resolved_at TEXT
            )
            """
        )
    import src.app.models.db as dbmod

    @contextlib.contextmanager
    def fake_session():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(dbmod, "db_session", fake_session)
    return Session


def test_resolver_drives_all_open_rows_to_terminal(sqlite_db):
    Session = sqlite_db
    s = Session()
    for i, outcome in enumerate(["reject_under_policy", "escalate_governance", "defer_retry", "quarantine"]):
        s.execute(text(
            "INSERT INTO exception_queue (id, action, requester, terminal_outcome, status, created_at) "
            "VALUES (:id, 'refund', 'x', :o, 'open', :ts)"
        ), {"id": f"e{i}", "o": outcome, "ts": f"t{i}"})
    s.commit(); s.close()

    summary = resolve_open_exceptions()
    assert summary["scanned"] == 4
    assert summary["resolved"] == 2          # reject_under_policy + quarantine
    assert summary["governance_open"] == 1   # escalate_governance
    assert summary["retry_scheduled"] == 1   # defer_retry

    s2 = Session()
    open_left = s2.execute(text("SELECT count(*) FROM exception_queue WHERE status = 'open'")).scalar()
    s2.close()
    assert open_left == 0  # the guarantee: nothing stays open


def test_resolver_is_idempotent(sqlite_db):
    Session = sqlite_db
    s = Session()
    s.execute(text(
        "INSERT INTO exception_queue (id, action, requester, terminal_outcome, status, created_at) "
        "VALUES ('e1', 'refund', 'x', 'reject_under_policy', 'open', 't0')"
    ))
    s.commit(); s.close()
    first = resolve_open_exceptions()
    second = resolve_open_exceptions()  # nothing left open
    assert first["scanned"] == 1
    assert second["scanned"] == 0


# ── domain enqueue (market-intel / procurement) reaches a governed disposition ──
def test_enqueue_exception_is_resolvable(sqlite_db):
    from src.app.services.exception_resolver import enqueue_exception
    ok = enqueue_exception(domain="procurement", terminal_outcome="no_approved_supplier", ref_id="fc-1")
    assert ok is True
    summary = resolve_open_exceptions()
    assert summary["scanned"] == 1 and summary["resolved"] == 1  # autonomously resolved, not stuck open


def test_new_domain_terminals_all_have_a_resolution_and_stay_autonomous():
    for t in ("no_approved_supplier", "quote_parse_failed", "supplier_response_quarantined",
              "recipient_blocked", "stale_signal", "pipeline_error", "buyer_declined"):
        r = resolve_terminal(t)
        assert r.resolution_status in ("resolved", "retry_scheduled"), f"{t} fell through to governance"
    # doctrine intact: escalate_governance is still the ONLY non-autonomous terminal
    non_auto = {k for k, v in TERMINAL_RESOLUTIONS.items() if not v.autonomous}
    assert non_auto == {"escalate_governance"}


def test_ensure_exception_table_repairs_legacy_schema():
    # a table created with the OLD db.py schema (no terminal_outcome/resolved_outcome) must be repaired
    from sqlalchemy import create_engine, text as _t
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.app.services.exception_resolver import ensure_exception_table
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE exception_queue (id TEXT PRIMARY KEY, tenant_id TEXT, domain TEXT, "
                          "kind TEXT, payload TEXT, outcome TEXT, status TEXT, created_at TEXT, resolved_at TEXT)")
    s = sessionmaker(bind=eng)()
    ensure_exception_table(s)
    cols = {r[1] for r in s.execute(_t("PRAGMA table_info(exception_queue)")).fetchall()}
    s.close()
    assert {"terminal_outcome", "resolved_outcome", "ref_id"} <= cols
