from src.app.services.agentic_rag_pipeline import run_agentic_rag_pipeline


def test_agentic_rag_pipeline_returns_context_ids_and_citations():
    out = run_agentic_rag_pipeline(
        question="How do I do a warranty return for broken screen?",
        trace_id="rag-test-1",
        context_budget_chars=1200,
        max_chunks=4,
    )
    assert out["status"] == "ok"
    assert out["pipeline"] == "agentic_rag"
    assert isinstance(out.get("context_ids"), list)
    assert out["context_used_chars"] <= out["context_budget_chars"]
    assert "verification" in out

