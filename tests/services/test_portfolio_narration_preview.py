from src.app.services.portfolio_narration_preview import (
    ShelfNarrationProjection,
    render_portfolio_narration_preview,
)


def _projection() -> ShelfNarrationProjection:
    return ShelfNarrationProjection(
        purpose="Factory I/O",
        accepted_requirements=[],
        shelf_summary="These options are conditional for Factory I/O.",
        top_product_sentences=[{
            "sku": "P1", "sentence": "Product One has verified RAM; GPU remains not verified.",
            "evidence_basis": "conditional",
        }],
        reranking_summary="Research did not change the order.",
    )


def test_disabled_preview_is_deterministic_and_has_no_authority():
    result = render_portfolio_narration_preview(_projection(), enabled=False)
    assert result["renderer"] == "deterministic"
    assert result["buyer_visible_model_copy"] is False
    assert result["commercial_authority_granted"] is False
    assert "Product One" in result["text"]


def test_critic_accepted_exact_blocks_can_be_previewed():
    projection = _projection()
    expected = " ".join([
        projection.shelf_summary,
        projection.top_product_sentences[0].sentence,
        projection.reranking_summary,
    ])
    result = render_portfolio_narration_preview(
        projection, enabled=True, generate=lambda _prompt: expected,
    )
    assert result["status"] == "accepted_preview"
    assert result["renderer"] == "local_model_preview"
    assert result["commercial_authority_granted"] is False


def test_hallucinated_preview_falls_back_to_deterministic_copy():
    result = render_portfolio_narration_preview(
        _projection(), enabled=True, generate=lambda _prompt: "Perfect at 240 FPS.",
    )
    assert result["status"] == "deterministic_fallback"
    assert result["renderer"] == "deterministic"
    assert result["violations"]
    assert "Product One" in result["text"]
