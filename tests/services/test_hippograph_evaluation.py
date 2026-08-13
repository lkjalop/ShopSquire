from src.app.services.hippograph_evaluation import evaluate_recall, evaluate_recommendations


def test_recall_and_recommendation_metrics_are_distinct_contracts():
    recall = evaluate_recall(["publisher:good", "product:bad"], {"publisher:good"}, k=2)
    recommendation = evaluate_recommendations(
        ["product:bad", "product:good"], {"product:bad": 0, "product:good": 2}, k=2,
    )
    assert recall.schema_version == "hippograph-recall-eval-v1"
    assert recall.precision_at_k == 0.5 and recall.reciprocal_rank == 1.0
    assert recommendation.schema_version == "recommendation-relevance-eval-v1"
    assert 0 < recommendation.ndcg_at_k < 1
    assert recall.purpose != recommendation.purpose


def test_duplicate_ids_cannot_inflate_metrics():
    recall = evaluate_recall(["x", "x", "y"], {"x", "y"}, k=2)
    recommendation = evaluate_recommendations(["p", "p"], {"p": 2}, k=2)
    assert recall.relevant_recalled == ["x", "y"]
    assert recommendation.directly_relevant_count == 1
