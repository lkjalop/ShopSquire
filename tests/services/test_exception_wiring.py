"""Step-10 wiring: a terminal failure in procurement (a FAILURE_STATE transition) or market-intel (a
pipeline error) is routed into the governed exception queue via enqueue_exception — not silently dead-ended."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services.fulfillment import workflow as wf
from src.app.services.fulfillment.domain import Actor, ActorType as A


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def AG():
    return Actor(A.AGENT, "agent")


def test_procurement_failure_state_enqueues_governed_exception(db, monkeypatch):
    calls = []
    import src.app.services.exception_resolver as er
    monkeypatch.setattr(er, "enqueue_exception", lambda **kw: calls.append(kw) or True)
    # drive a case to COMMITTED, then fire the no_approved_supplier failure transition
    cid = wf.open_case(db, buyer_uid_hash="u", source_trace_id="T", requested_by="r", now_iso="2026-06-27 09:00:00")
    db.commit()
    wf.transition(db, case_id=cid, event="availability_assessed", actor=AG(),
                  state_patch={"availability": {"shortfall": 6}}, now_iso="2026-06-27 09:00:01")
    wf.transition(db, case_id=cid, event="request_buyer_commitment", actor=AG(), now_iso="2026-06-27 09:00:02")
    wf.transition(db, case_id=cid, event="buyer_committed", actor=Actor(A.BUYER, "u"), now_iso="2026-06-27 09:05:00")
    res = wf.transition(db, case_id=cid, event="no_approved_supplier", actor=AG(), now_iso="2026-06-27 09:05:10")
    assert res.ok and res.state == "NO_APPROVED_SUPPLIER"
    assert any(c.get("domain") == "procurement" and c.get("terminal_outcome") == "no_approved_supplier"
               and c.get("ref_id") == cid for c in calls), calls
    # a NON-failure transition must NOT enqueue
    assert all(c.get("terminal_outcome") != "committed" for c in calls)


def test_every_failure_state_resolves_to_a_modelled_disposition():
    """Completeness RATCHET: every procurement FAILURE_STATE must map to a MODELLED terminal resolution,
    not the fail-closed-to-governance fallback. The workflow enqueues `dst.value.lower()`, so each failure
    state's lower-cased value must be a TERMINAL_RESOLUTIONS key. If a new failure state is added without a
    resolution, this fails (instead of silently leaning on the unknown fallback at runtime)."""
    from src.app.services.exception_resolver import TERMINAL_RESOLUTIONS, resolve_terminal
    from src.app.services.fulfillment.domain import FAILURE_STATES

    missing = [s.value for s in FAILURE_STATES if s.value.lower() not in TERMINAL_RESOLUTIONS]
    assert not missing, f"FAILURE_STATES with no TERMINAL_RESOLUTIONS entry: {missing}"
    for s in FAILURE_STATES:
        res = resolve_terminal(s.value.lower())
        # a modelled outcome must NOT land on the unknown→governance fallback note
        assert "unknown terminal" not in res.note, f"{s.value} hit the fail-closed fallback"


def test_unmodelled_terminal_fails_closed_to_governance():
    from src.app.services.exception_resolver import DISP_GOVERNANCE, resolve_terminal
    res = resolve_terminal("a_brand_new_unmapped_outcome")
    assert res.resolution_status == DISP_GOVERNANCE and not res.autonomous


def test_market_pipeline_error_enqueues_market_exception(monkeypatch):
    calls = []
    import src.app.services.exception_resolver as er
    monkeypatch.setattr(er, "enqueue_exception", lambda **kw: calls.append(kw) or True)
    import src.app.services.market_pipeline as mp
    import src.app.services.market_signal_adapters as msa

    def _boom(*a, **k):
        raise RuntimeError("ingest exploded")
    monkeypatch.setattr(msa, "backfill_from_db", _boom)  # run_pipeline imports it from here
    res = mp.run_pipeline(object())  # truthy db; backfill raises inside the try
    assert res["findings"] == 0 and res["persisted"] == 0  # safe zero-result shape preserved
    assert any(c.get("domain") == "market" and c.get("terminal_outcome") == "pipeline_error" for c in calls), calls
