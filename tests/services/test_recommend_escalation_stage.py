"""Escalation/trace-decoration stage (extracted from suggest()). Verifies the auto path and the
review/human path (envelope + incident), with all assessors injected."""
from __future__ import annotations

from types import SimpleNamespace

from src.app.services.recommend_escalation_stage import decorate_escalation


def _b2b(verdict="consumer", wants=False):
    return SimpleNamespace(verdict=verdict, wants_procurement_questions=wants,
                           to_dict=lambda: {"verdict": verdict, "wants_procurement_questions": wants})


def _decision(band="auto", reasons=None, talk=False):
    rs = reasons or []
    return SimpleNamespace(band=band, reasons=rs, talk_to_client=talk,
                           to_dict=lambda: {"band": band, "reasons": rs, "talk_to_client": talk})


def _decompose(_q):
    return SimpleNamespace(decomposition_confidence=1.0)


def test_auto_band_surfaces_assessments_without_review():
    payload = {}
    incidents = []
    decorate_escalation(
        payload, constraints={"order_quantity": 1}, analysis={"details": {}}, results=[{"price_cents": 99900}],
        query="laptop under 1000", claim_guard_result="disabled", trace_id="T", uid="u",
        assess_escalation=lambda **kw: _decision("auto"), decompose=_decompose,
        assess_b2b_intent=lambda q, quantity=1: _b2b("consumer"),
        auto_create_incident=lambda **kw: incidents.append(kw))
    assert payload["b2b_assessment"]["verdict"] == "consumer"
    assert payload["escalation_assessment"]["band"] == "auto"
    assert "needs_human_review" not in payload and "escalation" not in payload
    assert incidents == []


def test_review_band_sets_envelope_and_creates_incident():
    payload = {"approval_id": "appr-1"}
    incidents = []
    decorate_escalation(
        payload, constraints={"order_quantity": 50, "availability_horizon_days": 5},
        analysis={"details": {"risk_adj": 0.4}}, results=[{"price_cents": 150000}],
        query="50 laptops in 5 days", claim_guard_result="disabled", trace_id="T", uid="u",
        assess_escalation=lambda **kw: _decision("review", ["needs review"], talk=True), decompose=_decompose,
        assess_b2b_intent=lambda q, quantity=1: _b2b("ambiguous_bulk", wants=True),
        auto_create_incident=lambda **kw: incidents.append(kw))
    assert payload["needs_human_review"] is True
    env = payload["escalation"]
    assert env["route"] == "human_review" and env["band"] == "review" and env["talk_to_client"] is True
    assert env["approval_required"] is True   # approval_id present
    assert len(incidents) == 1 and incidents[0]["severity"] == "warn"


def test_human_required_is_high_severity_and_blocking():
    payload = {}
    incidents = []
    decorate_escalation(
        payload, constraints={"order_quantity": 1000000}, analysis={"details": {}}, results=[],
        query="buy 1000000 laptops", claim_guard_result="disabled", trace_id="T", uid="u",
        assess_escalation=lambda **kw: _decision("human_required", ["anomalous"]), decompose=_decompose,
        assess_b2b_intent=lambda q, quantity=1: _b2b("anomalous"),
        auto_create_incident=lambda **kw: incidents.append(kw))
    assert payload["escalation"]["blocking"] is True and payload["escalation"]["approval_required"] is True
    assert incidents[0]["severity"] == "high"
