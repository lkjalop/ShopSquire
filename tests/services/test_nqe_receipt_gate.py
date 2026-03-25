"""Tests for NQE receipt/serial verification gate."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.app.flows.nqe import NQEInput, NextQuestionEngine


def _make_engine():
    rag = MagicMock()
    rag.retrieve.return_value = []
    templates = MagicMock()
    templates.get_templates.return_value = []
    return NextQuestionEngine(rag=rag, templates=templates)


def test_receipt_gate_fires_on_high_risk():
    engine = _make_engine()
    inp = NQEInput(
        intent="return_request",
        product_category="laptop",
        risk_score=65.0,              # > 50 threshold
        image_identity_confidence=1.0,
        has_image=False,
        previously_asked_ids=[],
        answered_fields={},
        missing_fields=[],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" in ids


def test_receipt_gate_fires_on_low_cv_confidence():
    engine = _make_engine()
    inp = NQEInput(
        intent="return_request",
        product_category="laptop",
        risk_score=0.0,
        image_identity_confidence=0.45,   # < 0.6 threshold
        has_image=True,
        previously_asked_ids=[],
        answered_fields={},
        missing_fields=[],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" in ids


def test_receipt_gate_fires_on_high_value():
    engine = _make_engine()
    inp = NQEInput(
        intent="warranty_claim",
        product_category="laptop",
        risk_score=0.0,
        image_identity_confidence=1.0,
        has_image=False,
        previously_asked_ids=[],
        answered_fields={"item_value": 1200},   # > $500
        missing_fields=[],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" in ids


def test_receipt_gate_suppressed_when_already_asked():
    engine = _make_engine()
    inp = NQEInput(
        intent="return_request",
        product_category="laptop",
        risk_score=80.0,
        image_identity_confidence=0.3,
        has_image=True,
        previously_asked_ids=["receipt_verification"],   # already asked
        answered_fields={},
        missing_fields=[],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" not in ids


def test_receipt_gate_suppressed_for_product_search():
    """Normal product search should NOT trigger receipt gate."""
    engine = _make_engine()
    inp = NQEInput(
        intent="product_search",
        product_category="laptop",
        risk_score=0.0,
        image_identity_confidence=1.0,
        has_image=False,
        previously_asked_ids=[],
        answered_fields={},
        missing_fields=["budget"],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" not in ids


def test_receipt_gate_suppressed_when_proof_confirmed():
    engine = _make_engine()
    inp = NQEInput(
        intent="return_request",
        product_category="laptop",
        risk_score=90.0,
        image_identity_confidence=0.2,
        has_image=True,
        previously_asked_ids=[],
        answered_fields={"receipt_uploaded": True},   # proof already given
        missing_fields=[],
    )
    questions = engine.propose(inp)
    ids = [q.id for q in questions]
    assert "receipt_verification" not in ids
