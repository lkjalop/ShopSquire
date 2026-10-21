from src.app.services.recommendation_core.semantic_coverage import (
    sanitize_semantic_concept_spans,
    unresolved_purpose_proposal,
)


def test_budget_revision_consumes_its_qualifier_without_hiding_named_workloads():
    from src.app.services.budget_grammar import parse_budget
    query = 'cut it to 1300 max, for 3ds Max'
    parsed = parse_budget(query)
    assert parsed.budget_max == 1300
    start, end = parsed.source_span
    assert query[start:end].strip() == 'cut it to 1300 max'
    assert query[end:].strip() == ', for 3ds Max'


def test_run_relation_recalls_an_unknown_named_subject() -> None:
    proposal = unresolved_purpose_proposal(
        query="will a $3000 laptop run where winds meet?",
        use_cases=("gaming",),
        node_path="Electronics > Computers > Laptops",
    )

    assert proposal["concepts"][0]["query_span"] == "where winds meet"


def test_budget_tail_is_removed_from_model_concept_before_provider_lookup() -> None:
    proposal = sanitize_semantic_concept_spans(
        "what about for where winds meet is 3000 ok?",
        {
            "validation": "valid",
            "concepts": [{
                "text": "where winds meet is 3000 ok",
                "query_span": "where winds meet is 3000 ok",
                "status": "unresolved",
                "material": True,
            }],
        },
    )

    assert proposal["concepts"][0]["query_span"] == "where winds meet"
