"""safe_stage — observable partial-failure wrapper (P1 reliability).

Locks the contract: success passes through; failure returns the default, logs a warning, and emits
a `stage_partial_failure` trace event (so the silent-except class that hid the ASUS bug is now
auditable). The trace sink must never re-raise.
"""
from __future__ import annotations

import logging

import src.app.services.safe_stage as ss
from src.app.services.safe_stage import safe_stage


def test_success_passes_through():
    assert safe_stage("ok", lambda: 42, default=-1) == 42


def test_failure_returns_default():
    assert safe_stage("boom", lambda: (_ for _ in ()).throw(ValueError("x")), default="fallback") == "fallback"


def test_failure_emits_trace_event(monkeypatch):
    events = []
    monkeypatch.setattr(
        "src.app.services.decision_log.log_trace_event",
        lambda *a, **k: events.append((a, k)),
    )
    out = safe_stage("image_grounding", lambda: 1 / 0, default=None, trace_id="t-1", extra={"uid": "u1"})
    assert out is None
    assert events, "expected a stage_partial_failure trace event"
    args, _ = events[0]
    # positional: trace_id, event_type, source_type, source_id(stage), target_type, target_id, payload
    assert args[1] == "stage_partial_failure"
    assert args[3] == "image_grounding"
    payload = args[6]
    assert payload["degraded"] is True
    assert payload["uid"] == "u1"
    assert "ZeroDivisionError" in payload["error"]


def test_trace_sink_failure_never_propagates(monkeypatch, caplog):
    def _raise(*a, **k):
        raise RuntimeError("trace backend down")
    monkeypatch.setattr("src.app.services.decision_log.log_trace_event", _raise)
    with caplog.at_level(logging.WARNING):
        # stage fails AND the trace sink fails — must still return default, not raise.
        assert safe_stage("price_fallback", lambda: 1 / 0, default=[], trace_id="t-2") == []


def test_logs_warning_on_failure(caplog):
    with caplog.at_level(logging.WARNING):
        safe_stage("nqe", lambda: 1 / 0, default=None)
    assert any("stage_partial_failure" in r.message and "nqe" in r.message for r in caplog.records)
