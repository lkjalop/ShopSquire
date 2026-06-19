"""NQE question packs are PER-REQUEST profile-scoped — no electronics bleed.

Proves that NextQuestionEngine.propose() fires domain-specific questions from the
active StoreProfile's nqe_question_packs, and that a pharmacy/fashion request never
gets gaming/laptop/GPU clarifying questions.
"""
from __future__ import annotations

import contextlib
from unittest.mock import MagicMock

from src.app.flows.nqe import NQEInput, NextQuestionEngine
from src.app.platform.store_profile import (
    reset_active_profile_id,
    reset_cache,
    set_active_profile_id,
)


@contextlib.contextmanager
def _vertical(pid: str):
    reset_cache()
    token = set_active_profile_id(pid)
    try:
        yield
    finally:
        reset_active_profile_id(token)
        reset_cache()


def _make_engine() -> NextQuestionEngine:
    """Minimal NQE engine with stub RAG and templates."""
    rag = MagicMock()
    rag.retrieve = MagicMock(return_value=[])
    rag.embedder = None
    templates = MagicMock()
    templates.get_templates = MagicMock(return_value=[])
    return NextQuestionEngine(rag=rag, templates=templates)


def _question_ids(questions) -> set:
    return {q.id for q in questions}


# ── Electronics: existing questions fire ──

class TestElectronicsNQEPacks:
    def test_high_school_fires(self):
        with _vertical("electronics"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="laptop",
                query="laptop for high school",
                detected_use_case="high_school",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            assert "ask_high_school_activity" in _question_ids(qs)

    def test_university_fires(self):
        with _vertical("electronics"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="laptop",
                query="laptop for university",
                detected_use_case="university_general",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            assert "ask_university_subject" in _question_ids(qs)

    def test_gaming_fires(self):
        with _vertical("electronics"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="laptop",
                query="gaming laptop",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            assert "ask_gaming_depth" in _question_ids(qs)

    def test_corporate_fires(self):
        with _vertical("electronics"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="laptop",
                query="office work laptop for business",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            assert "ask_corporate_work_type" in _question_ids(qs)


# ── Pharmacy: fires pharmacy questions, NOT electronics ──

class TestPharmacyNQEPacks:
    def test_pain_relief_fires_symptom_type(self):
        with _vertical("pharmacy"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="medicine",
                query="something for my headache",
                detected_use_case="pain_relief",
                missing_fields=["symptom_type"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_symptom_type" in ids

    def test_allergy_fires_drowsy_pref(self):
        with _vertical("pharmacy"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="medicine",
                query="antihistamine for hay fever",
                detected_use_case="allergy",
                missing_fields=["drowsy_preference"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_drowsy_preference" in ids

    def test_no_gaming_question_under_pharmacy(self):
        """Gaming/laptop NQE questions must NEVER fire under pharmacy profile."""
        with _vertical("pharmacy"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="medicine",
                query="gaming laptop rtx 4070",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_gaming_depth" not in ids
            assert "ask_high_school_activity" not in ids
            assert "ask_university_subject" not in ids
            assert "ask_corporate_work_type" not in ids

    def test_vitamins_fires_health_goal(self):
        with _vertical("pharmacy"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="supplement",
                query="vitamin supplement for immune support",
                detected_use_case="vitamins",
                missing_fields=["health_goal"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_health_goal" in ids


# ── Fashion: fires fashion questions, NOT electronics ──

class TestFashionNQEPacks:
    def test_casual_fires_occasion(self):
        with _vertical("fashion"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="top",
                query="casual everyday shirt",
                detected_use_case="casual",
                missing_fields=["occasion"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_occasion" in ids

    def test_athletic_fires_activity(self):
        with _vertical("fashion"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="shoes",
                query="running shoes for gym",
                detected_use_case="athletic",
                missing_fields=["activity_type"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_activity" in ids

    def test_outdoor_fires_climate(self):
        with _vertical("fashion"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="outerwear",
                query="jacket for hiking in cold weather",
                detected_use_case="outdoor",
                missing_fields=["climate"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_climate" in ids

    def test_no_electronics_questions_under_fashion(self):
        """Electronics NQE questions must NEVER fire under fashion profile."""
        with _vertical("fashion"):
            engine = _make_engine()
            inp = NQEInput(
                intent="recommend",
                product_category="shoes",
                query="gaming laptop high school student",
                detected_use_case="high_school",
                missing_fields=["use_case"],
            )
            qs = engine.propose(inp)
            ids = _question_ids(qs)
            assert "ask_gaming_depth" not in ids
            assert "ask_high_school_activity" not in ids
            assert "ask_university_subject" not in ids
            assert "ask_corporate_work_type" not in ids
