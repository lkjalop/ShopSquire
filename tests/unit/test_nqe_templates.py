import pytest

from src.app.flows.nqe import NQEInput, NextQuestionEngine
from src.app.flows.catalog import QuestionTemplateCatalog
from src.app.rag.retrieve import Retriever


def test_nqe_product_search_missing_budget_usecase_brand():
    engine = NextQuestionEngine(Retriever(), QuestionTemplateCatalog())
    inp = NQEInput(
        intent="product_search",
        product_category="laptop",
        symptom=None,
        timeline_days=None,
        risk_score=0.0,
        missing_fields=["budget", "use_case", "brand_preference"],
        tenant_id=None,
        trace_id="TEST-TRACE",
    )
    qs = engine.propose(inp)
    ids = {q.id for q in qs}
    # Ensure key templates are present when the corresponding fields are missing
    assert any(i in ids for i in ("ask_budget_tier", "ask_budget")), "Expected budget question template"
    assert "ask_platform" in ids or "ask_use_case" in ids, "Expected platform/use-case question template"
    assert "ask_brand_pref" in ids, "Expected brand preference question template"
