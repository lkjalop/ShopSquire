from src.app.services.research_explainability_projection import (
    project_research_explainability,
)


def test_projection_exposes_concise_receipt_and_only_typed_decision_inputs():
    research = {
        "claims": [{
            "claim_id": "c1", "attribute": "operating_system", "operator": "in",
            "value": ["Windows 11"], "source_id": "factory_io", "freshness_status": "fresh",
            "raw_html": "must never cross the narration boundary",
        }],
        "context_claims": [], "unresolved": [],
        "source_execution": [{"source_id": "factory_io", "publisher": "Factory I/O"}],
    }
    shelves = {"shelves": [{"initial": [{
        "identity_key": "p1", "title": "Workstation A", "fit_status": "conditional",
        "product": {"sku": "A"}, "unknowns": ["GPU TGP is not verified"],
    }]}]}

    receipt, narration = project_research_explainability(
        purpose="Run Factory I/O", research=research, shelves=shelves, delta=[],
    )

    assert receipt.summary == (
        "Researched Factory I/O's official requirements. 1 requirement was established; "
        "product identity and availability remain separately verified."
    )
    assert narration.top_product_sentences[0].sentence == (
        "Workstation A remains conditional because GPU TGP is not verified."
    )
    assert "raw_html" not in narration.model_dump_json()


def test_projection_names_verified_failure_and_rank_movement():
    shelves = {"shelves": [{"initial": [{
        "identity_key": "p1", "title": "Laptop B", "fit_status": "failed",
        "product": {"sku": "B"}, "misses": ["Windows Pro required"],
    }]}]}
    _receipt, narration = project_research_explainability(
        purpose="CAD", research={"claims": [], "context_claims": [], "unresolved": []},
        shelves=shelves,
        delta=[{"sku": "B", "movement": -2, "reason": "verified OS incompatibility"}],
    )
    assert narration.top_product_sentences[0].evidence_basis == "failed"
    assert "not qualified" in narration.top_product_sentences[0].sentence
    assert "verified OS incompatibility" in narration.reranking_summary
